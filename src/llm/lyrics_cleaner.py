"""Step 2 — turn a raw OCR dump into the most probable song lyrics.

A specialised agent reconstructs the lyrics from noisy Tesseract output: it detects the
language (Polish church repertoire is frequently Latin or Polish), removes OCR artefacts
(stray glyphs, broken hyphenation, mis-split words, staff-line noise) and preserves the
verse/refrain structure — without inventing text that is not plausibly there.
"""

import logging
from typing import Optional

try:  # pydantic ships with google-genai; degrade gracefully when neither is installed
    from pydantic import BaseModel
except Exception:  # pragma: no cover - exercised only without google-genai/pydantic

    class BaseModel:  # minimal stand-in so this module imports without pydantic
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


from src.llm.client import LLMClient

logger = logging.getLogger(__name__)


class CleanedLyrics(BaseModel):
    """Structured result of the lyric-cleaning agent."""

    language: str  # ISO 639-1 code, e.g. "pl", "la", "en"; "und" if undetermined
    cleaned_lyrics: str  # the reconstructed text, verses separated by blank lines
    notes: str  # short note on what was corrected / any uncertainty


_SYSTEM = """\
Jesteś ekspertem od polskiej i łacińskiej muzyki kościelnej oraz korekty tekstu po OCR.
Otrzymujesz surowy, zaszumiony zrzut tekstu wyekstrahowanego przez Tesseract z pliku nutowego
(pieśni/utworu kościelnego). Twoje zadanie:

1. Rozpoznaj język tekstu pieśni (najczęściej polski lub łacina; czasem inny). Zwróć kod ISO 639-1
   (np. "pl", "la", "en", "de"). Jeśli nie da się ustalić — "und".
2. Odtwórz NAJBARDZIEJ PRAWDOPODOBNY tekst pieśni:
   - usuń artefakty OCR (przypadkowe znaki, pozostałości pięciolinii, cyfry taktów, błędne łamanie),
   - scal błędnie podzielone wyrazy i napraw dzielenie międzywersowe,
   - zachowaj podział na strofy/refren (oddzielaj puste linią),
   - uwzględnij znaczenie i typowe frazy repertuaru, ale NIE wymyślaj treści, której nie ma.
3. W "notes" napisz krótko (1–3 zdania) co poprawiono i gdzie masz wątpliwości.

Nie dodawaj komentarza poza wymaganymi polami.\
"""


def clean_lyrics(raw_text: str, client: Optional[LLMClient] = None) -> CleanedLyrics:
    """Reconstruct clean lyrics from raw OCR text.

    Args:
        raw_text: Raw OCR output (possibly multi-page, with separators).
        client: Optional injected client (tests pass a mock); created on demand otherwise.

    Returns:
        A :class:`CleanedLyrics` with detected language, cleaned text and notes.
    """
    client = client or LLMClient()
    user = f"Surowy tekst OCR do oczyszczenia:\n\n{raw_text}"
    result = client.parse(_SYSTEM, user, CleanedLyrics, step="text")
    logger.info(
        "clean_lyrics: język=%s, długość=%d",
        result.language,
        len(result.cleaned_lyrics or ""),
    )
    return result
