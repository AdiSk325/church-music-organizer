"""Tests for the src/services layer."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicPiece
from src.services import FileService, MusicPieceService


@pytest.fixture
def db_session():
    """In-memory SQLite session for service tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# MusicPieceService
# ---------------------------------------------------------------------------


class TestMusicPieceServiceCreate:
    def test_create_returns_piece_with_id(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="Ave Maria")
        db_session.commit()
        assert piece.id is not None
        assert piece.title == "Ave Maria"

    def test_create_ignores_unknown_keys(self, db_session):
        # Should not raise even though "nonexistent_field" is not a column
        piece = MusicPieceService.create_piece(
            db_session, title="Test", nonexistent_field="ignored"
        )
        db_session.commit()
        assert piece.title == "Test"

    def test_create_stores_all_valid_fields(self, db_session):
        piece = MusicPieceService.create_piece(
            db_session,
            title="Psalm 23",
            composer="Schubert",
            lyrics_author="Jan Kowalski",
            occasion="Easter",
            liturgical_season="Lent",
        )
        db_session.commit()
        assert piece.composer == "Schubert"
        assert piece.lyrics_author == "Jan Kowalski"
        assert piece.occasion == "Easter"
        assert piece.liturgical_season == "Lent"


class TestMusicPieceServiceGet:
    def test_get_existing_piece(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="Hallelujah")
        db_session.commit()

        fetched = MusicPieceService.get_piece(db_session, piece.id)
        assert fetched is not None
        assert fetched.id == piece.id
        assert fetched.title == "Hallelujah"

    def test_get_nonexistent_piece_returns_none(self, db_session):
        result = MusicPieceService.get_piece(db_session, 99999)
        assert result is None


class TestMusicPieceServiceList:
    def _seed(self, db_session):
        pieces = [
            MusicPieceService.create_piece(
                db_session,
                title="Gloria",
                composer="Bach",
                occasion="Easter",
                liturgical_season="Advent",
            ),
            MusicPieceService.create_piece(
                db_session,
                title="Agnus Dei",
                lyrics_author="Jan Kowalski",
                occasion="Wedding",
                liturgical_season="Lent",
            ),
            MusicPieceService.create_piece(
                db_session,
                title="Kyrie",
                composer="Bach",
                occasion="Easter",
                liturgical_season="Advent",
            ),
        ]
        db_session.commit()
        return pieces

    def test_list_all_no_filters(self, db_session):
        self._seed(db_session)
        items, total = MusicPieceService.list_pieces(db_session)
        assert total == 3
        assert len(items) == 3

    def test_list_search_by_title(self, db_session):
        self._seed(db_session)
        items, total = MusicPieceService.list_pieces(db_session, search="gloria")
        assert total == 1
        assert items[0].title == "Gloria"

    def test_list_search_by_composer(self, db_session):
        self._seed(db_session)
        items, total = MusicPieceService.list_pieces(db_session, search="bach")
        assert total == 2

    def test_list_search_by_lyrics_author(self, db_session):
        self._seed(db_session)
        items, total = MusicPieceService.list_pieces(db_session, search="kowalski")
        assert total == 1
        assert items[0].title == "Agnus Dei"

    def test_list_filter_by_occasion(self, db_session):
        self._seed(db_session)
        items, total = MusicPieceService.list_pieces(db_session, occasion="Easter")
        assert total == 2

    def test_list_filter_by_liturgical_season(self, db_session):
        self._seed(db_session)
        items, total = MusicPieceService.list_pieces(db_session, liturgical_season="Lent")
        assert total == 1

    def test_list_pagination(self, db_session):
        self._seed(db_session)
        page0, total = MusicPieceService.list_pieces(db_session, page=0, per_page=2)
        page1, total2 = MusicPieceService.list_pieces(db_session, page=1, per_page=2)
        assert total == total2 == 3
        assert len(page0) == 2
        assert len(page1) == 1

    def test_list_empty_result(self, db_session):
        items, total = MusicPieceService.list_pieces(db_session)
        assert items == []
        assert total == 0


class TestMusicPieceServiceUpdate:
    def test_update_existing_piece(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="Old Title")
        db_session.commit()

        updated = MusicPieceService.update_piece(db_session, piece.id, title="New Title")
        db_session.commit()

        assert updated is not None
        assert updated.id == piece.id
        assert updated.title == "New Title"

    def test_update_ignores_unknown_keys(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="Piece")
        db_session.commit()

        result = MusicPieceService.update_piece(
            db_session, piece.id, composer="Bach", nonexistent="value"
        )
        db_session.commit()
        assert result.composer == "Bach"

    def test_update_nonexistent_returns_none(self, db_session):
        result = MusicPieceService.update_piece(db_session, 99999, title="x")
        assert result is None

    def test_update_does_not_change_id(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="Piece")
        db_session.commit()
        original_id = piece.id

        MusicPieceService.update_piece(db_session, piece.id, id=999, title="Changed")
        db_session.commit()

        assert piece.id == original_id


