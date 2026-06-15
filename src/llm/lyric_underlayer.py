"""Step 5 — place the cleaned lyrics under the notes, then validate the whole file.

Unlike steps 2/4, this step does **not** ask the LLM to rewrite the MusicXML. OMR scores
are large and regenerating the whole document to add a text layer reliably overran the
model's output budget. Instead the work is split: the **LLM aligns syllables to notes**
(small, bounded structured output) and the **code inserts** them as ``<lyric>`` via music21.

Per-voice alignment
-------------------
Choral music carries the same text in every voice (homophonic) or each voice sings the whole
text (polyphonic). A single LLM call asked to fill *all* parts at once was unreliable — it
typically returned syllables for the first part only, leaving the other voices empty. So we
align **one part at a time**: each call sees the song text plus that part's note sequence and
returns one entry per note. This guarantees every vocal part gets its lyrics, and keeps each
request small. Transient API errors (503/overload) on a single part are retried and, if they
still fail, that part is skipped rather than crashing the whole step.

The result is round-tripped through music21; on a hard failure the step-4 document is kept.
"""

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from src.llm.client import LLMClient
from src.llm.musicxml_validate import validate_musicxml

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


def underlay_lyrics(
    lyrics: str,
    musicxml: str,
    client: Optional[LLMClient] = None,
) -> UnderlayResult:
    """Underlay ``lyrics`` into every vocal part of ``musicxml`` and validate the result.

    The LLM produces a syllable-per-onset alignment **per part**; this function inserts the
    ``<lyric>`` elements with music21 and re-exports, so output size is bounded by the score.

    Args:
        lyrics: Cleaned lyrics from step 2.
        musicxml: Corrected MusicXML from step 4.
        client: Optional injected client (tests pass a mock).

    Returns:
        An :class:`UnderlayResult`; ``changed`` is False when no syllable could be placed
        or the result failed validation (the step-4 document is returned unchanged).
    """
    client = client or LLMClient()

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

    vocal_parts = [
        (idx, part, onsets)
        for idx, part in enumerate(score.parts)
        if not _is_instrumental(part) and (onsets := _part_onsets(part))
    ]
    if not vocal_parts:
        return _keep(
            musicxml,
            "⚠️ Partytura nie zawiera głosów wokalnych z nutami — zachowano plik z korekty.",
            "Brak głosów wokalnych z nutami.",
        )

    total_placed = 0
    parts_with_text = 0
    per_part: List[str] = []
    failures: List[int] = []
    for idx, _part, onsets in vocal_parts:
        try:
            syllables = _align_part(client, lyrics, onsets, idx)
        except Exception as exc:  # noqa: BLE001 - one failed part must not sink the rest
            logger.warning("underlay_lyrics: partia %s nieudana: %s", idx, exc)
            failures.append(idx)
            continue
        placed = _apply_syllables(onsets, syllables)
        total_placed += placed
        if placed:
            parts_with_text += 1
        per_part.append(f"głos {idx}: {placed}/{len(onsets)}")

    if total_placed == 0:
        return _keep(
            musicxml,
            "⚠️ Nie podłożono żadnej sylaby (możliwe błędy API) — zachowano plik z korekty.",
            "Plan podkładu nie umieścił żadnej sylaby.",
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
        f"Podłożono {total_placed} sylab w {parts_with_text} głosach (per-głos, music21). "
        f"Szczegóły: {', '.join(per_part)}."
    )
    if failures:
        report += f" Pominięte głosy (błąd API): {failures}."
    return UnderlayResult(musicxml=out_xml, report=report, changed=True, score=score)
