#!/usr/bin/env python3
"""One-time, idempotent migration from data/uploads/{piece_id}/ to the library layout.

Usage
-----
    # Dry run (default) — reports what would happen, nothing is written:
    poetry run python scripts/migrate_to_library.py --dry-run

    # Real run — backup first, then migrate:
    poetry run python scripts/migrate_to_library.py --apply

Design
------
- STEP 0  (--apply only): backup church_music.db and data/uploads/ with a timestamp
  under backups/.  Abort if backup fails.
- STEP 1  For each MusicPiece: generate/persist slug, create library dir, write piece.yaml.
- STEP 2  Move files from data/uploads/{id}/* to sources/|scores/|derived/ based on
  detected MusicFileKind.  Update MusicFile.file_path, .kind, .opens_externally.
- STEP 3  lyrics_translation_pl (non-empty) → Translation(language='pl', kind=LITERAL,
  source='gemini', is_primary=True).  Idempotent: skip if primary-pl Translation exists.
- STEP 4  musescore_link (non-empty) → Source(source_type=EXTERNAL_LINK, url=...,
  rights_status=UNKNOWN).  Idempotent: skip if Source with that url exists.
- STEP 5  lyrics (non-empty) → write texts/lyrics.md via LibraryService.write_text.

Idempotence guarantee: re-running --apply again does NOT duplicate rows or re-move files.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so that ``src.*`` imports work when the
# script is executed directly (poetry run python scripts/...).
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.database.models import (  # noqa: E402
    FileType,
    MusicFile,
    MusicFileKind,
    MusicPiece,
    RightsStatus,
    Source,
    SourceType,
    Translation,
    TranslationKind,
)
from src.services.library_service import LibraryService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight schema-sync (mirrors database.py::_sync_sqlite_columns)
# Applied to the engine created from --db so new columns exist before queries.
# ---------------------------------------------------------------------------


def _sync_new_columns(engine: Any) -> None:  # engine: sqlalchemy.Engine
    """Add columns that exist in models but are missing from the live DB (SQLite only)."""
    if engine.dialect.name != "sqlite":
        return

    from sqlalchemy import inspect as _inspect, text as _text  # noqa: PLC0415
    from src.database.models import Base as _Base  # noqa: PLC0415

    inspector = _inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in _Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                if column.default is not None and getattr(column.default, "arg", None) is not None:
                    arg = column.default.arg
                    if isinstance(arg, (int, float)):
                        ddl += f" DEFAULT {arg}"
                conn.execute(_text(ddl))
                log.info("Auto-migrated: added column %s.%s", table.name, column.name)

# ---------------------------------------------------------------------------
# Kind detection — one-time inference from legacy naming conventions
# ---------------------------------------------------------------------------

_OPENS_EXTERNALLY_KINDS = {
    MusicFileKind.EDITABLE,
    MusicFileKind.CORRECTED,
    MusicFileKind.FINAL,
    MusicFileKind.OMR_RAW,
}


def _detect_kind(mf: MusicFile) -> MusicFileKind:
    """Infer MusicFileKind from legacy filename prefixes, description, and FileType.

    Priority order (highest wins):
    1. filename starts with 'final_'       → FINAL
    2. filename starts with 'corrected_'   → CORRECTED
    3. description starts '[REFERENCJA]'   → REFERENCE
    4. extension .mscz / .mscx            → EDITABLE
    5. FileType.PDF                        → SOURCE_PDF
    6. FileType.SCAN                       → SOURCE_SCAN
    7. extension .xml / .musicxml          → OMR_RAW
    8. fallback                            → OTHER
    """
    filename = Path(mf.file_path).name.lower()
    ext = Path(mf.file_path).suffix.lower()
    description = (mf.description or "").strip()

    if filename.startswith("final_"):
        return MusicFileKind.FINAL
    if filename.startswith("corrected_"):
        return MusicFileKind.CORRECTED
    if description.startswith("[REFERENCJA]"):
        return MusicFileKind.REFERENCE
    if ext in (".mscz", ".mscx"):
        return MusicFileKind.EDITABLE
    if mf.file_type == FileType.PDF:
        return MusicFileKind.SOURCE_PDF
    if mf.file_type == FileType.SCAN:
        return MusicFileKind.SOURCE_SCAN
    if ext in (".xml", ".musicxml"):
        return MusicFileKind.OMR_RAW
    return MusicFileKind.OTHER


# ---------------------------------------------------------------------------
# Backup helpers
# ---------------------------------------------------------------------------


def _backup(db_path: Path, uploads_dir: Path, backups_dir: Path) -> None:
    """Copy church_music.db and data/uploads/ to backups/ with a timestamp.

    Raises RuntimeError if either source exists but the copy fails.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backups_dir.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        dest = backups_dir / f"church_music_{ts}.db"
        try:
            shutil.copy2(db_path, dest)
            log.info("DB backup → %s", dest)
        except Exception as exc:
            raise RuntimeError(f"Failed to backup {db_path}: {exc}") from exc
    else:
        log.warning("church_music.db not found — skipping DB backup")

    if uploads_dir.exists():
        dest_dir = backups_dir / f"uploads_{ts}"
        try:
            shutil.copytree(uploads_dir, dest_dir)
            log.info("Uploads backup → %s", dest_dir)
        except Exception as exc:
            raise RuntimeError(f"Failed to backup {uploads_dir}: {exc}") from exc
    else:
        log.warning("data/uploads/ not found — skipping uploads backup")