class TestMusicPieceServiceDelete:
    def test_delete_existing_piece_returns_true(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="To Delete")
        db_session.commit()

        result = MusicPieceService.delete_piece(db_session, piece.id)
        db_session.commit()

        assert result is True
        assert MusicPieceService.get_piece(db_session, piece.id) is None

    def test_delete_nonexistent_returns_false(self, db_session):
        result = MusicPieceService.delete_piece(db_session, 99999)
        assert result is False

    def test_delete_cascades_files(self, db_session):
        piece = MusicPieceService.create_piece(db_session, title="With File")
        db_session.commit()

        music_file = MusicFile(
            music_piece_id=piece.id,
            file_path="data/uploads/1/test.pdf",
            file_type=FileType.PDF,
        )
        db_session.add(music_file)
        db_session.commit()

        MusicPieceService.delete_piece(db_session, piece.id)
        db_session.commit()

        assert db_session.query(MusicFile).count() == 0


# ---------------------------------------------------------------------------
# FileService
# ---------------------------------------------------------------------------


class TestFileServiceSaveUploadedFile:
    def test_saves_file_to_correct_path(self, tmp_path):
        dest = FileService.save_uploaded_file(
            piece_id=42,
            filename="score.pdf",
            file_data=b"PDF content",
            upload_dir=str(tmp_path),
        )
        saved = Path(dest)
        assert saved.exists()
        assert saved.read_bytes() == b"PDF content"
        assert saved.parent.name == "42"

    def test_creates_parent_directory(self, tmp_path):
        upload_dir = tmp_path / "uploads"
        FileService.save_uploaded_file(
            piece_id=7,
            filename="file.pdf",
            file_data=b"data",
            upload_dir=str(upload_dir),
        )
        assert (upload_dir / "7" / "file.pdf").exists()

    def test_strips_path_traversal(self, tmp_path):
        dest = FileService.save_uploaded_file(
            piece_id=1,
            filename="../../etc/passwd",
            file_data=b"data",
            upload_dir=str(tmp_path),
        )
        saved = Path(dest)
        # Must be inside the upload dir, never at /etc/passwd
        assert saved.is_relative_to(tmp_path)
        assert "etc" not in saved.parts[:-1]

    def test_sanitises_special_characters(self, tmp_path):
        dest = FileService.save_uploaded_file(
            piece_id=1,
            filename="bad name!@#.pdf",
            file_data=b"x",
            upload_dir=str(tmp_path),
        )
        saved = Path(dest)
        # Spaces and special chars replaced, extension preserved
        assert " " not in saved.name
        assert saved.exists()


class TestFileServiceSaveOcrResult:
    def test_saves_ocr_fields(self, db_session):
        piece = MusicPiece(title="Scan Piece")
        db_session.add(piece)
        db_session.flush()

        music_file = MusicFile(
            music_piece_id=piece.id,
            file_path="data/uploads/1/scan.pdf",
            file_type=FileType.SCAN,
        )
        db_session.add(music_file)
        db_session.flush()

        FileService.save_ocr_result(
            db_session,
            file_id=music_file.id,
            extracted_text="Kyrie eleison",
            confidence=87,
        )
        db_session.commit()

        db_session.refresh(music_file)
        assert music_file.extracted_text == "Kyrie eleison"
        assert music_file.ocr_confidence == 87
        assert music_file.is_processed == 1

    def test_save_ocr_nonexistent_file_does_nothing(self, db_session):
        # Should not raise
        FileService.save_ocr_result(db_session, file_id=99999, extracted_text="text", confidence=50)

    def test_save_ocr_marks_as_processed(self, db_session):
        piece = MusicPiece(title="Piece")
        db_session.add(piece)
        db_session.flush()

        music_file = MusicFile(
            music_piece_id=piece.id,
            file_path="data/uploads/1/f.pdf",
            file_type=FileType.PDF,
            is_processed=0,
        )
        db_session.add(music_file)
        db_session.flush()

        FileService.save_ocr_result(db_session, music_file.id, "text", 75)
        db_session.commit()

        db_session.refresh(music_file)
        assert music_file.is_processed == 1
