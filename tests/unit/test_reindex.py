"""Tests for LibraryService.reindex_from_fs — full upsert + idempotency + regression.

All tests are fully isolated:
- Database: in-memory SQLite via a local ``db_session`` fixture.
- Filesystem: tmp_path / monkeypatched ``CMO_LIBRARY_ROOT`` env var.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import (
    Base,
    KnowledgeCategory,
    KnowledgeNote,
    MusicPiece,
    RightsStatus,
    Source,
    SourceType,
    Translation,
    TranslationKind,
    UsageCategory,
)
from src.services.library_service import LibraryService

# ---------------------------------------------------------------------------
# Shared fixtures
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


def _make_piece(db: Session, title: str = "Test Piece", **kwargs: Any) -> MusicPiece:
    """Create + commit a MusicPiece with sensible defaults."""
    p = MusicPiece(title=title, **kwargs)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _write_yaml(library_root: Path, piece: MusicPiece, extra: dict | None = None) -> Path:
    """Write a minimal piece.yaml for *piece*, then merge *extra* fields."""
    data: dict = {
        "id": piece.id,
        "title": piece.title,
        "slug": piece.slug or LibraryService.slugify(piece.title),
        "composer": piece.composer,
        "difficulty_grade": piece.difficulty_grade,
        "difficulty_notes": piece.difficulty_notes,
        "sources": [],
        "tags": [],
        "usage_categories": [],
    }
    if extra:
        data.update(extra)
    piece_dir = library_root / "pieces" / f"{piece.id:04d}_{data['slug']}"
    piece_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = piece_dir / "piece.yaml"
    with open(yaml_path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, default_flow_style=False)
    return yaml_path


def _ensure_subdirs(piece_dir: Path) -> None:
    for sub in ("sources", "scores", "texts", "knowledge", "derived"):
        (piece_dir / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Baseline: empty library
# ---------------------------------------------------------------------------


class TestReindexEmptyLibrary:
    def test_empty_pieces_dir_returns_zero_summary(self, db_session: Session, library_root: Path):
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary == {
            "scanned": 0,
            "updated": 0,
            "sources": 0,
            "translations": 0,
            "categories": 0,
            "knowledge": 0,
        }

    def test_missing_pieces_dir_returns_zero_summary(self, db_session: Session, library_root: Path):
        # library_root exists but pieces/ does not
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["scanned"] == 0

    def test_orphaned_directory_skipped(self, db_session: Session, library_root: Path):
        """FS dir with no matching DB row must not raise."""
        orphan = library_root / "pieces" / "9999_orphan"
        orphan.mkdir(parents=True)
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["scanned"] == 1
        assert summary["updated"] == 0  # skipped — no DB row


# ---------------------------------------------------------------------------
# Slug + difficulty sync (existing functionality — regression guard)
# ---------------------------------------------------------------------------


class TestReindexSlugAndDifficulty:
    def test_slug_updated_from_directory_name(self, db_session: Session, library_root: Path):
        piece = _make_piece(db_session, title="Ave Maria")
        piece.slug = "old-slug"
        db_session.commit()

        # FS dir has the correct slug
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_ave-maria"
        piece_dir.mkdir(parents=True)

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()  # flush in-memory changes before refreshing from DB
        db_session.refresh(piece)
        assert piece.slug == "ave-maria"

    def test_difficulty_grade_synced_from_yaml(self, db_session: Session, library_root: Path):
        piece = _make_piece(db_session, title="Kyrie", slug="kyrie")
        _write_yaml(library_root, piece, extra={"difficulty_grade": 4})

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()  # flush in-memory changes before refreshing from DB
        db_session.refresh(piece)
        assert piece.difficulty_grade == 4

    def test_title_not_overwritten_from_yaml(self, db_session: Session, library_root: Path):
        """YAML title must NOT overwrite the DB title."""
        piece = _make_piece(db_session, title="DB Title", slug="db-title")
        _write_yaml(library_root, piece, extra={"title": "YAML Title (different)"})

        LibraryService.reindex_from_fs(db_session)
        db_session.refresh(piece)
        assert piece.title == "DB Title"


# ---------------------------------------------------------------------------
# Source upsert
# ---------------------------------------------------------------------------


class TestReindexSources:
    def _setup(self, db_session: Session, library_root: Path) -> MusicPiece:
        piece = _make_piece(db_session, title="Ave Maria", slug="ave-maria")
        _write_yaml(
            library_root,
            piece,
            extra={
                "sources": [
                    {
                        "type": "external_link",
                        "url": "https://musescore.com/example/ave-maria",
                        "label": "MuseScore",
                        "rights_status": "public_domain",
                        "event_name": None,
                        "ensemble": None,
                    }
                ]
            },
        )
        return piece

    def test_source_created_from_yaml(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)

        LibraryService.reindex_from_fs(db_session)

        src = db_session.query(Source).filter_by(music_piece_id=piece.id).first()
        assert src is not None
        assert src.source_type == SourceType.EXTERNAL_LINK
        assert src.url == "https://musescore.com/example/ave-maria"
        assert src.rights_status == RightsStatus.PUBLIC_DOMAIN

    def test_source_reindex_idempotent_no_duplicates(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        count = db_session.query(Source).filter_by(music_piece_id=piece.id).count()
        assert count == 1

    def test_source_summary_counter_incremented(self, db_session: Session, library_root: Path):
        self._setup(db_session, library_root)
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["sources"] >= 1

    def test_existing_source_not_duplicated_after_delete_and_reindex(
        self, db_session: Session, library_root: Path
    ):
        """Round-trip: delete Source row, reindex restores it from YAML."""
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        # Delete the row from SQLite
        db_session.query(Source).filter_by(music_piece_id=piece.id).delete()
        db_session.commit()
        assert db_session.query(Source).filter_by(music_piece_id=piece.id).count() == 0

        # Reindex restores it
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        assert db_session.query(Source).filter_by(music_piece_id=piece.id).count() == 1

    def test_unknown_source_type_is_skipped(self, db_session: Session, library_root: Path):
        piece = _make_piece(db_session, title="Test", slug="test")
        _write_yaml(
            library_root,
            piece,
            extra={"sources": [{"type": "nonexistent_type", "url": None}]},
        )
        # Must not raise
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["sources"] == 0


# ---------------------------------------------------------------------------
# Translation upsert
# ---------------------------------------------------------------------------


class TestReindexTranslations:
    def _setup(
        self, db_session: Session, library_root: Path, translation_text: str = "Pełna łaski"
    ) -> MusicPiece:
        piece = _make_piece(db_session, title="Ave Maria", slug="ave-maria")
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_ave-maria"
        _write_yaml(library_root, piece)
        _ensure_subdirs(piece_dir)
        (piece_dir / "texts" / "translation_pl_literal.md").write_text(
            translation_text, encoding="utf-8"
        )
        return piece

    def test_translation_created_from_file(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)

        LibraryService.reindex_from_fs(db_session)

        tr = (
            db_session.query(Translation)
            .filter_by(
                music_piece_id=piece.id,
                language="pl",
                kind=TranslationKind.LITERAL,
            )
            .first()
        )
        assert tr is not None
        assert tr.text == "Pełna łaski"

    def test_translation_is_primary_when_first(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)

        tr = db_session.query(Translation).filter_by(music_piece_id=piece.id, language="pl").first()
        assert tr.is_primary is True

    def test_translation_reindex_idempotent_no_duplicates(
        self, db_session: Session, library_root: Path
    ):
        piece = self._setup(db_session, library_root)

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        count = db_session.query(Translation).filter_by(music_piece_id=piece.id).count()
        assert count == 1

    def test_translation_text_updated_when_file_changes(
        self, db_session: Session, library_root: Path
    ):
        piece = self._setup(db_session, library_root, "Tekst oryginalny")
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        # Modify the file
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_ave-maria"
        (piece_dir / "texts" / "translation_pl_literal.md").write_text(
            "Tekst zaktualizowany", encoding="utf-8"
        )
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        tr = (
            db_session.query(Translation)
            .filter_by(music_piece_id=piece.id, language="pl", kind=TranslationKind.LITERAL)
            .first()
        )
        assert tr.text == "Tekst zaktualizowany"
        # Still exactly one row
        assert db_session.query(Translation).filter_by(music_piece_id=piece.id).count() == 1

    def test_round_trip_delete_and_reindex(self, db_session: Session, library_root: Path):
        """Delete Translation row, reindex must restore it from FS."""
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        db_session.query(Translation).filter_by(music_piece_id=piece.id).delete()
        db_session.commit()
        assert db_session.query(Translation).filter_by(music_piece_id=piece.id).count() == 0

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        assert db_session.query(Translation).filter_by(music_piece_id=piece.id).count() == 1

    def test_summary_translations_counter(self, db_session: Session, library_root: Path):
        self._setup(db_session, library_root)
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["translations"] == 1

    def test_unknown_kind_skipped(self, db_session: Session, library_root: Path):
        piece = _make_piece(db_session, title="Test", slug="test")
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_test"
        _write_yaml(library_root, piece)
        _ensure_subdirs(piece_dir)
        (piece_dir / "texts" / "translation_pl_badkind.md").write_text(
            "some text", encoding="utf-8"
        )
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["translations"] == 0

    def test_multiple_languages_all_created(self, db_session: Session, library_root: Path):
        piece = _make_piece(db_session, title="Hallelujah", slug="hallelujah")
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_hallelujah"
        _write_yaml(library_root, piece)
        _ensure_subdirs(piece_dir)
        (piece_dir / "texts" / "translation_pl_literal.md").write_text("Alleluja", encoding="utf-8")
        (piece_dir / "texts" / "translation_en_singable.md").write_text(
            "Praise the Lord", encoding="utf-8"
        )

        LibraryService.reindex_from_fs(db_session)

        count = db_session.query(Translation).filter_by(music_piece_id=piece.id).count()
        assert count == 2
        assert (
            db_session.query(Translation).filter_by(music_piece_id=piece.id, language="pl").count()
            == 1
        )
        assert (
            db_session.query(Translation).filter_by(music_piece_id=piece.id, language="en").count()
            == 1
        )


# ---------------------------------------------------------------------------
# UsageCategory upsert (M2M)
# ---------------------------------------------------------------------------


class TestReindexUsageCategories:
    def _setup(self, db_session: Session, library_root: Path) -> MusicPiece:
        piece = _make_piece(db_session, title="Komunia", slug="komunia")
        _write_yaml(library_root, piece, extra={"usage_categories": ["Komunia", "Uwielbienie"]})
        return piece

    def test_categories_linked_to_piece(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        db_session.refresh(piece)

        names = {uc.name for uc in piece.usage_categories}
        assert "Komunia" in names
        assert "Uwielbienie" in names

    def test_category_rows_created_in_table(self, db_session: Session, library_root: Path):
        self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        assert db_session.query(UsageCategory).filter_by(name="Komunia").count() == 1
        assert db_session.query(UsageCategory).filter_by(name="Uwielbienie").count() == 1

    def test_category_reindex_idempotent(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        db_session.refresh(piece)
        assert len(piece.usage_categories) == 2
        # Global table must not have duplicates either
        assert db_session.query(UsageCategory).filter_by(name="Komunia").count() == 1

    def test_round_trip_delete_links_and_reindex(self, db_session: Session, library_root: Path):
        """Delete M2M links, reindex must restore them from YAML."""
        from src.database.models import PieceUsageCategory

        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        db_session.query(PieceUsageCategory).filter_by(music_piece_id=piece.id).delete()
        db_session.commit()
        db_session.refresh(piece)
        assert len(piece.usage_categories) == 0

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        db_session.refresh(piece)
        assert len(piece.usage_categories) == 2

    def test_summary_categories_counter(self, db_session: Session, library_root: Path):
        self._setup(db_session, library_root)
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["categories"] == 2

    def test_shared_category_not_duplicated_across_pieces(
        self, db_session: Session, library_root: Path
    ):
        piece1 = _make_piece(db_session, title="Piece 1", slug="piece-1")
        piece2 = _make_piece(db_session, title="Piece 2", slug="piece-2")
        _write_yaml(library_root, piece1, extra={"usage_categories": ["Shared"]})
        _write_yaml(library_root, piece2, extra={"usage_categories": ["Shared"]})

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        # Only one UsageCategory row for "Shared"
        assert db_session.query(UsageCategory).filter_by(name="Shared").count() == 1


# ---------------------------------------------------------------------------
# KnowledgeNote upsert
# ---------------------------------------------------------------------------


class TestReindexKnowledgeNotes:
    def _setup(self, db_session: Session, library_root: Path) -> MusicPiece:
        piece = _make_piece(db_session, title="Ave Maria", slug="ave-maria")
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_ave-maria"
        _write_yaml(library_root, piece)
        _ensure_subdirs(piece_dir)
        (piece_dir / "knowledge" / "historical_historia-utworu.md").write_text(
            "# Historia utworu\n\nUtwór pochodzi z XVI wieku.", encoding="utf-8"
        )
        return piece

    def test_knowledge_note_created(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)

        note = db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).first()
        assert note is not None
        assert note.title == "Historia utworu"
        assert note.category == KnowledgeCategory.HISTORICAL
        assert "XVI" in note.body_md

    def test_knowledge_note_reindex_idempotent(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        count = db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).count()
        assert count == 1

    def test_knowledge_note_body_updated_when_file_changes(
        self, db_session: Session, library_root: Path
    ):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        piece_dir = library_root / "pieces" / f"{piece.id:04d}_ave-maria"
        (piece_dir / "knowledge" / "historical_historia-utworu.md").write_text(
            "# Historia utworu\n\nZaktualizowana treść.", encoding="utf-8"
        )
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        note = db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).first()
        assert "Zaktualizowana" in note.body_md
        assert db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).count() == 1

    def test_round_trip_delete_and_reindex(self, db_session: Session, library_root: Path):
        piece = self._setup(db_session, library_root)
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).delete()
        db_session.commit()
        assert db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).count() == 0

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        assert db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).count() == 1

    def test_summary_knowledge_counter(self, db_session: Session, library_root: Path):
        self._setup(db_session, library_root)
        summary = LibraryService.reindex_from_fs(db_session)
        assert summary["knowledge"] == 1

    def test_note_without_title_header(self, db_session: Session, library_root: Path):
        """A knowledge file without a # header line is stored with title=None."""
        piece = _make_piece(db_session, title="Test", slug="test")
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_test"
        _write_yaml(library_root, piece)
        _ensure_subdirs(piece_dir)
        (piece_dir / "knowledge" / "general_raw-note.md").write_text(
            "Just some raw text, no heading.", encoding="utf-8"
        )

        LibraryService.reindex_from_fs(db_session)

        note = db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).first()
        assert note is not None
        assert note.title is None
        assert "raw text" in note.body_md

    def test_write_knowledge_then_reindex_round_trip(self, db_session: Session, library_root: Path):
        """Full round-trip using the real write_knowledge helper."""
        from src.database.models import KnowledgeNote as KNModel

        piece = _make_piece(db_session, title="Psalm 23", slug="psalm-23")
        _write_yaml(library_root, piece)

        note_obj = KNModel(
            music_piece_id=piece.id,
            category=KnowledgeCategory.PERFORMANCE,
            title="Wskazówki wykonawcze",
            body_md="Tempo umiarkowane, dynamika p–mf.",
        )
        db_session.add(note_obj)
        db_session.commit()

        LibraryService.write_knowledge(piece, note_obj)

        # Delete DB row and reindex from FS
        db_session.delete(note_obj)
        db_session.commit()
        assert db_session.query(KNModel).filter_by(music_piece_id=piece.id).count() == 0

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        restored = db_session.query(KNModel).filter_by(music_piece_id=piece.id).first()
        assert restored is not None
        assert restored.title == "Wskazówki wykonawcze"
        assert restored.category == KnowledgeCategory.PERFORMANCE
        assert "Tempo" in restored.body_md


