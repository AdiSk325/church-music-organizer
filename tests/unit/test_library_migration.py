"""Tests for LibraryService, new ORM models, and the migrate_to_library script.

All tests are fully isolated:
- Database: in-memory SQLite via a local ``db_session`` fixture.
- Filesystem: tmp_path / monkeypatched ``CMO_LIBRARY_ROOT`` env var.
- No real church_music.db or data/uploads/ is touched.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import (
    Base,
    FileType,
    KnowledgeCategory,
    KnowledgeNote,
    MusicFile,
    MusicFileKind,
    MusicPiece,
    RightsStatus,
    Source,
    SourceType,
    Tag,
    Translation,
    TranslationKind,
    UsageCategory,
)
from src.services.library_service import LibraryService

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
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
def sample_piece(db_session: Session) -> MusicPiece:
    piece = MusicPiece(
        title="Ave Maria",
        composer="Franz Schubert",
        lyrics="Gratia plena",
        lyrics_translation_pl="Pełna łaski",
        musescore_link="https://musescore.com/example/ave-maria",
    )
    db_session.add(piece)
    db_session.commit()
    return piece


# ---------------------------------------------------------------------------
# ZADANIE B-1  slugify: polskie znaki, format, edge cases
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_polish_a_ogonek(self):
        assert LibraryService.slugify("ąbc") == "abc"

    def test_polish_c_accent(self):
        assert LibraryService.slugify("ćma") == "cma"

    def test_polish_e_ogonek(self):
        assert LibraryService.slugify("ęcho") == "echo"

    def test_polish_l_stroke(self):
        assert LibraryService.slugify("łódź") == "lodz"

    def test_polish_n_accent(self):
        assert LibraryService.slugify("koń") == "kon"

    def test_polish_o_accent(self):
        assert LibraryService.slugify("ósmy") == "osmy"

    def test_polish_s_accent(self):
        assert LibraryService.slugify("śpiew") == "spiew"

    def test_polish_z_dot(self):
        assert LibraryService.slugify("żaba") == "zaba"

    def test_polish_z_accent(self):
        assert LibraryService.slugify("źródło") == "zrodlo"

    def test_full_polish_phrase(self):
        result = LibraryService.slugify("Chwała na wysokości")
        assert result == "chwala-na-wysokosci"

    def test_em_dash_collapsed_to_hyphen(self):
        result = LibraryService.slugify("Alleluja – Śpiewnik")
        assert result == "alleluja-spiewnik"

    def test_spaces_become_hyphens(self):
        assert LibraryService.slugify("Ave Maria") == "ave-maria"

    def test_consecutive_hyphens_collapsed(self):
        result = LibraryService.slugify("a  b")  # double space → single hyphen
        assert result == "a-b"

    def test_leading_trailing_hyphens_stripped(self):
        result = LibraryService.slugify("  leading  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_string_returns_utwor(self):
        assert LibraryService.slugify("") == "utwor"

    def test_whitespace_only_returns_utwor(self):
        assert LibraryService.slugify("   ") == "utwor"

    def test_result_is_lowercase(self):
        result = LibraryService.slugify("Gloria In Excelsis")
        assert result == result.lower()

    def test_result_is_ascii(self):
        result = LibraryService.slugify("Chwała Tobie Słowo Boże")
        result.encode("ascii")  # must not raise

    def test_numbers_preserved(self):
        assert LibraryService.slugify("Psalm 23") == "psalm-23"


# ---------------------------------------------------------------------------
# ZADANIE B-2  round-trip: write_piece_yaml → read_piece_yaml
# ---------------------------------------------------------------------------


class TestWriteReadPieceYaml:
    def test_round_trip_basic_fields(
        self, db_session: Session, library_root: Path, sample_piece: MusicPiece
    ):
        sample_piece.slug = LibraryService.slugify(sample_piece.title)
        db_session.commit()

        yaml_path = LibraryService.write_piece_yaml(sample_piece)
        data = LibraryService.read_piece_yaml(yaml_path)

        assert data["id"] == sample_piece.id
        assert data["title"] == "Ave Maria"
        assert data["composer"] == "Franz Schubert"
        assert data["slug"] == "ave-maria"

    def test_round_trip_difficulty_fields(self, db_session: Session, library_root: Path):
        piece = MusicPiece(title="Kyrie", difficulty_grade=3, difficulty_notes="Wymaga SATB")
        piece.slug = "kyrie"
        db_session.add(piece)
        db_session.commit()

        yaml_path = LibraryService.write_piece_yaml(piece)
        data = LibraryService.read_piece_yaml(yaml_path)

        assert data["difficulty_grade"] == 3
        assert data["difficulty_notes"] == "Wymaga SATB"

    def test_round_trip_sources_in_yaml(
        self, db_session: Session, library_root: Path, sample_piece: MusicPiece
    ):
        sample_piece.slug = "ave-maria"
        src = Source(
            music_piece_id=sample_piece.id,
            source_type=SourceType.EXTERNAL_LINK,
            url="https://musescore.com/example",
            rights_status=RightsStatus.PUBLIC_DOMAIN,
        )
        db_session.add(src)
        db_session.commit()
        db_session.refresh(sample_piece)

        yaml_path = LibraryService.write_piece_yaml(sample_piece)
        data = LibraryService.read_piece_yaml(yaml_path)

        assert len(data["sources"]) == 1
        assert data["sources"][0]["url"] == "https://musescore.com/example"
        assert data["sources"][0]["rights_status"] == "public_domain"

    def test_round_trip_tags_in_yaml(
        self, db_session: Session, library_root: Path, sample_piece: MusicPiece
    ):
        sample_piece.slug = "ave-maria"
        tag = Tag(name="liturgia")
        sample_piece.tags.append(tag)
        db_session.commit()
        db_session.refresh(sample_piece)

        yaml_path = LibraryService.write_piece_yaml(sample_piece)
        data = LibraryService.read_piece_yaml(yaml_path)

        assert "liturgia" in data["tags"]

    def test_yaml_file_exists_at_correct_path(
        self, db_session: Session, library_root: Path, sample_piece: MusicPiece
    ):
        sample_piece.slug = "ave-maria"
        db_session.commit()

        yaml_path = LibraryService.write_piece_yaml(sample_piece)
        assert yaml_path.exists()
        assert yaml_path.name == "piece.yaml"
        assert library_root.name in str(yaml_path)

    def test_piece_dir_creates_subdirectories(
        self, db_session: Session, library_root: Path, sample_piece: MusicPiece
    ):
        sample_piece.slug = "ave-maria"
        db_session.commit()

        piece_dir = LibraryService.piece_dir(sample_piece)
        for subdir in ("sources", "scores", "texts", "knowledge", "derived"):
            assert (piece_dir / subdir).is_dir(), f"Missing subdir: {subdir}"

    def test_read_nonexistent_yaml_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            LibraryService.read_piece_yaml(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# ZADANIE B-3  Modele: Source, Translation, UsageCategory, KnowledgeNote
# ---------------------------------------------------------------------------


class TestNewModels:
    def test_create_source_external_link(self, db_session: Session, sample_piece: MusicPiece):
        src = Source(
            music_piece_id=sample_piece.id,
            source_type=SourceType.EXTERNAL_LINK,
            url="https://example.com",
            rights_status=RightsStatus.UNKNOWN,
        )
        db_session.add(src)
        db_session.commit()

        fetched = db_session.query(Source).filter_by(music_piece_id=sample_piece.id).first()
        assert fetched is not None
        assert fetched.source_type == SourceType.EXTERNAL_LINK
        assert fetched.url == "https://example.com"

    def test_create_translation(self, db_session: Session, sample_piece: MusicPiece):
        tr = Translation(
            music_piece_id=sample_piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Pełna łaski",
            source="gemini",
            is_primary=True,
        )
        db_session.add(tr)
        db_session.commit()

        fetched = db_session.query(Translation).filter_by(music_piece_id=sample_piece.id).first()
        assert fetched is not None
        assert fetched.language == "pl"
        assert fetched.kind == TranslationKind.LITERAL
        assert fetched.is_primary is True

    def test_primary_translation_pl_property_returns_primary(
        self, db_session: Session, sample_piece: MusicPiece
    ):
        tr = Translation(
            music_piece_id=sample_piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Pełna łaski (primary)",
            source="gemini",
            is_primary=True,
        )
        db_session.add(tr)
        db_session.commit()
        db_session.refresh(sample_piece)

        assert sample_piece.primary_translation_pl == "Pełna łaski (primary)"

    def test_primary_translation_pl_property_falls_back_to_legacy_column(self, db_session: Session):
        """When no Translation rows exist, the legacy column is returned."""
        piece = MusicPiece(title="Test", lyrics_translation_pl="Legacy translation")
        db_session.add(piece)
        db_session.commit()

        assert piece.primary_translation_pl == "Legacy translation"

    def test_primary_translation_pl_newest_non_primary_fallback(
        self, db_session: Session, sample_piece: MusicPiece
    ):
        """When no is_primary row, returns the newest pl translation."""
        older = Translation(
            music_piece_id=sample_piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Older",
            is_primary=False,
            created_at=datetime(2024, 1, 1),
        )
        newer = Translation(
            music_piece_id=sample_piece.id,
            language="pl",
            kind=TranslationKind.SINGABLE,
            text="Newer",
            is_primary=False,
            created_at=datetime(2025, 1, 1),
        )
        db_session.add_all([older, newer])
        db_session.commit()
        db_session.refresh(sample_piece)

        assert sample_piece.primary_translation_pl == "Newer"

    def test_create_usage_category_and_assign(self, db_session: Session, sample_piece: MusicPiece):
        cat = UsageCategory(name="Komunia", description="Pieśni na komunię")
        sample_piece.usage_categories.append(cat)
        db_session.add(cat)
        db_session.commit()
        db_session.refresh(sample_piece)

        assert any(uc.name == "Komunia" for uc in sample_piece.usage_categories)

    def test_usage_category_shared_between_pieces(self, db_session: Session):
        cat = UsageCategory(name="Uwielbienie")
        piece1 = MusicPiece(title="Piece 1")
        piece2 = MusicPiece(title="Piece 2")
        piece1.usage_categories.append(cat)
        piece2.usage_categories.append(cat)
        db_session.add_all([piece1, piece2])
        db_session.commit()

        assert db_session.query(UsageCategory).count() == 1
        db_session.refresh(cat)
        assert len(cat.music_pieces) == 2

    def test_create_knowledge_note(self, db_session: Session, sample_piece: MusicPiece):
        note = KnowledgeNote(
            music_piece_id=sample_piece.id,
            category=KnowledgeCategory.HISTORICAL,
            title="Historia utworu",
            body_md="Utwór pochodzi z XVI wieku.",
        )
        db_session.add(note)
        db_session.commit()

        fetched = db_session.query(KnowledgeNote).filter_by(music_piece_id=sample_piece.id).first()
        assert fetched is not None
        assert fetched.category == KnowledgeCategory.HISTORICAL
        assert fetched.body_md == "Utwór pochodzi z XVI wieku."

    def test_cascade_delete_removes_source(self, db_session: Session, sample_piece: MusicPiece):
        src = Source(
            music_piece_id=sample_piece.id,
            source_type=SourceType.LOCAL_UPLOAD,
            rights_status=RightsStatus.UNKNOWN,
        )
        db_session.add(src)
        db_session.commit()

        assert db_session.query(Source).count() == 1

        db_session.delete(sample_piece)
        db_session.commit()

        assert db_session.query(Source).count() == 0

    def test_cascade_delete_removes_translation(
        self, db_session: Session, sample_piece: MusicPiece
    ):
        tr = Translation(
            music_piece_id=sample_piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            text="Test",
            is_primary=True,
        )
        db_session.add(tr)
        db_session.commit()

        db_session.delete(sample_piece)
        db_session.commit()

        assert db_session.query(Translation).count() == 0

    def test_cascade_delete_removes_knowledge_note(
        self, db_session: Session, sample_piece: MusicPiece
    ):
        note = KnowledgeNote(
            music_piece_id=sample_piece.id,
            category=KnowledgeCategory.GENERAL,
            body_md="Some note.",
        )
        db_session.add(note)
        db_session.commit()

        db_session.delete(sample_piece)
        db_session.commit()

        assert db_session.query(KnowledgeNote).count() == 0

    def test_usage_category_not_cascade_deleted_with_piece(self, db_session: Session):
        """UsageCategory is shared — must NOT be deleted when a piece is deleted."""
        cat = UsageCategory(name="Procesja")
        piece = MusicPiece(title="Piece to delete")
        piece.usage_categories.append(cat)
        db_session.add_all([cat, piece])
        db_session.commit()

        db_session.delete(piece)
        db_session.commit()

        assert db_session.query(UsageCategory).filter_by(name="Procesja").count() == 1

    def test_new_music_file_kind_field(self, db_session: Session, sample_piece: MusicPiece):
        mf = MusicFile(
            music_piece_id=sample_piece.id,
            file_path="/tmp/score.mscz",
            file_type=FileType.MUSESCORE,
            kind=MusicFileKind.EDITABLE,
            opens_externally=True,
        )
        db_session.add(mf)
        db_session.commit()
        db_session.refresh(mf)

        assert mf.kind == MusicFileKind.EDITABLE
        assert mf.opens_externally is True


# ---------------------------------------------------------------------------
# ZADANIE B-4  Migracja: dry-run + apply na tymczasowej bazie
# ---------------------------------------------------------------------------


def _make_in_memory_session() -> Session:
    """Return a fresh in-memory SQLite session with the full schema."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_db_with_uploads(db: Session, uploads_dir: Path) -> tuple[MusicPiece, MusicPiece]:
    """Seed the session with two pieces and actual files on disk."""
    piece1 = MusicPiece(
        title="Alleluja Wielkanocne",
        lyrics="Alleluia, alleluia",
        lyrics_translation_pl="Alleluja (tłumaczenie)",
        musescore_link="https://musescore.com/example/alleluja",
    )
    piece2 = MusicPiece(
        title="Kyrie Eleison",
        lyrics="",
        lyrics_translation_pl="",
        musescore_link="",
    )
    db.add_all([piece1, piece2])
    db.flush()

    # Create physical files in uploads/{id}/
    p1_dir = uploads_dir / str(piece1.id)
    p1_dir.mkdir(parents=True)
    (p1_dir / "scan.pdf").write_bytes(b"%PDF-fake")
    (p1_dir / "final_score.xml").write_bytes(b"<score/>")

    p2_dir = uploads_dir / str(piece2.id)
    p2_dir.mkdir(parents=True)
    (p2_dir / "corrected_score.xml").write_bytes(b"<score/>")

    mf1 = MusicFile(
        music_piece_id=piece1.id,
        file_path=str(p1_dir / "scan.pdf"),
        file_type=FileType.PDF,
    )
    mf2 = MusicFile(
        music_piece_id=piece1.id,
        file_path=str(p1_dir / "final_score.xml"),
        file_type=FileType.XML,
    )
    mf3 = MusicFile(
        music_piece_id=piece2.id,
        file_path=str(p2_dir / "corrected_score.xml"),
        file_type=FileType.XML,
    )
    db.add_all([mf1, mf2, mf3])
    db.commit()
    return piece1, piece2