# ---------------------------------------------------------------------------
# Per-piece migration helpers
# ---------------------------------------------------------------------------


def _ensure_slug(piece: MusicPiece, db, dry_run: bool) -> str:
    """Return piece.slug (generate + persist if blank and not dry-run)."""
    if piece.slug:
        return piece.slug
    slug = LibraryService.slugify(piece.title)
    if not dry_run:
        piece.slug = slug
        db.flush()
    return slug


def _migrate_file(
    mf: MusicFile,
    piece: MusicPiece,
    uploads_dir: Path,
    dry_run: bool,
    db,
) -> Optional[str]:
    """Move one MusicFile from legacy uploads to the library.

    Returns the new file path string on success / would-be-path in dry-run,
    or None if the source file does not exist on disk.
    """
    src_path = Path(mf.file_path)
    if not src_path.is_absolute():
        src_path = PROJECT_ROOT / src_path

    kind = _detect_kind(mf)
    subdir = LibraryService.subdir_for_kind(kind)
    # create=not dry_run keeps a --dry-run free of filesystem side effects.
    piece_dir = LibraryService.piece_dir(piece, create=not dry_run)
    dest_dir = piece_dir / subdir
    dest_path = dest_dir / src_path.name

    def _apply_db_fields() -> None:
        mf.file_path = str(dest_path)
        mf.kind = kind
        mf.opens_externally = kind in _OPENS_EXTERNALLY_KINDS
        db.flush()

    if not src_path.exists():
        # Crash recovery: a previous interrupted --apply may have moved the file
        # already (DB then rolled back, leaving the row pointing at the old
        # path). Re-point the DB row to the new location rather than skipping,
        # which would otherwise orphan the row.
        if not dry_run and dest_path.exists():
            _apply_db_fields()
            return str(dest_path)
        log.debug("Source file missing (already moved?): %s", src_path)
        return None

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not dest_path.exists():
            shutil.move(str(src_path), str(dest_path))
        _apply_db_fields()
    return str(dest_path)


def _ensure_translation(piece: MusicPiece, dry_run: bool, db) -> bool:
    """Create primary-pl Translation from lyrics_translation_pl if not already present.

    Returns True if a Translation was (or would be) created.
    """
    text = (piece.lyrics_translation_pl or "").strip()
    if not text:
        return False

    # Idempotency: skip if any primary-pl Translation already exists
    existing = next(
        (t for t in piece.translations if t.language == "pl" and t.is_primary), None
    )
    if existing is not None:
        return False

    if not dry_run:
        tr = Translation(
            music_piece_id=piece.id,
            language="pl",
            kind=TranslationKind.LITERAL,
            source="gemini",
            is_primary=True,
            text=text,
        )
        db.add(tr)
        db.flush()
    return True


def _ensure_source(piece: MusicPiece, dry_run: bool, db) -> bool:
    """Create Source(EXTERNAL_LINK) from musescore_link if not already present.

    Returns True if a Source was (or would be) created.
    """
    url = (piece.musescore_link or "").strip()
    if not url:
        return False

    # Idempotency: skip if a Source with this exact URL already exists
    existing = next((s for s in piece.sources if s.url == url), None)
    if existing is not None:
        return False

    if not dry_run:
        src = Source(
            music_piece_id=piece.id,
            source_type=SourceType.EXTERNAL_LINK,
            url=url,
            rights_status=RightsStatus.UNKNOWN,
        )
        db.add(src)
        db.flush()
    return True


def _write_lyrics(piece: MusicPiece, dry_run: bool) -> bool:
    """Write texts/lyrics.md if piece.lyrics is non-empty.

    Returns True if the file was (or would be) written.
    """
    text = (piece.lyrics or "").strip()
    if not text:
        return False
    if not dry_run:
        LibraryService.write_text(piece, "lyrics.md", text)
    return True


# ---------------------------------------------------------------------------
# Main migration runner
# ---------------------------------------------------------------------------


