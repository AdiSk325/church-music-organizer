"""Unit tests for the metadata-extraction agent and its pipeline wiring (LLM mocked)."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, MusicPiece
from src.llm.metadata_extractor import ExtractedMetadata, extract_metadata
from src.services.pipeline_service import PipelineService


def test_empty_input_skips_llm():
    client = MagicMock()
    result = extract_metadata("   ", client=client)
    assert isinstance(result, ExtractedMetadata)
    client.parse.assert_not_called()


def test_extract_via_client_uses_raw_text():
    client = MagicMock()
    client.parse.return_value = ExtractedMetadata(
        title="Ave Maria", composer="Arcadelt", lyrics_author="trad.", language="la"
    )
    result = extract_metadata("Ave Maria\nJacob Arcadelt\n...", client=client)
    assert result.title == "Ave Maria"
    assert result.composer == "Arcadelt"
    # raw OCR text reaches the prompt (not pre-filtered)
    _system, user = client.parse.call_args.args[:2]
    assert "Arcadelt" in user


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_run_step_metadata_fills_only_empty_fields(db_session, monkeypatch):
    # User already set the composer by hand; AI must not overwrite it.
    piece = MusicPiece(title="Ave Maria", composer="Mój wpis")
    db_session.add(piece)
    db_session.flush()

    monkeypatch.setattr(
        "src.llm.metadata_extractor.extract_metadata",
        lambda *a, **k: ExtractedMetadata(
            title="Ave Maria (AI)", composer="Arcadelt (AI)",
            lyrics_author="Anon", language="la",
        ),
    )

    result = PipelineService().run_step_metadata(db_session, piece.id, "Ave Maria Arcadelt")
    db_session.flush()

    assert result["status"] == "ok"
    # composer kept (already set), title kept (already set), empty fields filled
    assert piece.composer == "Mój wpis"
    assert piece.title == "Ave Maria"
    assert piece.lyrics_author == "Anon"
    assert piece.language == "la"
    assert "lyrics_author" in result["applied"]
    assert "composer" not in result["applied"]