class TestMigrationDryRun:
    """Import run_migration directly and call with dry_run=True."""

    def test_dry_run_creates_no_translations(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        summary = run_migration(db, uploads_dir, dry_run=True)
        db.rollback()

        assert db.query(Translation).count() == 0
        assert summary["translations_created"] == 1  # would be created for piece1

    def test_dry_run_creates_no_sources(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=True)
        db.rollback()

        assert db.query(Source).count() == 0

    def test_dry_run_does_not_move_files(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        original_paths = [mf.file_path for mf in piece1.files]
        run_migration(db, uploads_dir, dry_run=True)
        db.rollback()
        db.refresh(piece1)

        for mf in piece1.files:
            assert mf.file_path in original_paths, "file_path changed during dry-run"
            assert Path(mf.file_path).exists(), "file was moved during dry-run"

    def test_dry_run_returns_correct_counts(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        _seed_db_with_uploads(db, uploads_dir)

        summary = run_migration(db, uploads_dir, dry_run=True)
        db.rollback()

        assert summary["pieces"] == 2
        assert summary["files_moved"] == 3  # all three files exist on disk
        assert summary["translations_created"] == 1  # only piece1 has translation
        assert summary["sources_created"] == 1  # only piece1 has musescore_link

    def test_dry_run_does_not_write_yaml(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=True)
        db.rollback()

        # piece.yaml must NOT be written even if directories are created for path-computation
        yaml_files = list(library_root.rglob("piece.yaml"))
        assert yaml_files == [], f"piece.yaml should not be written in dry-run: {yaml_files}"


class TestMigrationApply:
    """Apply migration on isolated tmp data and verify the outcome."""

    def test_apply_moves_files_to_correct_subdirs(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, piece2 = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()
        db.refresh(piece1)
        db.refresh(piece2)

        # scan.pdf → sources/
        source_files = [mf for mf in piece1.files if "scan.pdf" in mf.file_path]
        assert len(source_files) == 1
        assert "sources" in source_files[0].file_path

        # final_score.xml → scores/ (FINAL kind)
        final_files = [mf for mf in piece1.files if "final_score.xml" in mf.file_path]
        assert len(final_files) == 1
        assert "scores" in final_files[0].file_path

        # corrected_score.xml → scores/ (CORRECTED kind)
        corrected_files = [mf for mf in piece2.files if "corrected_score.xml" in mf.file_path]
        assert len(corrected_files) == 1
        assert "scores" in corrected_files[0].file_path

    def test_apply_creates_translation_row(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()

        translations = (
            db.query(Translation)
            .filter_by(music_piece_id=piece1.id, language="pl", is_primary=True)
            .all()
        )
        assert len(translations) == 1
        assert "Alleluja" in translations[0].text

    def test_apply_creates_source_row(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()

        sources = (
            db.query(Source)
            .filter_by(music_piece_id=piece1.id, source_type=SourceType.EXTERNAL_LINK)
            .all()
        )
        assert len(sources) == 1
        assert "alleluja" in sources[0].url

    def test_apply_sets_kind_and_opens_externally(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()
        db.refresh(piece1)

        for mf in piece1.files:
            assert mf.kind is not None, f"kind not set for {mf.file_path}"
        editable_files = [mf for mf in piece1.files if mf.kind == MusicFileKind.FINAL]
        assert all(mf.opens_externally for mf in editable_files)

    def test_apply_idempotent_no_duplicate_translations(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()
        # Run again — must not duplicate
        run_migration(db, uploads_dir, dry_run=False)
        db.commit()

        count = (
            db.query(Translation)
            .filter_by(music_piece_id=piece1.id, language="pl", is_primary=True)
            .count()
        )
        assert count == 1

    def test_apply_idempotent_no_duplicate_sources(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()
        run_migration(db, uploads_dir, dry_run=False)
        db.commit()

        count = (
            db.query(Source)
            .filter_by(music_piece_id=piece1.id, source_type=SourceType.EXTERNAL_LINK)
            .count()
        )
        assert count == 1

    def test_apply_writes_piece_yaml(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()

        pieces_dir = library_root / "pieces"
        yaml_files = list(pieces_dir.rglob("piece.yaml"))
        assert len(yaml_files) >= 1

    def test_apply_writes_lyrics_md(self, tmp_path: Path, library_root: Path):
        from scripts.migrate_to_library import run_migration

        uploads_dir = tmp_path / "uploads"
        db = _make_in_memory_session()
        piece1, _ = _seed_db_with_uploads(db, uploads_dir)

        run_migration(db, uploads_dir, dry_run=False)
        db.commit()
        db.refresh(piece1)

        piece_dir = LibraryService.piece_dir(piece1)
        lyrics_md = piece_dir / "texts" / "lyrics.md"
        assert lyrics_md.exists()
        assert "Alleluia" in lyrics_md.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ZADANIE B-4 extra  Kind detection helper
# ---------------------------------------------------------------------------


class TestDetectKind:
    def _make_file(self, path: str, file_type: FileType, description: str = "") -> Any:
        """Return a duck-type stub acceptable to _detect_kind (no SQLAlchemy session needed)."""
        import types

        mf = types.SimpleNamespace()
        mf.file_path = path
        mf.file_type = file_type
        mf.description = description
        return mf

    def test_final_prefix_detected(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/final_score.xml", FileType.XML)
        assert _detect_kind(mf) == MusicFileKind.FINAL

    def test_corrected_prefix_detected(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/corrected_score.xml", FileType.XML)
        assert _detect_kind(mf) == MusicFileKind.CORRECTED

    def test_referencja_description_detected(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/ref.pdf", FileType.PDF, "[REFERENCJA] opis")
        assert _detect_kind(mf) == MusicFileKind.REFERENCE

    def test_mscz_extension_detected_as_editable(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/score.mscz", FileType.MUSESCORE)
        assert _detect_kind(mf) == MusicFileKind.EDITABLE

    def test_mscx_extension_detected_as_editable(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/score.mscx", FileType.MUSESCORE)
        assert _detect_kind(mf) == MusicFileKind.EDITABLE

    def test_pdf_filetype_detected_as_source_pdf(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/scan.pdf", FileType.PDF)
        assert _detect_kind(mf) == MusicFileKind.SOURCE_PDF

    def test_scan_filetype_detected_as_source_scan(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/img.png", FileType.SCAN)
        assert _detect_kind(mf) == MusicFileKind.SOURCE_SCAN

    def test_xml_extension_without_prefix_detected_as_omr_raw(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/raw_output.xml", FileType.XML)
        assert _detect_kind(mf) == MusicFileKind.OMR_RAW

    def test_musicxml_extension_detected_as_omr_raw(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/output.musicxml", FileType.XML)
        assert _detect_kind(mf) == MusicFileKind.OMR_RAW

    def test_unknown_falls_back_to_other(self):
        from scripts.migrate_to_library import _detect_kind

        mf = self._make_file("/uploads/1/notes.txt", FileType.TEXT)
        assert _detect_kind(mf) == MusicFileKind.OTHER
