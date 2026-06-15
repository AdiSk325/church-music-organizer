"""Step 5 — place the cleaned lyrics under the notes, then validate the whole file.

Algorithm first, LLM only on the hard cases
-------------------------------------------
Underlay is mostly mechanical, so it is done **in pure Python** by
:mod:`src.services.lyric_alignment`: the text is syllabified and distributed over each voice's
notes using the melodic structure (slurs/ties mark melismas, rests mark phrase ends). This
needs no LLM — so the common, syllabic SATB case costs nothing and never times out.

Each part's algorithmic alignment carries a **confidence**. Only when a part scores below a
threshold (e.g. heavy melismas the score didn't mark, or a syllable/note mismatch) do we spend
an **LLM call to redo just that part** (bounded per-onset structured output, inserted by
music21). The backend is selectable via ``CMO_UNDERLAY_BACKEND`` (``auto`` | ``algo`` | ``llm``)
and the escalation threshold via ``CMO_UNDERLAY_LLM_THRESHOLD`` (default 0.6).

This replaces the previous "one LLM call per voice always" design, which was slow and reliably
timed out on real scores. Transient LLM failures fall back to the algorithmic result for that
part instead of crashing. The result is round-tripped through music21; on a hard failure the
step-4 document is kept.
"""

import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from src.llm.client import LLMClient, make_client
from src.llm.musicxml_validate import validate_musicxml
from src.services.lyric_alignment import align_part, extract_phrases, syllabify_text

try:  # pydantic ships with google-genai; degrade gracefully when neither is installed
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - exercised only without google-genai/pydantic

    class BaseModel:  # minimal stand-in so this module imports without pydantic
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def Field(default=None, **_kwargs):  # type: ignore
        return default


logger = logging.getLogger(__name__)

_SYLLABIC = {"single", "begin", "middle", "end"}

# Part-name hints for staves that should NOT receive lyrics (instrumental accompaniment).
_INSTRUMENT_HINTS = (
    "piano", "klavier", "organ", "organy", "reduction", "redukcja",
    "accompan", "akompan", "instrument", "keyboard",
)

# Retry a part's alignment on transient server errors (Gemini 503 / overload).
_MAX_TRANSIENT_RETRIES = 2


@dataclass
class UnderlayResult:
    musicxml: str  # final document, or the step-4 document when underlay was rejected
    report: str  # validation / placement summary
    changed: bool  # True when a valid underlaid document was produced
    validation_error: Optional[str] = None
    score: Optional[Any] = None  # music21 Score with lyrics applied, available when changed=True


class OnsetSyllable(BaseModel):
    """One note onset's text: a syllable, or empty for a melisma continuation / no text."""

    text: str = Field(default="", description="Sylaba/słowo dla tej nuty; \"\" = brak tekstu "
                      "(przedłużenie melizmatu lub nuta bez tekstu).")
    syllabic: str = Field(default="single", description="single|begin|middle|end")


class PartSyllables(BaseModel):
    """Per-part syllable stream: one entry per note onset of a single vocal part."""

    syllables: List[OnsetSyllable] = Field(default_factory=list)
    notes: str = Field(default="")


_SYSTEM = """\
Jesteś ekspertem notacji wokalnej. Otrzymujesz (A) tekst pieśni oraz (B) listę nut JEDNEGO
głosu (partii) w kolejności dokumentu (wysokość + wartość rytmiczna). Ten głos śpiewa CAŁY
podany tekst. Twoje zadanie: dopasować tekst do nut, podkładając sylaby pod kolejne nuty.

ZASADY:
- Zwróć tablicę "syllables" o długości DOKŁADNIE równej liczbie podanych nut — jeden wpis na
  każdą nutę, w tej samej kolejności.
- Każdy wpis: "text" (sylaba lub słowo) i "syllabic" (single|begin|middle|end).
  * dziel wyrazy na sylaby: begin=pierwsza, middle=środkowa, end=ostatnia, single=jednosylabowy.
- MELIZMAT (jedna sylaba na kilka nut): pierwsza nuta dostaje sylabę, KOLEJNE nuty tej samej
  sylaby mają text="" — NIE powtarzaj sylaby.
- Nuty bez tekstu (przedłużenia, wstawki) mają text="".
- Rozłóż tekst tak, by sensownie pokrył wszystkie nuty melodyczne tego głosu.
- W "notes" napisz 1 zdanie o ewentualnych wątpliwościach.

Nie zwracaj MusicXML. Tylko dopasowanie sylab do nut tego jednego głosu.\
"""


def _load_score(musicxml: str):
    from music21 import converter

    return converter.parseData(musicxml, format="musicxml")


def _part_onsets(part) -> list:
    """Note onsets (notes + chords, no rests) of a part, in document order."""
    return list(part.recurse().notes)


