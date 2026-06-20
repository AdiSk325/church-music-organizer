"""Extra step — pull header metadata (title, authors, …) out of the OCR text with an LLM.

The OCR dump usually carries the score's *credits* at the very top: title, composer, lyric
author, arranger, sometimes an occasion or copyright line. The lyric-cleaning step (step 2)
deliberately throws this away to reconstruct the sung text, so the structured metadata was
never produced by the pipeline and the ``MusicPiece`` author fields stayed empty.

This agent reads the **raw** OCR text (and, optionally, the music21 ``score.metadata``
captured by Audiveris) and returns a structured :class:`ExtractedMetadata`. It is conservative
by design: it extracts only what is plausibly present in the header and never invents authors.
The caller fills *empty* ``MusicPiece`` fields only, so manual user input is never overwritten.
"""

import logging
from typing import Optional

try:  # pydantic ships with google-genai; degrade gracefully when neither is installed
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - exercised only without google-genai/pydantic

    class BaseModel:  # minimal stand-in so this module imports without pydantic
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def Field(default=None, **_kwargs):  # type: ignore
        return default


from src.llm.client import LLMClient, make_client

logger = logging.getLogger(__name__)

# Only the leading part of the OCR carries credits; cap the prompt so cost stays bounded even
# for multi-page dumps (header info is always at the top of the first page).
_MAX_CHARS = 4000


class ExtractedMetadata(BaseModel):
    """Structured header metadata of a piece. Empty string means "not found / unknown"."""

    title: str = Field(default="", description="Tytuł utworu.")
    composer: str = Field(default="", description="Kompozytor (ogólnie).")
    music_author: str = Field(default="", description="Autor muzyki, jeśli rozróżniony.")
    lyrics_author: str = Field(default="", description="Autor słów/tekstu.")
    arranger: str = Field(default="", description="Autor opracowania/aranżacji/harmonizacji.")
    genre: str = Field(default="", description="Gatunek/forma (np. pieśń, hymn, kolęda, motet).")
    language: str = Field(default="", description="Kod ISO 639-1 języka tekstu (pl/la/en/...).")
    occasion: str = Field(default="", description="Okazja (np. Boże Narodzenie, ślub, pogrzeb).")
    liturgical_season: str = Field(default="", description="Okres liturgiczny (Adwent, Wielki Post...).")
    source_copyright: str = Field(default="", description="Źródło/wydawca/copyright, jeśli podane.")
    notes: str = Field(default="", description="1 zdanie o ewentualnych wątpliwościach.")


_SYSTEM = """\
Jesteś ekspertem od polskiej i łacińskiej muzyki kościelnej oraz katalogowania nut. Otrzymujesz
surowy tekst OCR z pierwszej strony pliku nutowego (pieśni/utworu kościelnego). W nagłówku takich
nut zwykle znajdują się: tytuł, kompozytor / autor muzyki, autor słów, autor opracowania, czasem
okazja, okres liturgiczny lub informacja o źródle/wydawcy.

Twoje zadanie: wyciągnij metadane utworu do podanych pól. ZASADY:
- Wypełniaj TYLKO te pola, które faktycznie wynikają z tekstu. Jeśli czegoś nie ma — zostaw "".
- NIE zmyślaj nazwisk, tytułów ani okazji. Lepiej zostawić puste niż zgadywać.
- Rozróżniaj role: "sł." / "słowa" → autor słów; "muz." / "muzyka" → autor muzyki;
  "oprac." / "harm." / "arr." → aranżer. Jeśli jest tylko jedno nazwisko bez roli — wpisz je do
  "composer".
- "language": kod ISO 639-1 języka tekstu pieśni (np. "pl", "la", "en").
- W "notes" napisz krótko (1 zdanie) co było niejednoznaczne, albo "".

Nie dodawaj komentarza poza wymaganymi polami.\
"""


def extract_metadata(
    ocr_text: str,
    score_metadata: Optional[dict] = None,
    client: Optional[LLMClient] = None,
) -> ExtractedMetadata:
    """Extract header metadata from raw OCR text (+ optional music21 score metadata).

    Args:
        ocr_text: Raw, unfiltered OCR output (credits live at the top — do NOT pre-filter as in
            the lyric cleaner, which would strip short names/titles).
        score_metadata: Optional ``{"title": ..., "composer": ...}`` from music21/Audiveris.
        client: Optional injected client (tests pass a mock); created on demand otherwise.

    Returns:
        An :class:`ExtractedMetadata`; all-empty when nothing reliable could be read.
    """
    text = (ocr_text or "").strip()
    if not text and not score_metadata:
        logger.info("extract_metadata: brak tekstu OCR i metadanych partytury")
        return ExtractedMetadata(notes="Brak danych wejściowych.")

    client = client or make_client()
    head = text[:_MAX_CHARS]
    parts = []
    if score_metadata:
        hints = ", ".join(f"{k}={v}" for k, v in score_metadata.items() if v)
        if hints:
            parts.append(f"Metadane z pliku nutowego (music21/Audiveris): {hints}")
    parts.append(f"Surowy tekst OCR (początek strony):\n\n{head}")
    user = "\n\n".join(parts)

    result = client.parse(_SYSTEM, user, ExtractedMetadata, step="text")
    logger.info(
        "extract_metadata: tytuł=%r kompozytor=%r sł=%r muz=%r",
        result.title, result.composer, result.lyrics_author, result.music_author,
    )
    return result
