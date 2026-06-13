"""Step 5 — place the cleaned lyrics under the notes and validate the whole file.

The final agent takes the clean lyrics from step 2 and the corrected MusicXML from step 4
and produces a single MusicXML document with the text correctly underlaid as ``<lyric>``
elements (syllable-aligned, verse-aware), then validates the result. As with step 4, the
output is gated through music21 — on failure the step-4 document is kept unchanged.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.llm.client import LLMClient, extract_musicxml
from src.llm.musicxml_validate import validate_musicxml

logger = logging.getLogger(__name__)


@dataclass
class UnderlayResult:
    musicxml: str  # final document, or the step-4 document when underlay was rejected
    report: str  # validation / placement summary
    changed: bool  # True when a valid underlaid document was produced
    validation_error: Optional[str] = None


_SYSTEM = """\
Jesteś ekspertem notacji muzycznej (MusicXML) i edycji wokalnej. Otrzymujesz:
(A) oczyszczony tekst pieśni oraz (B) poprawiony dokument MusicXML (nuty bez/with niepełnym tekstem).
Twoje zadanie:

1. Podłóż tekst (A) pod nuty dokumentu (B) jako elementy <lyric> przy odpowiednich nutach:
   - dziel wyrazy na sylaby i wyrównuj sylaby do nut (syllabic/melizmatyczny zapis wg sensu),
   - używaj <syllabic>begin/middle/end/single</syllabic> i łączników tam, gdzie to właściwe,
   - obsłuż kolejne strofy jako kolejne numery zwrotek (<lyric number="2"> ...), jeśli występują,
   - nie zmieniaj nut — modyfikujesz wyłącznie warstwę tekstową, chyba że to konieczne dla poprawności.
2. Zweryfikuj poprawność całego pliku (składnia MusicXML, spójność tekstu z liczbą nut).
3. Zwróć odpowiedź DOKŁADNIE w formacie:

## Raport
- (zwięzłe punkty: jak podłożono tekst, wykryte problemy/wątpliwości; jeśli brak — napisz to)

```xml
<PEŁNY finalny dokument MusicXML z podłożonym tekstem>
```

Blok ```xml musi zawierać kompletny, samodzielny dokument MusicXML (z deklaracją <?xml ...?>).\
"""


def _build_user(lyrics: str, musicxml: str) -> str:
    return (
        "Oczyszczony tekst pieśni (A):\n\n"
        f"{lyrics}\n\n"
        "Dokument MusicXML do uzupełnienia o tekst (B):\n\n```xml\n" + musicxml + "\n```"
    )


def _extract_report(text: str) -> str:
    if not text:
        return ""
    import re

    idx = re.search(r"```", text)
    head = text[: idx.start()] if idx else text
    return head.strip() or "Agent nie dołączył raportu."


def underlay_lyrics(
    lyrics: str,
    musicxml: str,
    client: Optional[LLMClient] = None,
) -> UnderlayResult:
    """Underlay ``lyrics`` into ``musicxml`` and validate the result.

    Args:
        lyrics: Cleaned lyrics from step 2.
        musicxml: Corrected MusicXML from step 4.
        client: Optional injected client (tests pass a mock).

    Returns:
        An :class:`UnderlayResult`; ``changed`` is False when the agent returned no usable
        XML or it failed validation (the step-4 document is returned unchanged).
    """
    client = client or LLMClient()
    reply = client.complete_text(_SYSTEM, _build_user(lyrics, musicxml), step="lyrics")

    report = _extract_report(reply)
    candidate = extract_musicxml(reply)

    if not candidate:
        logger.warning("underlay_lyrics: brak bloku MusicXML w odpowiedzi agenta")
        return UnderlayResult(
            musicxml=musicxml,
            report=report + "\n\n⚠️ Agent nie zwrócił finalnego pliku — zachowano plik z korekty.",
            changed=False,
            validation_error="Brak dokumentu MusicXML w odpowiedzi.",
        )

    ok, error = validate_musicxml(candidate)
    if not ok:
        logger.warning("underlay_lyrics: walidacja music21 odrzuciła wynik: %s", error)
        return UnderlayResult(
            musicxml=musicxml,
            report=report + f"\n\n⚠️ Finalny plik nie przeszedł walidacji ({error}) — "
            "zachowano plik z korekty.",
            changed=False,
            validation_error=error,
        )

    return UnderlayResult(musicxml=candidate, report=report, changed=True)
