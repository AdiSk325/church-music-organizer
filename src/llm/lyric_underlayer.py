"""Step 5 — place the cleaned lyrics under the notes, then validate the whole file.

Unlike steps 2/4, this step does **not** ask the LLM to rewrite the MusicXML. OMR scores
are large (tens of thousands of tokens) and regenerating the whole document to add a text
layer reliably overran the model's output budget, truncating into invalid XML.

Instead the work is split:

* the **LLM aligns syllables to notes** — a small, bounded structured output: for each vocal
  part it returns one entry per note onset (a syllable, or an empty string for a melisma
  continuation / untexted note);
* the **code inserts** those syllables as ``<lyric>`` elements via music21 and re-exports the
  document.

The result is round-tripped through music21 (as in step 4); on any failure the step-4
document is kept unchanged.
"""

import logging
import shutil
import tempfile
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


class PartUnderlay(BaseModel):
    """Per-part syllable stream, one entry per note onset, in document order."""

    part_index: int
    syllables: List[OnsetSyllable] = Field(default_factory=list)


class UnderlayPlan(BaseModel):
    """The LLM's full alignment plan plus a short human-readable note."""

    parts: List[PartUnderlay] = Field(default_factory=list)
    notes: str = Field(default="")


_SYSTEM = """\
Jesteś ekspertem notacji wokalnej. Otrzymujesz (A) oczyszczony tekst pieśni oraz (B) opis
nut partytury: dla każdej partii (part_index) listę nut w kolejności dokumentu (wysokość +
wartość). Twoje zadanie: dopasować tekst do nut, podkładając sylaby pod kolejne nuty.

ZASADY:
- Dla KAŻDEJ partii wokalnej zwróć tablicę "syllables" o długości DOKŁADNIE równej liczbie
  podanych nut tej partii — jeden wpis na każdą nutę, w tej samej kolejności.
- Każdy wpis to: "text" (sylaba lub słowo) i "syllabic" (single|begin|middle|end).
  * dziel wyrazy na sylaby: begin=pierwsza, middle=środkowa, end=ostatnia, single=jednosylabowy.
- MELIZMAT (jedna sylaba na kilka nut): pierwsza nuta dostaje sylabę, a KOLEJNE nuty tej samej
  sylaby mają text="" (pusty) — NIE powtarzaj sylaby.
- Nuty bez tekstu (wstawki instrumentalne, przedłużenia) mają text="".
- Jeśli partia jest czysto instrumentalna lub nie niesie tekstu — zwróć dla niej pustą tablicę.
- W "notes" napisz krótko (1–2 zdania), jak rozłożono tekst i gdzie są wątpliwości.

Nie zwracaj MusicXML. Tylko dopasowanie sylab do nut.\
"""


def _load_score(musicxml: str):
    from music21 import converter

    return converter.parseData(musicxml, format="musicxml")


def _part_onsets(part) -> list:
    """Note onsets (notes + chords, no rests) of a part, in document order."""
    return list(part.recurse().notes)


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


def _build_user(lyrics: str, parts_onsets: List[list]) -> str:
    blocks = [f"Oczyszczony tekst pieśni (A):\n\n{lyrics}\n", "Opis nut partytury (B):"]
    for idx, onsets in enumerate(parts_onsets):
        seq = " ".join(_pitch_token(n) for n in onsets)
        blocks.append(f"\npart_index={idx} (liczba nut: {len(onsets)}):\n{seq}")
    return "\n".join(blocks)


def _apply_plan(parts_onsets: List[list], plan: UnderlayPlan) -> int:
    """Insert the planned syllables as music21 lyrics. Returns the number of notes texted."""
    from music21 import note as m21note

    placed = 0
    for part_plan in plan.parts:
        idx = part_plan.part_index
        if idx < 0 or idx >= len(parts_onsets):
            logger.warning("underlay: part_index=%s poza zakresem — pominięto", idx)
            continue
        onsets = parts_onsets[idx]
        for n, syl in zip(onsets, part_plan.syllables):
            text = (syl.text or "").strip()
            if not text:
                continue  # melisma continuation / untexted note
            lyric = m21note.Lyric(text=text, number=1)
            syllabic = (syl.syllabic or "single").strip().lower()
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


def underlay_lyrics(
    lyrics: str,
    musicxml: str,
    client: Optional[LLMClient] = None,
) -> UnderlayResult:
    """Underlay ``lyrics`` into ``musicxml`` programmatically and validate the result.

    The LLM only produces a syllable-per-onset alignment; this function inserts the
    ``<lyric>`` elements with music21 and re-exports the document, so the output size is
    bounded by the score, not by the model's token budget.

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
        return UnderlayResult(
            musicxml=musicxml,
            report=f"⚠️ Nie udało się wczytać partytury do podłożenia tekstu ({exc}) — "
            "zachowano plik z korekty.",
            changed=False,
            validation_error=str(exc),
        )

    parts_onsets = [_part_onsets(p) for p in score.parts]
    if not any(parts_onsets):
        return UnderlayResult(
            musicxml=musicxml,
            report="⚠️ Partytura nie zawiera nut do podłożenia tekstu — zachowano plik z korekty.",
            changed=False,
            validation_error="Brak nut w dokumencie.",
        )

    plan = client.parse(_SYSTEM, _build_user(lyrics, parts_onsets), UnderlayPlan, step="lyrics")
    placed = _apply_plan(parts_onsets, plan)
    report = (plan.notes or "").strip() or "Podłożono tekst pod nuty."

    if placed == 0:
        return UnderlayResult(
            musicxml=musicxml,
            report=report + "\n\n⚠️ Nie podłożono żadnej sylaby — zachowano plik z korekty.",
            changed=False,
            validation_error="Plan podkładu nie umieścił żadnej sylaby.",
        )

    try:
        out_xml = _export(score)
    except Exception as exc:
        logger.exception("underlay_lyrics: eksport music21 nie powiódł się")
        return UnderlayResult(
            musicxml=musicxml,
            report=report + f"\n\n⚠️ Eksport MusicXML nie powiódł się ({exc}) — "
            "zachowano plik z korekty.",
            changed=False,
            validation_error=str(exc),
        )

    ok, error, _validated = validate_musicxml(out_xml)
    if not ok:
        logger.warning("underlay_lyrics: walidacja music21 odrzuciła wynik: %s", error)
        return UnderlayResult(
            musicxml=musicxml,
            report=report + f"\n\n⚠️ Finalny plik nie przeszedł walidacji ({error}) — "
            "zachowano plik z korekty.",
            changed=False,
            validation_error=error,
        )

    report += f"\n\nPodłożono {placed} sylab w {len(plan.parts)} partii (programowo, music21)."
    return UnderlayResult(musicxml=out_xml, report=report, changed=True, score=score)
