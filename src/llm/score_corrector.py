"""Step 4 — correct an OMR-produced MusicXML score with an LLM.

Audiveris transcription is imperfect: wrong accidentals, implausible rhythms, voicing that
violates basic harmonic/melodic logic. A specialised agent reviews the MusicXML, understands
the notation semantics, and returns a corrected document **plus** a human-readable report of
what it changed. The corrected document is validated through music21 before it is accepted;
if it does not parse, the original is kept and the failure is recorded in the report.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from src.llm.client import LLMClient, extract_musicxml, make_client
from src.llm.musicxml_validate import validate_musicxml

logger = logging.getLogger(__name__)


@dataclass
class ScoreCorrectionResult:
    musicxml: str  # corrected document, or the original when correction was rejected
    report: str  # human-readable summary of changes / issues
    changed: bool  # True when a valid corrected document replaced the original
    validation_error: Optional[str] = None  # set when the LLM output failed validation
    score: Optional[Any] = None  # parsed music21 Score, available when changed=True


_SYSTEM = """\
Jesteś ekspertem teorii muzyki i notacji (MusicXML) specjalizującym się w korekcie partytur
po automatycznym rozpoznawaniu nut (OMR/Audiveris). Otrzymujesz dokument MusicXML, który może
zawierać błędy transkrypcji. Twoje zadanie:

1. Przeanalizuj zapis pod kątem semantyki muzycznej: tonacja, metrum, sumy wartości rytmicznych
   w taktach, znaki chromatyczne, prowadzenie głosów, oczywiste niespójności harmoniczne/melodyczne.
2. Popraw WYŁĄCZNIE wyraźne błędy transkrypcji, których jesteś rozsądnie pewny. Nie przekomponowuj
   utworu, nie zmieniaj zamysłu kompozytora, nie "ulepszaj" harmonii tam, gdzie zapis jest poprawny.
2a. Zachowaj strukturę MusicXML poprawną składniowo (musi parsować się w music21).
3. Zwróć odpowiedź w DOKŁADNIE takim formacie:

## Raport korekt
- (lista zwięzłych punktów: co i dlaczego poprawiono; jeśli nic — napisz że brak istotnych błędów)

```xml
<PEŁNY poprawiony dokument MusicXML>
```

Blok ```xml musi zawierać kompletny, samodzielny dokument MusicXML (z deklaracją <?xml ...?>).\
"""


def _build_user(musicxml: str, analysis_context: Optional[str]) -> str:
    parts = []
    if analysis_context:
        parts.append(f"Kontekst analizy (dla orientacji):\n{analysis_context}\n")
    parts.append("Dokument MusicXML do korekty:\n\n```xml\n" + musicxml + "\n```")
    return "\n".join(parts)


def _extract_report(text: str) -> str:
    """Return the prose before the XML fence (the change report)."""
    if not text:
        return ""
    import re

    idx = re.search(r"```", text)
    head = text[: idx.start()] if idx else text
    return head.strip() or "Agent nie dołączył raportu."


def correct_score(
    musicxml: str,
    analysis_context: Optional[str] = None,
    client: Optional[LLMClient] = None,
) -> ScoreCorrectionResult:
    """Correct a MusicXML score, keeping the original if the result is invalid.

    Args:
        musicxml: The OMR-produced MusicXML document.
        analysis_context: Optional short summary (key, metre, voices, epoch) to ground the
            harmonic reasoning — typically derived from ``ScoreDescriptor``.
        client: Optional injected client (tests pass a mock).

    Returns:
        A :class:`ScoreCorrectionResult`. ``changed`` is False when the LLM produced no
        usable XML or it failed music21 validation (the original document is returned).
    """
    client = client or make_client()
    reply = client.complete_text(_SYSTEM, _build_user(musicxml, analysis_context), step="score")

    report = _extract_report(reply)
    candidate = extract_musicxml(reply)

    if not candidate:
        logger.warning("correct_score: brak bloku MusicXML w odpowiedzi agenta")
        return ScoreCorrectionResult(
            musicxml=musicxml,
            report=report + "\n\n⚠️ Agent nie zwrócił poprawionego pliku — zachowano oryginał.",
            changed=False,
            validation_error="Brak dokumentu MusicXML w odpowiedzi.",
        )

    ok, error, score = validate_musicxml(candidate)
    if not ok:
        logger.warning("correct_score: walidacja music21 odrzuciła wynik: %s", error)
        return ScoreCorrectionResult(
            musicxml=musicxml,
            report=report + f"\n\n⚠️ Poprawiony plik nie przeszedł walidacji ({error}) — "
            "zachowano oryginał.",
            changed=False,
            validation_error=error,
        )

    return ScoreCorrectionResult(musicxml=candidate, report=report, changed=True, score=score)
