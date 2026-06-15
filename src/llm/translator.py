"""Translate song lyrics into Polish with the Gemini LLM.

Used by the Song Detail UI to show, under the original text, a Polish translation of the
lyrics. The translation preserves the verse/refrain structure and does not invent content.
When the source is already Polish the agent returns the text essentially unchanged and says
so in ``notes``.
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


from src.llm.client import LLMClient, make_client

logger = logging.getLogger(__name__)


class TranslatedLyrics(BaseModel):
    """Structured result of the lyric-translation agent."""

    source_language: str  # ISO 639-1 code of the detected source language
    translation_pl: str  # the Polish translation, verses separated by blank lines
    notes: str  # short note (e.g. "tekst był już po polsku", uncertain passages)


_SYSTEM = """\
Jesteś tłumaczem specjalizującym się w tekstach muzyki kościelnej i chóralnej (polski,
łacina, angielski, niemiecki). Otrzymujesz tekst pieśni. Twoje zadanie:

1. Rozpoznaj język źródłowy (kod ISO 639-1, np. "la", "en", "pl", "de").
2. Przetłumacz tekst NA JĘZYK POLSKI:
   - zachowaj podział na strofy/refren (oddzielaj pustą linią), wers po wersie tam, gdzie to
     możliwe, aby tłumaczenie dało się zestawić z oryginałem,
   - oddaj sens i rejestr (modlitewny/liturgiczny), nie tłumacz dosłownie kosztem znaczenia,
   - NIE dodawaj treści, której nie ma; nie komentuj poza polem "notes".
3. Jeśli tekst jest JUŻ po polsku — zwróć go bez zmian i napisz to w "notes".
4. W "notes" napisz krótko (1–2 zdania) o trudnych miejscach lub założeniach.\
"""


def translate_to_polish(
    lyrics: str,
    source_language: Optional[str] = None,
    client: Optional[LLMClient] = None,
) -> TranslatedLyrics:
    """Translate ``lyrics`` into Polish.

    Args:
        lyrics: The (already cleaned) lyrics to translate.
        source_language: Optional ISO 639-1 hint (e.g. from step 2) to ground detection.
        client: Optional injected client (tests pass a mock); created on demand otherwise.

    Returns:
        A :class:`TranslatedLyrics` with the detected source language, the Polish
        translation and a short note.
    """
    text = (lyrics or "").strip()
    if not text:
        return TranslatedLyrics(
            source_language="und",
            translation_pl="",
            notes="Brak tekstu do przetłumaczenia.",
        )

    client = client or make_client()
    hint = f"(sugerowany język źródłowy: {source_language})\n\n" if source_language else ""
    user = f"{hint}Tekst pieśni do przetłumaczenia na polski:\n\n{text}"
    result = client.parse(_SYSTEM, user, TranslatedLyrics, step="text")
    logger.info(
        "translate_to_polish: źródło=%s, długość tłumaczenia=%d",
        result.source_language,
        len(result.translation_pl or ""),
    )
    return result
