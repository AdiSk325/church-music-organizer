"""Tests for the src/services layer."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicPiece, Translation, TranslationKind
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


class TestSetPrimaryTranslationPl:
    """Tests for MusicPieceService.set_primary_translation_pl."""

    def _make_piece(self, db_session) -> MusicPiece:
        piece = MusicPieceService.create_piece(db_session, title="Test Piece")
        db_session.commit()
        return piece

    def _primary_pl_rows(self, db_session, piece_id: int):
        return (
            db_session.query(Translation)
            .filter(
                Translation.music_piece_id == piece_id,
                Translation.language == "pl",
                Translation.is_primary.is_(True),
            )
            .all()
        )

    # ------------------------------------------------------------------
    # Basic write: both storage locations updated
    # ------------------------------------------------------------------

    def test_sets_legacy_column_and_translation_row(self, db_session):
        piece = self._make_piece(db_session)
        result = MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Tekst PL")
        db_session.commit()

        assert result is not None
        assert result.lyrics_translation_pl == "Tekst PL"
        assert result.primary_translation_pl == "Tekst PL"

        primaries = self._primary_pl_rows(db_session, piece.id)
        assert len(primaries) == 1
        assert primaries[0].text == "Tekst PL"

    def test_translation_row_has_literal_kind(self, db_session):
        piece = self._make_piece(db_session)
        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "PL text")
        db_session.commit()

        primaries = self._primary_pl_rows(db_session, piece.id)
        assert primaries[0].kind == TranslationKind.LITERAL

    # ------------------------------------------------------------------
    # Idempotent update: no duplicate rows
    # ------------------------------------------------------------------

    def test_second_call_updates_same_row_no_duplicate(self, db_session):
        piece = self._make_piece(db_session)
        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Pierwsze")
        db_session.commit()

        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Drugie")
        db_session.commit()

        primaries = self._primary_pl_rows(db_session, piece.id)
        assert len(primaries) == 1
        assert primaries[0].text == "Drugie"

        pl_total = (
            db_session.query(Translation)
            .filter(
                Translation.music_piece_id == piece.id,
                Translation.language == "pl",
            )
            .count()
        )
        assert pl_total == 1  # still just the one row

    # ------------------------------------------------------------------
    # Clear: empty / None cleans up
    # ------------------------------------------------------------------

    def test_empty_string_clears_legacy_column_and_removes_primary_row(self, db_session):
        piece = self._make_piece(db_session)
        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Will be cleared")
        db_session.commit()

        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "")
        db_session.commit()

        db_session.refresh(piece)
        assert piece.lyrics_translation_pl is None
        assert piece.primary_translation_pl is None  # legacy fallback also None
        assert len(self._primary_pl_rows(db_session, piece.id)) == 0

    def test_none_clears_same_as_empty_string(self, db_session):
        piece = self._make_piece(db_session)
        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Some text")
        db_session.commit()

        MusicPieceService.set_primary_translation_pl(db_session, piece.id, None)
        db_session.commit()

        db_session.refresh(piece)
        assert piece.lyrics_translation_pl is None
        assert len(self._primary_pl_rows(db_session, piece.id)) == 0

    # ------------------------------------------------------------------
    # Nonexistent piece returns None
    # ------------------------------------------------------------------

    def test_nonexistent_piece_returns_none(self, db_session):
        result = MusicPieceService.set_primary_translation_pl(db_session, 99999, "text")
        assert result is None

    # ------------------------------------------------------------------
    # Regression: existing Translation(pl, primary) is updated, not shadowed
    # ------------------------------------------------------------------

    def test_existing_primary_row_is_updated_not_shadowed(self, db_session):
        """Core regression scenario: piece already has a Translation(pl, primary=True).

        After set_primary_translation_pl the property must return the NEW text,
        not the old one from the stale Translation row.
        """
        piece = self._make_piece(db_session)

        # Simulate pre-existing Translation row (as if seeded by migration)
        old_row = Translation(
            music_piece_id=piece.id,
            language="pl",
            is_primary=True,
            kind=TranslationKind.LITERAL,
            text="Stary tekst",
        )
        db_session.add(old_row)
        db_session.commit()

        # Sanity: property reads the old row
        db_session.refresh(piece)
        assert piece.primary_translation_pl == "Stary tekst"

        # Now update via the service
        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Nowy tekst")
        db_session.commit()
        db_session.refresh(piece)

        assert piece.primary_translation_pl == "Nowy tekst"
        assert piece.lyrics_translation_pl == "Nowy tekst"

        primaries = self._primary_pl_rows(db_session, piece.id)
        assert len(primaries) == 1
        assert primaries[0].id == old_row.id  # same row, not a new one

    # ------------------------------------------------------------------
    # Uniqueness: multiple stray primary rows are demoted
    # ------------------------------------------------------------------

    def test_extra_primary_rows_are_demoted(self, db_session):
        """If somehow two rows have is_primary=True the call must fix that."""
        piece = self._make_piece(db_session)

        row1 = Translation(
            music_piece_id=piece.id,
            language="pl",
            is_primary=True,
            kind=TranslationKind.LITERAL,
            text="Row 1",
        )
        row2 = Translation(
            music_piece_id=piece.id,
            language="pl",
            is_primary=True,
            kind=TranslationKind.SINGABLE,
            text="Row 2",
        )
        db_session.add_all([row1, row2])
        db_session.commit()

        # row1 will be found first as 'primary' (first match); row2 must be demoted
        MusicPieceService.set_primary_translation_pl(db_session, piece.id, "Canonical")
        db_session.commit()

        primaries = self._primary_pl_rows(db_session, piece.id)
        assert len(primaries) == 1
        assert primaries[0].text == "Canonical"


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
