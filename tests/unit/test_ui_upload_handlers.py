"""End-to-end tests for the NiceGUI upload handlers and file-kind mapping.

Covers points 2 and 3 from the library-wiring acceptance criteria:
- _file_kind_for_upload: complete extension→MusicFileKind mapping for both library.py
  and processing.py (they must be behaviorally identical).
- _save_uploaded (library.py): calling the handler creates a MusicFile whose file_path
  is inside CMO_LIBRARY_ROOT (not data/uploads), with the correct MusicFileKind.
- _upload_source (processing.py): same guarantees for the processing tab's async handler.

All tests are fully isolated:
- In-memory SQLite (no church_music.db touched).
- CMO_LIBRARY_ROOT is monkeypatched to an ephemeral tmp directory.
- get_db_session is patched to yield the test session (no real session factory used).
- NiceGUI UI calls (ui.notify, _panel.refresh) are replaced with MagicMocks.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, MusicFile, MusicFileKind, MusicPiece

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """In-memory SQLite session — isolated per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Monkeypatch CMO_LIBRARY_ROOT to an isolated tmp directory."""
    root = tmp_path / "church-music-library"
    root.mkdir()
    monkeypatch.setenv("CMO_LIBRARY_ROOT", str(root))
    return root


@pytest.fixture()
def piece(db_session: Session) -> MusicPiece:
    """A committed MusicPiece with a known slug."""
    p = MusicPiece(title="Ave Maria", slug="ave-maria")
    db_session.add(p)
    db_session.commit()
    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_session_mock(session: Session):
    """Return a zero-argument context manager factory that yields *session*.

    Replaces ``get_db_session`` in the target module:
    ``with get_db_session() as db:`` → yields the test session.
    """

    @contextlib.contextmanager
    def _cm():
        yield session

    return _cm


def _make_upload_event(name: str, data: bytes) -> MagicMock:
    """Build a minimal mock of a NiceGUI UploadEventArguments."""
    ev = MagicMock()
    ev.name = name
    ev.content = MagicMock()
    ev.content.read.return_value = data
    return ev


# ---------------------------------------------------------------------------
# Kind mapping — library.py
# ---------------------------------------------------------------------------


class TestFileKindMappingLibrary:
    """_file_kind_for_upload in library.py must map filename extensions correctly."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("sheet.pdf", MusicFileKind.SOURCE_PDF),
            ("scan.jpg", MusicFileKind.SOURCE_SCAN),
            ("scan.jpeg", MusicFileKind.SOURCE_SCAN),
            ("scan.png", MusicFileKind.SOURCE_SCAN),
            ("scan.tiff", MusicFileKind.SOURCE_SCAN),
            ("scan.bmp", MusicFileKind.SOURCE_SCAN),
            ("score.mscz", MusicFileKind.EDITABLE),
            ("score.mscx", MusicFileKind.EDITABLE),
            ("score.xml", MusicFileKind.OMR_RAW),
            ("score.musicxml", MusicFileKind.OMR_RAW),
            ("lyrics.txt", MusicFileKind.OTHER),
            ("song.ly", MusicFileKind.OTHER),
        ],
    )
    def test_extension_maps_to_correct_kind(self, filename: str, expected: MusicFileKind) -> None:
        from src.app_ng.pages.library import _file_kind_for_upload

        assert _file_kind_for_upload(filename) == expected, (
            f"Expected {expected!r} for {filename!r}, " f"got {_file_kind_for_upload(filename)!r}"
        )


# ---------------------------------------------------------------------------
# Kind mapping parity — processing.py must match library.py
# ---------------------------------------------------------------------------


