"""Unit tests for PipelineService — orchestration with all LLM/engine boundaries mocked.

No network, ``anthropic`` or credentials required: OCR/OMR services and the three LLM
agent functions are patched, and ``FileService.save_uploaded_file`` is redirected to a
temp directory.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicPiece, ProcessingStep
from src.services.pipeline_service import PipelineService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def piece(db_session):
    p = MusicPiece(title="Test Piece")
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def pdf_file(db_session, piece, tmp_path):
    real = tmp_path / "score.pdf"
    real.write_bytes(b"%PDF-1.4 fake")
    mf = MusicFile(
        music_piece_id=piece.id,
        file_path=str(real),
        file_type=FileType.PDF,
        original_filename="score.pdf",
    )
    db_session.add(mf)
    db_session.flush()
    return mf


@pytest.fixture
def stub_save(monkeypatch, tmp_path):
    """Redirect FileService.save_uploaded_file to a temp dir (real bytes on disk).

    Accepts **kwargs so the stub stays compatible when callers pass
    ``use_library=True``, ``piece=...``, ``kind=...`` keywords introduced by the
    library-routing feature.
    """

    def _save(piece_id, filename, file_data, upload_dir="data/uploads", **kwargs):
        dest = tmp_path / f"saved_{piece_id}_{filename}"
        dest.write_bytes(file_data)
        return str(dest)

    monkeypatch.setattr("src.services.file_service.FileService.save_uploaded_file", _save)


# ---------------------------------------------------------------------------
# Step 2 — clean text
# ---------------------------------------------------------------------------


class TestStep2CleanText:
    def test_empty_text_skipped(self, db_session, piece):
        result = PipelineService().run_step2_clean_text(db_session, piece.id, "   ")
        assert result["status"] == "skipped"

    def test_writes_lyrics_and_language(self, db_session, piece, monkeypatch):
        monkeypatch.setattr(
            "src.llm.lyrics_cleaner.clean_lyrics",
            lambda raw: SimpleNamespace(language="pl", cleaned_lyrics="Kyrie eleison", notes="ok"),
        )
        result = PipelineService().run_step2_clean_text(db_session, piece.id, "kyr1e e1eison")
        db_session.commit()

        assert result["status"] == "ok"
        refreshed = db_session.get(MusicPiece, piece.id)
        assert refreshed.lyrics == "Kyrie eleison"
        assert refreshed.language == "pl"

    def test_does_not_overwrite_existing_language(self, db_session, piece, monkeypatch):
        piece.language = "łacina"
        db_session.flush()
        monkeypatch.setattr(
            "src.llm.lyrics_cleaner.clean_lyrics",
            lambda raw: SimpleNamespace(language="pl", cleaned_lyrics="X", notes=""),
        )
        PipelineService().run_step2_clean_text(db_session, piece.id, "x")
        assert db_session.get(MusicPiece, piece.id).language == "łacina"


# ---------------------------------------------------------------------------
# Step 4 — correct score
# ---------------------------------------------------------------------------


class TestStep4CorrectScore:
    def test_persists_new_file_when_changed(
        self, db_session, piece, tmp_path, monkeypatch, stub_save
    ):
        xml = tmp_path / "omr.xml"
        xml.write_text("<score-partwise/>", encoding="utf-8")
        monkeypatch.setattr(
            "src.services.pipeline_service.load_musicxml_text", lambda p: "<score/>"
        )
        monkeypatch.setattr(
            "src.llm.score_corrector.correct_score",
            lambda content, analysis_context=None: SimpleNamespace(
                musicxml="<corrected/>", report="zmiany", changed=True, validation_error=None
            ),
        )

        before = db_session.query(MusicFile).count()
        result = PipelineService().run_step4_correct_score(db_session, piece.id, str(xml))
        db_session.commit()

        assert result["status"] == "ok" and result["changed"] is True
        assert db_session.query(MusicFile).count() == before + 1
        new = db_session.get(MusicFile, result["output_file_id"])
        assert new.file_type == FileType.XML

    def test_no_new_file_when_unchanged(self, db_session, piece, tmp_path, monkeypatch):
        xml = tmp_path / "omr.xml"
        xml.write_text("<score-partwise/>", encoding="utf-8")
        monkeypatch.setattr(
            "src.services.pipeline_service.load_musicxml_text", lambda p: "<score/>"
        )
        monkeypatch.setattr(
            "src.llm.score_corrector.correct_score",
            lambda content, analysis_context=None: SimpleNamespace(
                musicxml="<score/>", report="brak zmian", changed=False, validation_error="x"
            ),
        )

        before = db_session.query(MusicFile).count()
        result = PipelineService().run_step4_correct_score(db_session, piece.id, str(xml))

        assert result["status"] == "ok" and result["changed"] is False
        assert db_session.query(MusicFile).count() == before


# ---------------------------------------------------------------------------
# Step 5 — underlay lyrics
# ---------------------------------------------------------------------------


class TestStep5Underlay:
    def test_empty_lyrics_skipped(self, db_session, piece):
        result = PipelineService().run_step5_underlay(
            db_session, piece.id, "", xml_content="<score/>"
        )
        assert result["status"] == "skipped"

    def test_persists_final_file_when_changed(self, db_session, piece, monkeypatch, stub_save):
        monkeypatch.setattr(
            "src.llm.lyric_underlayer.underlay_lyrics",
            lambda lyrics, content: SimpleNamespace(
                musicxml="<final/>", report="ok", changed=True, validation_error=None
            ),
        )
        before = db_session.query(MusicFile).count()
        result = PipelineService().run_step5_underlay(
            db_session, piece.id, "Tekst", xml_content="<corrected/>"
        )
        db_session.commit()

        assert result["status"] == "ok" and result["changed"] is True
        assert db_session.query(MusicFile).count() == before + 1


# ---------------------------------------------------------------------------
# run_full — cascade
# ---------------------------------------------------------------------------


def _patch_engines(monkeypatch, *, ocr_text="raw text", omr_xml="/tmp/x.mxl"):
    ocr = MagicMock()
    ocr.return_value.process_file.return_value = (
        {"text": ocr_text, "confidence": 80, "has_music_notation": True}
        if ocr_text is not None
        else None
    )
    omr = MagicMock()
    omr.return_value.process_file.return_value = (
        {"success": True, "musicxml_path": omr_xml}
        if omr_xml is not None
        else {"success": False, "error": "brak mxl"}
    )
    monkeypatch.setattr("src.services.pipeline_service.OCRService", ocr)
    monkeypatch.setattr("src.services.pipeline_service.OMRService", omr)
    # Stub the metadata-extraction agent so the cascade never reaches a real LLM/CLI.
    from src.llm.metadata_extractor import ExtractedMetadata

    monkeypatch.setattr(
        "src.llm.metadata_extractor.extract_metadata",
        lambda *a, **k: ExtractedMetadata(),
    )


class TestRunFull:
    def test_happy_path_all_steps_ok(self, db_session, pdf_file, monkeypatch, stub_save):
        _patch_engines(monkeypatch)
        monkeypatch.setattr("src.services.pipeline_service.llm_available", lambda: True)
        monkeypatch.setattr(
            "src.llm.lyrics_cleaner.clean_lyrics",
            lambda raw: SimpleNamespace(language="pl", cleaned_lyrics="Tekst", notes="ok"),
        )
        monkeypatch.setattr(
            "src.services.pipeline_service.load_musicxml_text", lambda p: "<score/>"
        )
        monkeypatch.setattr(
            "src.llm.score_corrector.correct_score",
            lambda content, analysis_context=None: SimpleNamespace(
                musicxml="<corrected/>", report="r4", changed=True, validation_error=None
            ),
        )
        monkeypatch.setattr(
            "src.services.pipeline_service.PipelineService._analysis_context",
            lambda self, p: None,
        )
        monkeypatch.setattr(
            "src.llm.lyric_underlayer.underlay_lyrics",
            lambda lyrics, content: SimpleNamespace(
                musicxml="<final/>", report="r5", changed=True, validation_error=None
            ),
        )

        out = PipelineService().run_full(db_session, pdf_file.id)
        db_session.commit()

        statuses = {s["name"][0]: s["status"] for s in out["steps"]}
        assert all(v == "ok" for v in statuses.values()), out["steps"]
        assert db_session.get(MusicPiece, pdf_file.music_piece_id).lyrics == "Tekst"
        # Two new XML files (corrected + final).
        assert db_session.query(MusicFile).filter_by(file_type=FileType.XML).count() == 2

        # Every step is persisted as a ProcessingStep row for the UI to read back.
        keys = {r.step_key for r in db_session.query(ProcessingStep).all()}
        assert {"ocr", "clean_text", "omr", "correct_score", "underlay"} <= keys

    def test_no_omr_output_skips_steps_4_and_5(self, db_session, pdf_file, monkeypatch):
        _patch_engines(monkeypatch, omr_xml=None)
        monkeypatch.setattr("src.services.pipeline_service.llm_available", lambda: True)
        monkeypatch.setattr(
            "src.llm.lyrics_cleaner.clean_lyrics",
            lambda raw: SimpleNamespace(language="pl", cleaned_lyrics="T", notes=""),
        )

        out = PipelineService().run_full(db_session, pdf_file.id)
        by_num = {s["name"][0]: s for s in out["steps"]}
        assert by_num["3"]["status"] == "error"
        assert by_num["4"]["status"] == "skipped"
        assert by_num["5"]["status"] == "skipped"

    def test_llm_unavailable_skips_llm_steps(self, db_session, pdf_file, monkeypatch):
        _patch_engines(monkeypatch)
        monkeypatch.setattr("src.services.pipeline_service.llm_available", lambda: False)

        out = PipelineService().run_full(db_session, pdf_file.id)
        by_num = {s["name"][0]: s for s in out["steps"]}
        assert by_num["1"]["status"] == "ok"  # OCR still runs
        assert by_num["2"]["status"] == "skipped"  # no LLM
        assert by_num["4"]["status"] == "skipped"
        assert by_num["5"]["status"] == "skipped"

    def test_missing_source_file_returns_error(self, db_session):
        out = PipelineService().run_full(db_session, 999999)
        assert out["steps"] == []
        assert "error" in out
