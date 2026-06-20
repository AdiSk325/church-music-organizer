"""Unit tests for the Polish lyric-translation agent (LLM mocked)."""

from unittest.mock import MagicMock

from src.llm.translator import TranslatedLyrics, translate_to_polish


def test_empty_lyrics_returns_und_without_calling_llm():
    client = MagicMock()
    result = translate_to_polish("   ", client=client)
    assert isinstance(result, TranslatedLyrics)
    assert result.source_language == "und"
    assert result.translation_pl == ""
    client.parse.assert_not_called()


def test_translates_via_client():
    client = MagicMock()
    client.parse.return_value = TranslatedLyrics(
        source_language="la",
        translation_pl="Śpiewajcie Panu",
        notes="z łaciny",
    )
    result = translate_to_polish("Cantate Domino", source_language="la", client=client)
    assert result.translation_pl == "Śpiewajcie Panu"
    assert result.source_language == "la"
    # source-language hint is forwarded into the prompt
    _system, user = client.parse.call_args.args[:2]
    assert "la" in user