def _is_instrumental(part) -> bool:
    name = (getattr(part, "partName", "") or "").lower()
    return any(hint in name for hint in _INSTRUMENT_HINTS)


def _pitch_token(n) -> str:
    """Compact pitch+duration token for a note/chord, to ground the LLM alignment."""
    try:
        if n.isChord:
            name = n.root().nameWithOctave if n.root() is not None else "chord"
        else:
            name = n.nameWithOctave
    except Exception:  # pragma: no cover - defensive
        name = "?"
    return f"{name}/{n.quarterLength}"


def _build_user_part(lyrics: str, onsets: list, part_index: int) -> str:
    seq = " ".join(_pitch_token(n) for n in onsets)
    return (
        f"Tekst pieśni (śpiewany przez ten głos):\n\n{lyrics}\n\n"
        f"Nuty tego głosu (part_index={part_index}, liczba nut: {len(onsets)}), w kolejności:\n"
        f"{seq}"
    )


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("503", "unavailable", "overloaded", "500", "deadline", "timeout"))


def _align_part(client: LLMClient, lyrics: str, onsets: list, part_index: int) -> List:
    """One LLM call to align ``lyrics`` to a single part's onsets; retries transient errors."""
    user = _build_user_part(lyrics, onsets, part_index)
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_TRANSIENT_RETRIES + 1):
        try:
            plan = client.parse(_SYSTEM, user, PartSyllables, step="lyrics")
            return list(getattr(plan, "syllables", None) or [])
        except Exception as exc:  # noqa: BLE001 - decide retry vs propagate below
            last_exc = exc
            if _is_transient(exc) and attempt < _MAX_TRANSIENT_RETRIES:
                logger.warning(
                    "underlay: przejściowy błąd API dla partii %s (próba %s) — ponawiam: %s",
                    part_index, attempt + 1, exc,
                )
                time.sleep(2 * (attempt + 1))
                continue
            raise
    assert last_exc is not None
    raise last_exc


def _apply_syllables(onsets: list, syllables: List) -> int:
    """Insert planned syllables for one part as music21 lyrics. Returns notes texted."""
    from music21 import note as m21note

    placed = 0
    for n, syl in zip(onsets, syllables):
        text = (getattr(syl, "text", "") or "").strip()
        if not text:
            continue  # melisma continuation / untexted note
        lyric = m21note.Lyric(text=text, number=1)
        syllabic = (getattr(syl, "syllabic", "single") or "single").strip().lower()
        if syllabic in _SYLLABIC:
            lyric.syllabic = syllabic
        n.lyrics.append(lyric)
        placed += 1
    return placed


def _apply_assignment(assignments: list) -> int:
    """Insert an algorithmic ``(note, text, syllabic)`` assignment as music21 lyrics."""
    from music21 import note as m21note

    placed = 0
    for note_el, text, syllabic in assignments:
        clean = (text or "").strip()
        if not clean:
            continue  # melisma continuation / untexted note
        lyric = m21note.Lyric(text=clean, number=1)
        syl = (syllabic or "single").strip().lower()
        if syl in _SYLLABIC:
            lyric.syllabic = syl
        note_el.lyrics.append(lyric)
        placed += 1
    return placed


def _export(score) -> str:
    """Eksportuj kompletny ``Score`` do tekstu MusicXML przez standardowy writer music21.

    Świadomie NIE używamy ``GeneralObjectExporter`` — traktował on obiekt jak „fragment"
    (stąd ``<movement-title>Music21 Fragment</movement-title>`` i gubienie struktury
    part-list). ``score.write('musicxml')`` daje kompletny, otwieralny dokument.
    """
    tmpdir = tempfile.mkdtemp(prefix="cmo_xml_")
    out_path = Path(tmpdir) / "score.musicxml"
    try:
        written = score.write("musicxml", fp=str(out_path))
        result_path = Path(written) if written else out_path
        return result_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _keep(musicxml: str, report: str, error: str) -> UnderlayResult:
    return UnderlayResult(musicxml=musicxml, report=report, changed=False, validation_error=error)


def _underlay_threshold() -> float:
    """Confidence below which a part is escalated to the LLM (env-tunable)."""
    try:
        return float(os.getenv("CMO_UNDERLAY_LLM_THRESHOLD", "0.6"))
    except ValueError:
        return 0.6


