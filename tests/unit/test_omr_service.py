"""Unit tests for OMRService — mocks PdfToMusicXml.convert and audiveris_available."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicPiece
from src.services.omr_service import OMRService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    """In-memory SQLite session for OMRService tests."""
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
def pdf_file(db_session, piece, tmp_path):
    """MusicFile of type PDF backed by a real temp file on disk."""
    real_file = tmp_path / "score.pdf"
    real_file.write_bytes(b"%PDF-1.4 fake content")
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


@pytest.fixture
def scan_file(db_session, piece, tmp_path):
    """MusicFile of type SCAN backed by a real temp file on disk."""
    real_file = tmp_path / "scan.jpg"
    real_file.write_bytes(b"\xff\xd8\xff fake jpeg")
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


def _make_service(tmp_path=None):
    """Return an OMRService with _converter mocked — no real Audiveris needed."""
    service = OMRService.__new__(OMRService)
    service._converter = MagicMock(spec=["convert"])
    service._output_dir = str(tmp_path) if tmp_path is not None else "data/processed"
    return service


# ---------------------------------------------------------------------------
# Tests: is_available()
# ---------------------------------------------------------------------------


class TestOMRServiceIsAvailable:
    def test_delegates_to_audiveris_available(self):
        with patch("src.services.omr_service.audiveris_available", return_value=True) as mock_fn:
            result = OMRService.is_available()
        assert result is True
        mock_fn.assert_called_once()

    def test_returns_true_when_audiveris_found(self):
        with patch("src.services.omr_service.audiveris_available", return_value=True):
            assert OMRService.is_available() is True

    def test_returns_false_when_audiveris_not_found(self):
        with patch("src.services.omr_service.audiveris_available", return_value=False):
            assert OMRService.is_available() is False


# ---------------------------------------------------------------------------
# Tests: process_file() — MusicFile not found in DB
# ---------------------------------------------------------------------------


class TestOMRServiceFileNotFound:
    def test_returns_none_when_file_id_missing(self, db_session):
        service = _make_service()
        result = service.process_file(db_session, file_id=99999)
        assert result is None

    def test_does_not_call_converter_when_db_record_missing(self, db_session):
        service = _make_service()
        service.process_file(db_session, file_id=99999)
        service._converter.convert.assert_not_called()

    def test_logs_warning_when_db_record_missing(self, db_session, caplog):
        import logging

        service = _make_service()
        with caplog.at_level(logging.WARNING, logger="src.services.omr_service"):
            service.process_file(db_session, file_id=99999)

        assert any("not found" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tests: process_file() — unsupported file type
# ---------------------------------------------------------------------------


class TestOMRServiceUnsupportedFileType:
    @pytest.mark.parametrize(
        "ftype", [FileType.MUSESCORE, FileType.XML, FileType.TEXT, FileType.OTHER]
    )
    def test_returns_failure_for_unsupported_type(self, db_session, piece, tmp_path, ftype):
        real_file = tmp_path / "file.xyz"
        real_file.write_bytes(b"content")
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path=str(real_file),
            file_type=ftype,
            original_filename="file.xyz",
        )
        db_session.add(mf)
        db_session.flush()

        service = _make_service()
        result = service.process_file(db_session, mf.id)

        assert result is not None
        assert result["success"] is False
        assert result["file_id"] == mf.id
        assert "error" in result

    def test_does_not_call_converter_for_unsupported_type(self, db_session, piece, tmp_path):
        real_file = tmp_path / "score.mscz"
        real_file.write_bytes(b"musescore")
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path=str(real_file),
            file_type=FileType.MUSESCORE,
            original_filename="score.mscz",
        )
        db_session.add(mf)
        db_session.flush()

        service = _make_service()
        service.process_file(db_session, mf.id)

        service._converter.convert.assert_not_called()

    def test_error_message_contains_file_type_value(self, db_session, piece, tmp_path):
        real_file = tmp_path / "score.txt"
        real_file.write_bytes(b"text")
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path=str(real_file),
            file_type=FileType.TEXT,
            original_filename="score.txt",
        )
        db_session.add(mf)
        db_session.flush()

        service = _make_service()
        result = service.process_file(db_session, mf.id)

        assert "text" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tests: process_file() — file missing on disk
# ---------------------------------------------------------------------------


class TestOMRServiceFileMissingOnDisk:
    def test_returns_failure_when_path_not_on_disk(self, db_session, piece):
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path="/nonexistent/path/score.pdf",
            file_type=FileType.PDF,
            original_filename="score.pdf",
        )
        db_session.add(mf)
        db_session.flush()

        service = _make_service()
        result = service.process_file(db_session, mf.id)

        assert result is not None
        assert result["success"] is False
        assert result["file_id"] == mf.id

    def test_does_not_call_converter_when_file_missing_on_disk(self, db_session, piece):
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path="/nonexistent/path/score.pdf",
            file_type=FileType.PDF,
            original_filename="score.pdf",
        )
        db_session.add(mf)
        db_session.flush()

        service = _make_service()
        service.process_file(db_session, mf.id)

        service._converter.convert.assert_not_called()

    def test_error_message_mentions_missing_path(self, db_session, piece):
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path="/nonexistent/path/score.pdf",
            file_type=FileType.PDF,
            original_filename="score.pdf",
        )
        db_session.add(mf)
        db_session.flush()

        service = _make_service()
        result = service.process_file(db_session, mf.id)

        assert "not found" in result["error"].lower() or "nonexistent" in result["error"]


# ---------------------------------------------------------------------------
# Tests: process_file() — converter raises an exception
# ---------------------------------------------------------------------------


class TestOMRServiceConverterException:
    def test_returns_failure_when_converter_raises(self, db_session, pdf_file):
        service = _make_service()
        service._converter.convert.side_effect = RuntimeError("Audiveris crashed")

        result = service.process_file(db_session, pdf_file.id)

        assert result["success"] is False
        assert result["file_id"] == pdf_file.id
        assert "error" in result

    def test_does_not_propagate_converter_exception(self, db_session, pdf_file):
        """OMRService must swallow converter exceptions and return failure dict."""
        service = _make_service()
        service._converter.convert.side_effect = Exception("unexpected crash")

        result = service.process_file(db_session, pdf_file.id)

        assert result is not None  # exception was swallowed

    def test_logs_exception_on_converter_failure(self, db_session, pdf_file, caplog):
        import logging

        service = _make_service()
        service._converter.convert.side_effect = RuntimeError("Audiveris exploded")

        with caplog.at_level(logging.ERROR, logger="src.services.omr_service"):
            service.process_file(db_session, pdf_file.id)

        assert any(
            "exception" in r.message.lower() or "error" in r.message.lower() for r in caplog.records
        )

    def test_does_not_persist_file_on_exception(self, db_session, pdf_file):
        service = _make_service()
        service._converter.convert.side_effect = RuntimeError("crash")

        initial_count = db_session.query(MusicFile).count()
        service.process_file(db_session, pdf_file.id)

        assert db_session.query(MusicFile).count() == initial_count


# ---------------------------------------------------------------------------
# Tests: process_file() — converter returns None
# ---------------------------------------------------------------------------


class TestOMRServiceConverterReturnsNone:
    def test_returns_failure_when_convert_returns_none(self, db_session, pdf_file):
        service = _make_service()
        service._converter.convert.return_value = None

        result = service.process_file(db_session, pdf_file.id)

        assert result["success"] is False
        assert result["file_id"] == pdf_file.id
        assert "error" in result

    def test_does_not_persist_file_when_convert_returns_none(self, db_session, pdf_file):
        service = _make_service()
        service._converter.convert.return_value = None

        initial_count = db_session.query(MusicFile).count()
        service.process_file(db_session, pdf_file.id)

        assert db_session.query(MusicFile).count() == initial_count


# ---------------------------------------------------------------------------
# Tests: process_file() — successful conversion
# ---------------------------------------------------------------------------


class TestOMRServiceSuccess:
    @pytest.fixture
    def xml_output(self, tmp_path):
        """A real temp file that mimics Audiveris MusicXML output."""
        f = tmp_path / "output.mxl"
        f.write_bytes(b"<score-partwise version='4.0'/>")
        return f

    @pytest.fixture(autouse=True)
    def _isolate_io(self, monkeypatch, xml_output):
        """Isolate FileService (no real data/uploads writes) and skip real analysis.

        ``save_uploaded_file`` is stubbed to return the temp output path itself, so
        ``musicxml_path`` stays equal to ``xml_output`` and no real analysis runs.
        The stub accepts **kwargs so it stays compatible when callers pass
        ``use_library=True``, ``piece=...``, ``kind=...``.
        """
        monkeypatch.setattr(
            "src.services.file_service.FileService.save_uploaded_file",
            lambda *_args, **_kwargs: str(xml_output),
        )
        monkeypatch.setattr(
            "src.services.analysis_service.AnalysisService.analyze_file",
            lambda self, path: None,
        )

    def test_returns_success_true(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)

        assert result is not None
        assert result["success"] is True

    def test_result_contains_expected_keys(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)

        for key in ("success", "file_id", "music_piece_id", "musicxml_path", "output_file_id"):
            assert key in result, f"Missing key: {key}"

    def test_file_id_matches_source(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)

        assert result["file_id"] == pdf_file.id

    def test_music_piece_id_matches_source(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)

        assert result["music_piece_id"] == pdf_file.music_piece_id

    def test_musicxml_path_points_to_output(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)

        assert result["musicxml_path"] == str(xml_output)

    def test_persists_new_music_file_record(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        initial_count = db_session.query(MusicFile).count()
        service.process_file(db_session, pdf_file.id)
        db_session.commit()

        assert db_session.query(MusicFile).count() == initial_count + 1

    def test_new_file_has_xml_type(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        new_file = (
            db_session.query(MusicFile).filter(MusicFile.id == result["output_file_id"]).first()
        )
        assert new_file is not None
        assert new_file.file_type == FileType.XML

    def test_new_file_shares_music_piece_id(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        new_file = (
            db_session.query(MusicFile).filter(MusicFile.id == result["output_file_id"]).first()
        )
        assert new_file.music_piece_id == pdf_file.music_piece_id

    def test_new_file_description_contains_audiveris(
        self, db_session, pdf_file, tmp_path, xml_output
    ):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        new_file = (
            db_session.query(MusicFile).filter(MusicFile.id == result["output_file_id"]).first()
        )
        assert "Audiveris" in new_file.description

    def test_new_file_is_processed_flag_set(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        new_file = (
            db_session.query(MusicFile).filter(MusicFile.id == result["output_file_id"]).first()
        )
        assert new_file.is_processed == 1

    def test_output_file_id_returned_in_result(self, db_session, pdf_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        # output_file_id must match the persisted record's PK
        new_file = (
            db_session.query(MusicFile).filter(MusicFile.id == result["output_file_id"]).first()
        )
        assert new_file is not None

    def test_scan_file_type_also_succeeds(self, db_session, scan_file, tmp_path, xml_output):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, scan_file.id)

        assert result["success"] is True

    def test_converter_called_with_correct_input_path(
        self, db_session, pdf_file, tmp_path, xml_output
    ):
        service = _make_service(tmp_path)
        service._converter.convert.return_value = str(xml_output)

        service.process_file(db_session, pdf_file.id)

        service._converter.convert.assert_called_once_with(
            input_path=pdf_file.file_path,
            output_dir=str(tmp_path),
        )


# ---------------------------------------------------------------------------
# Tests: process_file() — automatic musical analysis enrichment
# ---------------------------------------------------------------------------


class TestOMRServiceAutoAnalysis:
    """A successful OMR run analyses the score and enriches the parent piece."""

    @pytest.fixture
    def xml_output(self, tmp_path):
        f = tmp_path / "out.mxl"
        f.write_bytes(b"<score-partwise version='4.0'/>")
        return f

    @pytest.fixture(autouse=True)
    def _stub_filesvc(self, monkeypatch, xml_output):
        # Keep the output in tmp (no real data/uploads writes).
        # Accept **kwargs so the stub stays compatible when callers pass
        # use_library=True, piece=..., kind=... keywords.
        monkeypatch.setattr(
            "src.services.file_service.FileService.save_uploaded_file",
            lambda *_args, **_kwargs: str(xml_output),
        )

    @staticmethod
    def _fake_descriptor():
        from src.analysis.score_descriptor import ScoreDescriptor

        return ScoreDescriptor(
            detected_key="F major",
            key_confidence=0.9,
            time_signatures=["3/4"],
            measure_count=42,
            voice_count=4,
            voice_names=["S", "A", "T", "B"],
            texture_type="homophonic_chorale",
            harmony_epoch="renaissance",
            lyrics_language="la",
            estimated_grade=2,
            grade_label="elementary",
            narrative_description="A short narrative.",
        )

    def test_fills_empty_piece_fields(self, db_session, pdf_file, xml_output, monkeypatch):
        desc = self._fake_descriptor()
        monkeypatch.setattr(
            "src.services.analysis_service.AnalysisService.analyze_file",
            lambda self, path: desc,
        )
        service = _make_service()
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)
        db_session.commit()

        piece = (
            db_session.query(MusicPiece).filter(MusicPiece.id == pdf_file.music_piece_id).first()
        )
        assert piece.key_signature == "F major"
        assert piece.time_signature == "3/4"
        assert piece.measures_count == 42
        assert piece.language == "łacina"
        assert "[Auto-analiza OMR]" in (piece.description or "")
        assert result["analysis"]["detected_key"] == "F major"

    def test_does_not_overwrite_user_data(self, db_session, pdf_file, xml_output, monkeypatch):
        desc = self._fake_descriptor()
        monkeypatch.setattr(
            "src.services.analysis_service.AnalysisService.analyze_file",
            lambda self, path: desc,
        )
        piece = (
            db_session.query(MusicPiece).filter(MusicPiece.id == pdf_file.music_piece_id).first()
        )
        piece.key_signature = "C major"  # user-entered value
        db_session.flush()

        service = _make_service()
        service._converter.convert.return_value = str(xml_output)
        service.process_file(db_session, pdf_file.id)
        db_session.commit()

        db_session.refresh(piece)
        assert piece.key_signature == "C major"  # preserved

    def test_analysis_failure_is_non_fatal(self, db_session, pdf_file, xml_output, monkeypatch):
        monkeypatch.setattr(
            "src.services.analysis_service.AnalysisService.analyze_file",
            lambda self, path: None,
        )
        service = _make_service()
        service._converter.convert.return_value = str(xml_output)

        result = service.process_file(db_session, pdf_file.id)

        assert result["success"] is True
        assert result["analysis"] is None
