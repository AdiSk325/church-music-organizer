"""Tests for OCRService — mocks SheetMusicOCR and Path.exists."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicPiece
from src.services.ocr_service import OCRService


@pytest.fixture
def db_session():
    """In-memory SQLite session for OCRService tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def piece(db_session):
    """Persisted MusicPiece for use in file fixtures."""
    p = MusicPiece(title="Test Piece")
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def scan_file(db_session, piece, tmp_path):
    """MusicFile of type SCAN backed by a real temp file."""
    real_file = tmp_path / "scan.jpg"
    real_file.write_bytes(b"fake image data")

    mf = MusicFile(
        music_piece_id=piece.id,
        file_path=str(real_file),
        file_type=FileType.SCAN,
        original_filename="scan.jpg",
        is_processed=0,
    )
    db_session.add(mf)
    db_session.flush()
    return mf


@pytest.fixture
def pdf_file(db_session, piece, tmp_path):
    """MusicFile of type PDF backed by a real temp file."""
    real_file = tmp_path / "score.pdf"
    real_file.write_bytes(b"%PDF-1.4 fake")

    mf = MusicFile(
        music_piece_id=piece.id,
        file_path=str(real_file),
        file_type=FileType.PDF,
        original_filename="score.pdf",
        is_processed=0,
    )
    db_session.add(mf)
    db_session.flush()
    return mf


# ---------------------------------------------------------------------------
# Tests: file not found in DB
# ---------------------------------------------------------------------------


class TestOCRServiceFileNotFound:
    def test_returns_none_when_music_file_missing(self, db_session):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()

        result = service.process_file(db_session, file_id=99999)

        assert result is None
        service._ocr.process_file.assert_not_called()

    def test_logs_warning_when_music_file_missing(self, db_session, caplog):
        import logging

        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()

        with caplog.at_level(logging.WARNING, logger="src.services.ocr_service"):
            service.process_file(db_session, file_id=99999)

        assert any("not found" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tests: file missing on disk
# ---------------------------------------------------------------------------


class TestOCRServiceFileMissingOnDisk:
    def test_returns_none_when_path_missing(self, db_session, piece):
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path="/nonexistent/path/scan.jpg",
            file_type=FileType.SCAN,
            is_processed=0,
        )
        db_session.add(mf)
        db_session.flush()

        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()

        result = service.process_file(db_session, mf.id)

        assert result is None
        service._ocr.process_file.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: successful dict result (image file)
# ---------------------------------------------------------------------------


class TestOCRServiceDictResult:
    def test_saves_text_and_confidence(self, db_session, scan_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = {
            "text": "Kyrie eleison",
            "confidence": 85.7,
            "has_music_notation": False,
        }

        result = service.process_file(db_session, scan_file.id)
        db_session.commit()

        assert result is not None
        assert result["text"] == "Kyrie eleison"
        assert result["confidence"] == 85
        assert result["has_music_notation"] is False
        assert result["file_id"] == scan_file.id

        db_session.refresh(scan_file)
        assert scan_file.extracted_text == "Kyrie eleison"
        assert scan_file.ocr_confidence == 85
        assert scan_file.is_processed == 1

    def test_sets_is_processed_flag(self, db_session, scan_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = {
            "text": "Gloria",
            "confidence": 70.0,
            "has_music_notation": True,
        }

        service.process_file(db_session, scan_file.id)
        db_session.commit()
        db_session.refresh(scan_file)

        assert scan_file.is_processed == 1

    def test_returns_has_music_notation_true(self, db_session, scan_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = {
            "text": "staff lines detected",
            "confidence": 60.0,
            "has_music_notation": True,
        }

        result = service.process_file(db_session, scan_file.id)

        assert result["has_music_notation"] is True

    def test_confidence_cast_to_int(self, db_session, scan_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = {
            "text": "text",
            "confidence": 92.9,
            "has_music_notation": False,
        }

        result = service.process_file(db_session, scan_file.id)

        assert isinstance(result["confidence"], int)
        assert result["confidence"] == 92


# ---------------------------------------------------------------------------
# Tests: successful list result (multi-page PDF)
# ---------------------------------------------------------------------------


class TestOCRServiceListResult:
    def test_combines_pages_text(self, db_session, pdf_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = [
            {"text": "Page one text", "confidence": 80.0, "has_music_notation": False, "page": 1},
            {"text": "Page two text", "confidence": 60.0, "has_music_notation": True, "page": 2},
        ]

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        assert result is not None
        assert "Page one text" in result["text"]
        assert "Page two text" in result["text"]

    def test_averages_confidence_across_pages(self, db_session, pdf_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = [
            {"text": "p1", "confidence": 80.0, "has_music_notation": False},
            {"text": "p2", "confidence": 60.0, "has_music_notation": False},
        ]

        result = service.process_file(db_session, pdf_file.id)

        assert result["confidence"] == 70  # (80 + 60) / 2

    def test_has_notation_true_if_any_page_has_notation(self, db_session, pdf_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = [
            {"text": "p1", "confidence": 50.0, "has_music_notation": False},
            {"text": "p2", "confidence": 50.0, "has_music_notation": True},
        ]

        result = service.process_file(db_session, pdf_file.id)

        assert result["has_music_notation"] is True

    def test_has_notation_false_when_no_page_has_notation(self, db_session, pdf_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = [
            {"text": "p1", "confidence": 50.0, "has_music_notation": False},
            {"text": "p2", "confidence": 50.0, "has_music_notation": False},
        ]

        result = service.process_file(db_session, pdf_file.id)

        assert result["has_music_notation"] is False

    def test_single_page_pdf_returns_correct_confidence(self, db_session, pdf_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = [
            {"text": "only page", "confidence": 73.0, "has_music_notation": False},
        ]

        result = service.process_file(db_session, pdf_file.id)

        assert result["confidence"] == 73

    def test_persists_combined_text_to_db(self, db_session, pdf_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.return_value = [
            {"text": "first", "confidence": 90.0, "has_music_notation": False},
            {"text": "second", "confidence": 90.0, "has_music_notation": False},
        ]

        service.process_file(db_session, pdf_file.id)
        db_session.commit()
        db_session.refresh(pdf_file)

        assert "first" in pdf_file.extracted_text
        assert "second" in pdf_file.extracted_text
        assert pdf_file.is_processed == 1


# ---------------------------------------------------------------------------
# Tests: OCR engine raises exception
# ---------------------------------------------------------------------------


class TestOCRServiceException:
    def test_returns_none_on_ocr_exception(self, db_session, scan_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.side_effect = RuntimeError("Tesseract not found")

        result = service.process_file(db_session, scan_file.id)

        assert result is None

    def test_does_not_set_processed_on_exception(self, db_session, scan_file):
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.side_effect = OSError("disk error")

        service.process_file(db_session, scan_file.id)
        db_session.commit()
        db_session.refresh(scan_file)

        assert scan_file.is_processed == 0

    def test_logs_exception_on_ocr_failure(self, db_session, scan_file, caplog):
        import logging

        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.side_effect = ValueError("bad image")

        with caplog.at_level(logging.ERROR, logger="src.services.ocr_service"):
            service.process_file(db_session, scan_file.id)

        assert any("OCR failed" in r.message for r in caplog.records)

    def test_does_not_raise_on_ocr_exception(self, db_session, scan_file):
        """OCRService must swallow engine exceptions and return None gracefully."""
        service = OCRService.__new__(OCRService)
        service._ocr = MagicMock()
        service._ocr.process_file.side_effect = Exception("unexpected crash")

        # Must not propagate the exception
        result = service.process_file(db_session, scan_file.id)
        assert result is None