class TestFileKindMappingProcessingParity:
    """_file_kind_for_upload in processing.py must return the same kind as library.py
    for every extension — the two implementations must stay in sync."""

    @pytest.mark.parametrize(
        "filename",
        [
            "sheet.pdf",
            "scan.jpg",
            "scan.jpeg",
            "scan.png",
            "scan.tiff",
            "scan.bmp",
            "score.mscz",
            "score.mscx",
            "score.xml",
            "score.musicxml",
            "data.txt",
        ],
    )
    def test_processing_kind_matches_library_kind(self, filename: str) -> None:
        from src.app_ng.pages.library import _file_kind_for_upload as lib_fn
        from src.app_ng.pages.processing import _file_kind_for_upload as proc_fn

        lib_kind = lib_fn(filename)
        proc_kind = proc_fn(filename)
        assert proc_kind == lib_kind, (
            f"Kind mismatch for {filename!r}: "
            f"library.py={lib_kind!r}, processing.py={proc_kind!r}"
        )


# ---------------------------------------------------------------------------
# _save_uploaded — library.py (sync handler)
# ---------------------------------------------------------------------------


class TestSaveUploaded:
    """Integration tests for src/app_ng/pages/library.py::_save_uploaded.

    The handler is called with a mock upload event and a patched get_db_session
    that yields the test in-memory session. Assertions focus on:
    - File is saved inside CMO_LIBRARY_ROOT, not data/uploads.
    - MusicFile row is created in the database with the correct kind and path.
    - File bytes are actually written to disk.
    """

    def _call(
        self,
        db_session: Session,
        library_root: Path,
        piece_id: int,
        name: str = "scan.pdf",
        data: bytes = b"%PDF-fake",
    ) -> None:
        """Invoke _save_uploaded with fully mocked dependencies."""
        from src.app_ng.pages.library import _save_uploaded

        upload = _make_upload_event(name, data)
        with patch(
            "src.app_ng.pages.library.get_db_session",
            _make_db_session_mock(db_session),
        ):
            _save_uploaded(piece_id, upload)

    # --- existence ---

    def test_creates_music_file_row_in_db(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf is not None, "Expected a MusicFile row to be created"

    # --- path guards ---

    def test_file_path_is_under_library_root(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert (
            str(library_root) in mf.file_path
        ), f"Expected path under {library_root}, got: {mf.file_path}"

    def test_file_path_not_under_data_uploads(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert (
            "data/uploads" not in mf.file_path
        ), f"Regression: file saved to legacy data/uploads path: {mf.file_path}"
        assert "data\\uploads" not in mf.file_path

    def test_file_path_contains_piece_dir(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert "ave-maria" in mf.file_path.replace(
            "\\", "/"
        ), f"Expected piece slug 'ave-maria' in path: {mf.file_path}"

    # --- disk write ---

    def test_file_bytes_written_to_disk(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        content = b"%PDF-test-content"
        self._call(db_session, library_root, piece.id, data=content)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        p = Path(mf.file_path)
        assert p.exists(), f"Expected file on disk at {p}"
        assert p.read_bytes() == content

    # --- kind mapping ---

    def test_kind_is_source_pdf_for_pdf_upload(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="scan.pdf")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf.kind == MusicFileKind.SOURCE_PDF

    def test_kind_is_source_scan_for_jpg_upload(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="scan.jpg", data=b"\xff\xd8\xff")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf.kind == MusicFileKind.SOURCE_SCAN

    def test_kind_is_editable_for_mscz_upload(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="score.mscz", data=b"fake-mscz")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf.kind == MusicFileKind.EDITABLE

    def test_kind_is_omr_raw_for_xml_upload(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="score.xml", data=b"<score/>")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf.kind == MusicFileKind.OMR_RAW

    # --- sub-directory routing ---

    def test_pdf_lands_in_sources_subdir(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="sheet.pdf")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert Path(mf.file_path).parent.name == "sources"

    def test_xml_lands_in_derived_subdir(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="raw.xml", data=b"<score/>")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert Path(mf.file_path).parent.name == "derived"

    # --- defensive / edge cases ---

    def test_piece_not_found_does_not_raise_or_create_row(
        self, db_session: Session, library_root: Path
    ) -> None:
        """Handler must silently skip when piece_id does not exist."""
        from src.app_ng.pages.library import _save_uploaded

        upload = _make_upload_event("scan.pdf", b"%PDF")
        with patch(
            "src.app_ng.pages.library.get_db_session",
            _make_db_session_mock(db_session),
        ):
            _save_uploaded(99999, upload)  # no piece with this id

        assert (
            db_session.query(MusicFile).count() == 0
        ), "No MusicFile must be created when piece is missing"


# ---------------------------------------------------------------------------
# _upload_source — processing.py (async handler)
# ---------------------------------------------------------------------------


class TestUploadSource:
    """Integration tests for src/app_ng/pages/processing.py::_upload_source.

    The handler is async (``async def _upload_source``), but contains no ``await``
    expressions, so ``asyncio.run()`` executes it fully synchronously. NiceGUI calls
    (``ui.notify`` and ``_panel.refresh``) are replaced with MagicMocks to avoid
    requiring an active NiceGUI server context.
    """

    def _call(
        self,
        db_session: Session,
        library_root: Path,
        piece_id: int,
        name: str = "scan.pdf",
        data: bytes = b"%PDF-fake",
    ) -> None:
        """Invoke _upload_source with fully mocked dependencies."""
        from src.app_ng.pages.processing import _upload_source

        upload = _make_upload_event(name, data)
        with (
            patch(
                "src.app_ng.pages.processing.get_db_session",
                _make_db_session_mock(db_session),
            ),
            patch("src.app_ng.pages.processing.ui"),  # silences ui.notify(...)
            patch("src.app_ng.pages.processing._panel"),  # silences _panel.refresh()
        ):
            asyncio.run(_upload_source(piece_id, upload))

    # --- existence ---

    def test_creates_music_file_row_in_db(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf is not None, "Expected a MusicFile row to be created"

    # --- path guards ---

    def test_file_path_is_under_library_root(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert (
            str(library_root) in mf.file_path
        ), f"Expected path under {library_root}, got: {mf.file_path}"

    def test_file_path_not_under_data_uploads(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert (
            "data/uploads" not in mf.file_path
        ), f"Regression: file saved to legacy data/uploads: {mf.file_path}"
        assert "data\\uploads" not in mf.file_path

    # --- disk write ---

    def test_file_bytes_written_to_disk(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        content = b"%PDF-source-file"
        self._call(db_session, library_root, piece.id, data=content)
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        p = Path(mf.file_path)
        assert p.exists(), f"Expected file on disk at {p}"
        assert p.read_bytes() == content

    # --- kind mapping ---

    def test_kind_is_source_pdf_for_pdf_upload(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="scan.pdf")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf.kind == MusicFileKind.SOURCE_PDF

    def test_kind_is_source_scan_for_png_upload(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="scan.png", data=b"\x89PNG")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert mf.kind == MusicFileKind.SOURCE_SCAN

    # --- sub-directory routing ---

    def test_pdf_lands_in_sources_subdir(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        self._call(db_session, library_root, piece.id, name="source.pdf")
        mf = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert Path(mf.file_path).parent.name == "sources"

    # --- defensive ---

    def test_piece_not_found_does_not_raise_or_create_row(
        self, db_session: Session, library_root: Path
    ) -> None:
        """Handler must not crash when piece_id does not exist — it calls ui.notify instead."""
        from src.app_ng.pages.processing import _upload_source

        upload = _make_upload_event("scan.pdf", b"%PDF")
        with (
            patch(
                "src.app_ng.pages.processing.get_db_session",
                _make_db_session_mock(db_session),
            ),
            patch("src.app_ng.pages.processing.ui"),
            patch("src.app_ng.pages.processing._panel"),
        ):
            asyncio.run(_upload_source(99999, upload))

        assert (
            db_session.query(MusicFile).count() == 0
        ), "No MusicFile must be created when piece is missing"
