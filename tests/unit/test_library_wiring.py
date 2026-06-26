"""Tests proving that the library-routing wiring is correct.

These tests verify that:
- ``FileService.save_uploaded_file(use_library=True, ...)`` places files under the
  library root tree (``pieces/<id>_<slug>/...``) and NOT under ``data/uploads/``.
- ``MusicFile.file_path`` stored in the DB points to the library location.
- Each ``MusicFileKind`` lands in the expected sub-directory (sources/, scores/,
  derived/).

All tests are fully isolated:
- In-memory SQLite database (no real ``church_music.db`` touched).
- Filesystem: monkeypatched ``CMO_LIBRARY_ROOT`` pointing to a temporary directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicFileKind, MusicPiece
from src.services.file_service import FileService
from src.services.library_service import LibraryService

# ---------------------------------------------------------------------------
# Shared fixtures (mirrors the pattern from test_library_migration.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session — isolated per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Sess = sessionmaker(bind=engine)
    sess = Sess()
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


@pytest.fixture()
def piece_no_slug(db_session: Session) -> MusicPiece:
    """A committed MusicPiece without a pre-set slug (slug derived from title)."""
    p = MusicPiece(title="Chwała na Wysokości")
    db_session.add(p)
    db_session.commit()
    return p


# ---------------------------------------------------------------------------
# FileService.save_uploaded_file(use_library=True)
# ---------------------------------------------------------------------------


class TestSaveUploadedFileLibraryRouting:
    """Unit tests for the use_library=True path in FileService."""

    def test_file_created_under_library_root(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """The saved file must reside somewhere inside the library root."""
        stored = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename="scan.pdf",
            file_data=b"%PDF-fake",
            use_library=True,
            piece=piece,
            kind=MusicFileKind.SOURCE_PDF,
        )
        assert (
            str(library_root) in stored
        ), f"Expected path under library root {library_root}, got {stored}"

    def test_file_not_in_data_uploads(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """The saved file must NOT go to the legacy data/uploads directory."""
        stored = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename="scan.pdf",
            file_data=b"%PDF-fake",
            use_library=True,
            piece=piece,
            kind=MusicFileKind.SOURCE_PDF,
        )
        assert (
            "data/uploads" not in stored and "data\\uploads" not in stored
        ), f"File was saved to legacy path: {stored}"

    def test_file_path_contains_piece_dir(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """File path must embed the piece directory in format ``<id:04d>_<slug>``."""
        stored = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename="scan.pdf",
            file_data=b"%PDF-fake",
            use_library=True,
            piece=piece,
            kind=MusicFileKind.SOURCE_PDF,
        )
        expected_dir = LibraryService.piece_dirname(piece.id, "ave-maria")
        assert expected_dir in stored, f"Expected piece dir '{expected_dir}' in path '{stored}'"

    def test_file_bytes_written_correctly(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """Content bytes must match what was passed to save_uploaded_file."""
        content = b"<score-partwise/>"
        stored = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename="score.xml",
            file_data=content,
            use_library=True,
            piece=piece,
            kind=MusicFileKind.OMR_RAW,
        )
        assert Path(stored).read_bytes() == content

    def test_raises_when_piece_is_none_and_use_library(self, db_session: Session) -> None:
        """Passing use_library=True without a piece must raise ValueError."""
        with pytest.raises(ValueError, match="piece must be provided"):
            FileService.save_uploaded_file(
                piece_id=1,
                filename="scan.pdf",
                file_data=b"data",
                use_library=True,
                piece=None,
                kind=MusicFileKind.SOURCE_SCAN,
            )

    def test_slug_derived_from_title_when_not_set(
        self, db_session: Session, library_root: Path, piece_no_slug: MusicPiece
    ) -> None:
        """When piece.slug is None, LibraryService slugifies the title automatically."""
        stored = FileService.save_uploaded_file(
            piece_id=piece_no_slug.id,
            filename="scan.jpg",
            file_data=b"\xff\xd8\xff fake",
            use_library=True,
            piece=piece_no_slug,
            kind=MusicFileKind.SOURCE_SCAN,
        )
        # The slug derived from "Chwała na Wysokości" should contain "chwala" in ASCII
        assert "chwala" in stored.lower(), f"Expected slug derived from title in path '{stored}'"


# ---------------------------------------------------------------------------
# Kind → sub-directory routing
# ---------------------------------------------------------------------------


class TestKindSubdirRouting:
    """Each MusicFileKind must route to the correct library sub-directory."""

    def _save(
        self, library_root: Path, piece: MusicPiece, kind: MusicFileKind, filename: str
    ) -> str:
        return FileService.save_uploaded_file(
            piece_id=piece.id,
            filename=filename,
            file_data=b"content",
            use_library=True,
            piece=piece,
            kind=kind,
        )

    def test_source_pdf_goes_to_sources(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.SOURCE_PDF, "sheet.pdf")
        assert Path(stored).parent.name == "sources", f"Got {Path(stored).parent.name}"

    def test_source_scan_goes_to_sources(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.SOURCE_SCAN, "page.png")
        assert Path(stored).parent.name == "sources", f"Got {Path(stored).parent.name}"

    def test_omr_raw_goes_to_derived(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.OMR_RAW, "raw.mxl")
        assert Path(stored).parent.name == "derived", f"Got {Path(stored).parent.name}"

    def test_corrected_goes_to_scores(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.CORRECTED, "corrected.musicxml")
        assert Path(stored).parent.name == "scores", f"Got {Path(stored).parent.name}"

    def test_final_goes_to_scores(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.FINAL, "final.musicxml")
        assert Path(stored).parent.name == "scores", f"Got {Path(stored).parent.name}"

    def test_reference_goes_to_scores(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.REFERENCE, "ref.musicxml")
        assert Path(stored).parent.name == "scores", f"Got {Path(stored).parent.name}"

    def test_editable_goes_to_scores(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.EDITABLE, "score.mscz")
        assert Path(stored).parent.name == "scores", f"Got {Path(stored).parent.name}"

    def test_other_goes_to_derived(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        stored = self._save(library_root, piece, MusicFileKind.OTHER, "misc.txt")
        assert Path(stored).parent.name == "derived", f"Got {Path(stored).parent.name}"


# ---------------------------------------------------------------------------
# End-to-end: MusicFile.file_path stored in DB points to library
# ---------------------------------------------------------------------------


class TestMusicFilePathInDatabase:
    """Integration tests: verify that MusicFile rows written via the service path
    carry file_path values inside the library root (not data/uploads)."""

    def test_music_file_path_points_to_library(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """Simulate the upload path and verify MusicFile.file_path is in the library."""
        file_data = b"%PDF-1.4 fake"
        filename = "scan.pdf"
        kind = MusicFileKind.SOURCE_PDF

        file_path = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename=filename,
            file_data=file_data,
            use_library=True,
            piece=piece,
            kind=kind,
        )
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path=file_path,
            file_type=FileType.PDF,
            original_filename=filename,
            file_size=len(file_data),
            kind=kind,
        )
        db_session.add(mf)
        db_session.commit()

        fetched = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert fetched is not None
        assert (
            str(library_root) in fetched.file_path
        ), f"Expected library root in file_path, got: {fetched.file_path}"
        assert (
            "data/uploads" not in fetched.file_path
        ), f"file_path must not point to data/uploads: {fetched.file_path}"
        assert (
            "data\\uploads" not in fetched.file_path
        ), f"file_path must not point to data/uploads: {fetched.file_path}"

    def test_music_file_path_not_in_data_uploads_when_use_library(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """Regression: the default (use_library=False) went to data/uploads.
        With use_library=True this must no longer happen.
        """
        stored = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename="score.xml",
            file_data=b"<score/>",
            use_library=True,
            piece=piece,
            kind=MusicFileKind.OMR_RAW,
        )
        assert "uploads" not in str(Path(stored).parts), f"Expected library path, got: {stored}"

    def test_kind_field_is_set_on_music_file(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """The kind field on MusicFile must reflect the upload kind."""
        file_data = b"<score-partwise/>"
        kind = MusicFileKind.CORRECTED

        stored = FileService.save_uploaded_file(
            piece_id=piece.id,
            filename="corrected.musicxml",
            file_data=file_data,
            use_library=True,
            piece=piece,
            kind=kind,
        )
        mf = MusicFile(
            music_piece_id=piece.id,
            file_path=stored,
            file_type=FileType.XML,
            original_filename="corrected.musicxml",
            file_size=len(file_data),
            kind=kind,
        )
        db_session.add(mf)
        db_session.commit()

        fetched = db_session.query(MusicFile).filter_by(music_piece_id=piece.id).first()
        assert fetched is not None
        assert fetched.kind == MusicFileKind.CORRECTED

    def test_multiple_uploads_go_to_correct_subdirs(
        self, db_session: Session, library_root: Path, piece: MusicPiece
    ) -> None:
        """Multiple files with different kinds all land in their own sub-directories."""
        uploads = [
            ("scan.pdf", b"%PDF", MusicFileKind.SOURCE_PDF, FileType.PDF, "sources"),
            ("scan.png", b"\x89PNG", MusicFileKind.SOURCE_SCAN, FileType.SCAN, "sources"),
            ("raw.xml", b"<score/>", MusicFileKind.OMR_RAW, FileType.XML, "derived"),
            (
                "corrected.musicxml",
                b"<score/>",
                MusicFileKind.CORRECTED,
                FileType.XML,
                "scores",
            ),
        ]
        for filename, data, kind, ftype, expected_subdir in uploads:
            stored = FileService.save_uploaded_file(
                piece_id=piece.id,
                filename=filename,
                file_data=data,
                use_library=True,
                piece=piece,
                kind=kind,
            )
            actual_subdir = Path(stored).parent.name
            assert actual_subdir == expected_subdir, (
                f"{filename}: expected sub-dir '{expected_subdir}', got '{actual_subdir}' "
                f"(path: {stored})"
            )