def underlay_lyrics(
    lyrics: str,
    musicxml: str,
    client: Optional[LLMClient] = None,
) -> UnderlayResult:
    """Underlay ``lyrics`` into every vocal part of ``musicxml`` and validate the result.

    Algorithmic by default (no LLM): :mod:`src.services.lyric_alignment` syllabifies the text
    and distributes it over each voice using slurs/ties/rests. Each part's alignment carries a
    confidence; only parts scoring below :func:`_underlay_threshold` are redone by the LLM
    (``CMO_UNDERLAY_BACKEND`` = ``auto`` default | ``algo`` never | ``llm`` always). A failed
    LLM call falls back to the algorithmic result for that part.

    Args:
        lyrics: Cleaned lyrics from step 2.
        musicxml: Corrected MusicXML from step 4.
        client: Optional injected LLM client (tests pass a mock); created lazily only if needed.

    Returns:
        An :class:`UnderlayResult`; ``changed`` is False when no syllable could be placed
        or the result failed validation (the step-4 document is returned unchanged).
    """
    backend = (os.getenv("CMO_UNDERLAY_BACKEND") or "auto").strip().lower()
    threshold = _underlay_threshold()

    try:
        score = _load_score(musicxml)
    except Exception as exc:
        logger.exception("underlay_lyrics: nie udało się sparsować MusicXML wejściowego")
        return _keep(
            musicxml,
            f"⚠️ Nie udało się wczytać partytury do podłożenia tekstu ({exc}) — "
            "zachowano plik z korekty.",
            str(exc),
        )

    syllables = syllabify_text(lyrics)
    if not syllables:
        return _keep(
            musicxml,
            "⚠️ Z tekstu nie udało się wyodrębnić sylab — zachowano plik z korekty.",
            "Brak sylab w tekście.",
        )

    vocal_parts = [
        (idx, part)
        for idx, part in enumerate(score.parts)
        if not _is_instrumental(part) and _part_onsets(part)
    ]
    if not vocal_parts:
        return _keep(
            musicxml,
            "⚠️ Partytura nie zawiera głosów wokalnych z nutami — zachowano plik z korekty.",
            "Brak głosów wokalnych z nutami.",
        )

    # Lazily-created LLM client, shared across parts; only built when a part needs it.
    llm: dict = {"client": client, "tried": client is not None}

    def _get_client():
        if not llm["tried"]:
            llm["tried"] = True
            try:
                llm["client"] = make_client()
            except Exception as exc:  # no backend available → stay algorithmic
                logger.info("underlay_lyrics: brak backendu LLM (%s) — tylko algorytm", exc)
                llm["client"] = None
        return llm["client"]

    total_placed = 0
    parts_with_text = 0
    per_part: List[str] = []
    for idx, part in vocal_parts:
        phrases = extract_phrases(part)
        algo = align_part(syllables, phrases)
        onsets = _part_onsets(part)

        want_llm = backend == "llm" or (backend == "auto" and algo.confidence < threshold)
        method = "algorytm"
        placed = 0
        if want_llm and backend != "algo":
            c = _get_client()
            if c is not None:
                try:
                    plan = _align_part(c, lyrics, onsets, idx)
                    placed = _apply_syllables(onsets, plan)
                    method = "LLM"
                except Exception as exc:  # noqa: BLE001 - fall back, don't sink the part
                    logger.warning(
                        "underlay_lyrics: LLM dla partii %s nieudany (%s) — używam algorytmu",
                        idx, exc,
                    )
                    placed = _apply_assignment(algo.note_assignments)
                    method = "algorytm (LLM nieudany)"
            else:
                placed = _apply_assignment(algo.note_assignments)
        else:
            placed = _apply_assignment(algo.note_assignments)

        total_placed += placed
        if placed:
            parts_with_text += 1
        per_part.append(
            f"głos {idx}: {placed}/{algo.slot_count} [{method}, pewność={algo.confidence}]"
        )

    if total_placed == 0:
        return _keep(
            musicxml,
            "⚠️ Nie podłożono żadnej sylaby — zachowano plik z korekty.",
            "Algorytm/LLM nie umieścił żadnej sylaby.",
        )

    try:
        out_xml = _export(score)
    except Exception as exc:
        logger.exception("underlay_lyrics: eksport music21 nie powiódł się")
        return _keep(
            musicxml,
            f"⚠️ Eksport MusicXML nie powiódł się ({exc}) — zachowano plik z korekty.",
            str(exc),
        )

    ok, error, _validated = validate_musicxml(out_xml)
    if not ok:
        logger.warning("underlay_lyrics: walidacja music21 odrzuciła wynik: %s", error)
        return _keep(
            musicxml,
            f"⚠️ Finalny plik nie przeszedł walidacji ({error}) — zachowano plik z korekty.",
            error or "walidacja nieudana",
        )

    report = (
        f"Podłożono {total_placed} sylab w {parts_with_text} głosach. "
        f"Szczegóły: {', '.join(per_part)}."
    )
    return UnderlayResult(musicxml=out_xml, report=report, changed=True, score=score)