# ---------------------------------------------------------------------------
# Full round-trip test (all entities at once)
# ---------------------------------------------------------------------------


class TestReindexFullRoundTrip:
    def test_full_round_trip_all_entities(self, db_session: Session, library_root: Path):
        """Create a piece with all entity types, delete them, reindex, verify restored."""
        piece = _make_piece(
            db_session,
            title="Gloria",
            slug="gloria",
            difficulty_grade=3,
            difficulty_notes="SATB required",
        )
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_gloria"
        _ensure_subdirs(piece_dir)

        # Write YAML with sources + categories
        _write_yaml(
            library_root,
            piece,
            extra={
                "sources": [
                    {
                        "type": "external_link",
                        "url": "https://cpdl.org/gloria",
                        "label": "CPDL",
                        "rights_status": "public_domain",
                        "event_name": None,
                        "ensemble": None,
                    }
                ],
                "usage_categories": ["Chwała", "Msza"],
            },
        )

        # Write translation file
        (piece_dir / "texts" / "translation_pl_literal.md").write_text(
            "Chwała na wysokościach Bogu", encoding="utf-8"
        )

        # Write knowledge note
        (piece_dir / "knowledge" / "historical_historia.md").write_text(
            "# Historia\n\nUtwór z XVIII w.", encoding="utf-8"
        )

        # First reindex — creates everything
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        # Delete all related rows
        db_session.query(Source).filter_by(music_piece_id=piece.id).delete()
        db_session.query(Translation).filter_by(music_piece_id=piece.id).delete()
        db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).delete()
        from src.database.models import PieceUsageCategory

        db_session.query(PieceUsageCategory).filter_by(music_piece_id=piece.id).delete()
        db_session.commit()

        # Second reindex — must restore all
        summary = LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        assert db_session.query(Source).filter_by(music_piece_id=piece.id).count() == 1
        assert db_session.query(Translation).filter_by(music_piece_id=piece.id).count() == 1
        assert db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).count() == 1
        db_session.refresh(piece)
        assert len(piece.usage_categories) == 2
        assert summary["sources"] >= 1
        assert summary["translations"] >= 1
        assert summary["categories"] >= 2
        assert summary["knowledge"] >= 1

    def test_double_reindex_no_duplicates_any_entity(self, db_session: Session, library_root: Path):
        """Two consecutive reindexes produce the same state — no duplicates anywhere."""
        piece = _make_piece(db_session, title="Kyrie", slug="kyrie")
        piece_dir = library_root / "pieces" / f"{piece.id:04d}_kyrie"
        _ensure_subdirs(piece_dir)

        _write_yaml(
            library_root,
            piece,
            extra={
                "sources": [
                    {
                        "type": "local_upload",
                        "url": None,
                        "label": "oryginał",
                        "rights_status": "unknown",
                        "event_name": None,
                        "ensemble": None,
                    }
                ],
                "usage_categories": ["Msza"],
            },
        )
        (piece_dir / "texts" / "translation_en_singable.md").write_text(
            "Lord have mercy", encoding="utf-8"
        )
        (piece_dir / "knowledge" / "stylistic_styl.md").write_text(
            "# Styl\n\nPolifonia.", encoding="utf-8"
        )

        LibraryService.reindex_from_fs(db_session)
        db_session.commit()
        LibraryService.reindex_from_fs(db_session)
        db_session.commit()

        assert db_session.query(Source).filter_by(music_piece_id=piece.id).count() == 1
        assert db_session.query(Translation).filter_by(music_piece_id=piece.id).count() == 1
        assert db_session.query(KnowledgeNote).filter_by(music_piece_id=piece.id).count() == 1
        db_session.refresh(piece)
        assert len(piece.usage_categories) == 1