def run_migration(
    db,
    uploads_dir: Path,
    dry_run: bool,
) -> Dict[str, int]:
    """Execute migration steps for all MusicPiece rows.

    Args:
        db:          Active SQLAlchemy session (will flush but NOT commit).
        uploads_dir: Legacy uploads root (data/uploads/).
        dry_run:     When True, nothing is written — only report counts.

    Returns:
        Summary dict with counts of pieces, files_moved, translations_created,
        sources_created, lyrics_written.
    """
    pieces: List[MusicPiece] = db.query(MusicPiece).all()

    # Pre-flight: detect slug collisions BEFORE moving any file. Two distinct
    # titles can slugify to the same value (e.g. "Ave Maria" / "Ave-Maria"),
    # which would raise a UNIQUE violation mid-run. The per-piece directory name
    # is id-prefixed so folders never clash, but the unique slug column would —
    # fail fast with a readable message instead of a half-done migration.
    pending = [(p, LibraryService.slugify(p.title)) for p in pieces if not p.slug]
    seen: Dict[str, str] = {}
    collisions = []
    for piece, slug in pending:
        if slug in seen:
            collisions.append(f"{slug!r}: {seen[slug]!r} vs {piece.title!r}")
        else:
            seen[slug] = piece.title
    if collisions:
        for c in collisions:
            log.error("Slug collision — %s", c)
        log.error("Resolve by editing titles (or pre-setting piece.slug) and re-run.")
        return {"error": 1, "collisions": len(collisions)}

    pieces_count = 0
    files_moved = 0
    translations_created = 0
    sources_created = 0
    lyrics_written = 0

    for piece in pieces:
        pieces_count += 1
        slug = _ensure_slug(piece, db, dry_run)
        log.info(
            "[%s] %s | slug=%s",
            "DRY" if dry_run else "APPLY",
            piece.title,
            slug,
        )

        # STEP 1 — piece directory + piece.yaml
        if not dry_run:
            piece_dir = LibraryService.piece_dir(piece)
            LibraryService.write_piece_yaml(piece)
            log.debug("  piece.yaml written → %s", piece_dir)

        # STEP 2 — move files
        for mf in list(piece.files):
            new_path = _migrate_file(mf, piece, uploads_dir, dry_run, db)
            if new_path is not None:
                files_moved += 1
                log.info("  file: %s → %s", mf.file_path, new_path)

        # STEP 3 — translation
        if _ensure_translation(piece, dry_run, db):
            translations_created += 1
            log.info("  Translation(pl, LITERAL) %s", "would be created" if dry_run else "created")

        # STEP 4 — musescore source link
        if _ensure_source(piece, dry_run, db):
            sources_created += 1
            log.info("  Source(EXTERNAL_LINK) %s", "would be created" if dry_run else "created")

        # STEP 5 — lyrics.md
        if _write_lyrics(piece, dry_run):
            lyrics_written += 1
            log.info("  texts/lyrics.md %s", "would be written" if dry_run else "written")

    return {
        "pieces": pieces_count,
        "files_moved": files_moved,
        "translations_created": translations_created,
        "sources_created": sources_created,
        "lyrics_written": lyrics_written,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate church-music-organizer uploads to the library layout."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Report what would happen without writing anything (default).",
    )
    mode.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Execute the migration (creates backup first).",
    )
    parser.add_argument(
        "--db",
        default=str(PROJECT_ROOT / "church_music.db"),
        help="Path to church_music.db (default: <project_root>/church_music.db).",
    )
    parser.add_argument(
        "--uploads-dir",
        default=str(PROJECT_ROOT / "data" / "uploads"),
        help="Legacy uploads root (default: <project_root>/data/uploads).",
    )
    parser.add_argument(
        "--backups-dir",
        default=str(PROJECT_ROOT / "backups"),
        help="Where to write backups (default: <project_root>/backups).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    dry_run: bool = args.dry_run
    db_path = Path(args.db)
    uploads_dir = Path(args.uploads_dir)
    backups_dir = Path(args.backups_dir)

    mode_label = "DRY RUN" if dry_run else "APPLY"
    log.info("=== migrate_to_library.py [%s] ===", mode_label)

    # STEP 0 — backup (only on --apply)
    if not dry_run:
        log.info("STEP 0: Creating backup …")
        try:
            _backup(db_path, uploads_dir, backups_dir)
        except RuntimeError as exc:
            log.error("Backup failed — aborting migration: %s", exc)
            return 1
        log.info("STEP 0: Backup complete.")

    # Connect to the database specified by --db (not the module-level engine)
    from sqlalchemy import create_engine as _create_engine, inspect, text  # noqa: PLC0415
    from sqlalchemy.orm import sessionmaker as _sessionmaker  # noqa: PLC0415
    from src.database.models import Base  # noqa: PLC0415

    db_url = f"sqlite:///{db_path}" if not str(db_path).startswith("sqlite") else str(db_path)
    engine = _create_engine(db_url)

    # Ensure all tables exist and new columns are present (idempotent, no data loss)
    Base.metadata.create_all(bind=engine)
    _sync_new_columns(engine)

    Session = _sessionmaker(bind=engine)
    db = Session()

    try:
        summary = run_migration(db, uploads_dir, dry_run=dry_run)
        if not dry_run:
            db.commit()
    except Exception as exc:
        db.rollback()
        log.error("Migration failed — rolled back: %s", exc)
        return 1
    finally:
        db.close()

    # Report
    print(f"\n=== Migration summary [{mode_label}] ===")
    print(f"  Pieces processed   : {summary['pieces']}")
    print(f"  Files moved        : {summary['files_moved']}")
    print(f"  Translations added : {summary['translations_created']}")
    print(f"  Sources added      : {summary['sources_created']}")
    print(f"  lyrics.md written  : {summary['lyrics_written']}")
    if dry_run:
        print("\nNothing was changed.  Re-run with --apply to execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