# ---------------------------------------------------------------------------
# Regression: primary_translation_pl stale-flush fix (WAŻNE-2)
# ---------------------------------------------------------------------------


class TestPrimaryTranslationPlStale:
    """Verify that primary_translation_pl reflects the live session state after flush."""

    def test_returns_fresh_value_after_flush_without_refresh(self, db_session: Session):
        """Core regression: adding Translation + flush → property returns new text immediately.

        The property must NOT require an explicit db_session.refresh(piece) call to see
        the newly flushed row.
        """
        piece = MusicPiece(title="Test")
        db_session.add(piece)
        db_session.commit()

        # Access translations to warm/load the (empty) collection
        _ = piece.translations  # noqa: F841  — force load of empty list

        # Now add a Translation without refreshing piece
        tr = Translation(
            music_piece_id=piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Fresh text from flush",
            is_primary=True,
        )
        db_session.add(tr)
        db_session.flush()  # NOT commit, NOT refresh(piece)

        # Property must see the row despite the stale in-memory collection
        result = piece.primary_translation_pl
        assert result == "Fresh text from flush"

    def test_returns_fresh_value_after_text_update_without_refresh(self, db_session: Session):
        """Updating an existing Translation text → property returns updated value after flush."""
        piece = MusicPiece(title="Test")
        db_session.add(piece)
        db_session.commit()

        tr = Translation(
            music_piece_id=piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Original",
            is_primary=True,
        )
        db_session.add(tr)
        db_session.commit()

        # Update without refreshing piece
        tr.text = "Updated"
        db_session.flush()

        assert piece.primary_translation_pl == "Updated"

    def test_fallback_to_legacy_column_when_no_translation_rows(self, db_session: Session):
        """No Translation rows → legacy column returned."""
        piece = MusicPiece(title="Test", lyrics_translation_pl="Legacy")
        db_session.add(piece)
        db_session.commit()

        assert piece.primary_translation_pl == "Legacy"

    def test_newest_non_primary_returned_via_session(self, db_session: Session):
        """Two non-primary rows → newest by created_at is returned via session query."""
        from datetime import datetime

        piece = MusicPiece(title="Test")
        db_session.add(piece)
        db_session.commit()

        older = Translation(
            music_piece_id=piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Older",
            is_primary=False,
            created_at=datetime(2024, 1, 1),
        )
        newer = Translation(
            music_piece_id=piece.id,
            language="pl",
            kind=TranslationKind.SINGABLE,
            text="Newer",
            is_primary=False,
            created_at=datetime(2025, 6, 1),
        )
        db_session.add_all([older, newer])
        db_session.flush()

        assert piece.primary_translation_pl == "Newer"

    def test_detached_instance_uses_loaded_collection(self):
        """Transient instance (never in a session) uses in-memory collection."""
        # Build a transient piece — object_session(piece) returns None
        piece = MusicPiece(title="Detached Test")
        tr = Translation(
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Detached text",
            is_primary=True,
        )
        # Append to the in-memory collection (valid for transient instances)
        piece.translations.append(tr)

        # Property must use the else-branch (no session) and read the collection
        assert piece.primary_translation_pl == "Detached text"
