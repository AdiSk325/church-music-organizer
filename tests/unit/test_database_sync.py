"""Unit tests for _sync_sqlite_columns() in src/database/database.py.

Strategy: create a fresh SQLite database (via tmp_path) with an intentionally
partial schema (only the ``id`` column on ``music_files``), then monkeypatch the
module-level ``engine`` in ``src.database.database`` so ``_sync_sqlite_columns``
operates on our test database rather than the real ``church_music.db``.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text

import src.database.database as db_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_with_partial_schema(db_url: str):
    """Create a SQLite engine whose ``music_files`` table only has ``id``."""
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE music_files (id INTEGER PRIMARY KEY)"))
    return engine


def _col_names(engine, table_name: str) -> set:
    """Return the set of column names for a table in the given engine."""
    inspector = inspect(engine)
    return {col["name"] for col in inspector.get_columns(table_name)}


# ---------------------------------------------------------------------------
# Tests: missing column is added
# ---------------------------------------------------------------------------


class TestSyncSQLiteColumnsAddsColumns:
    def test_adds_extracted_text_column(self, tmp_path):
        """extracted_text must be added when the table is missing it."""
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        assert "extracted_text" in _col_names(engine, "music_files")

    def test_adds_file_path_column(self, tmp_path):
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        assert "file_path" in _col_names(engine, "music_files")

    def test_adds_file_type_column(self, tmp_path):
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        assert "file_type" in _col_names(engine, "music_files")

    def test_adds_is_processed_column(self, tmp_path):
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        assert "is_processed" in _col_names(engine, "music_files")

    def test_adds_ocr_confidence_column(self, tmp_path):
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        assert "ocr_confidence" in _col_names(engine, "music_files")

    def test_adds_all_model_columns(self, tmp_path):
        """Every column defined in the MusicFile model must be present after sync."""
        from src.database.models import MusicFile

        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        actual_cols = _col_names(engine, "music_files")
        model_cols = {col.name for col in MusicFile.__table__.columns}
        assert model_cols.issubset(
            actual_cols
        ), f"Columns missing after sync: {model_cols - actual_cols}"


# ---------------------------------------------------------------------------
# Tests: idempotency — second call must not raise
# ---------------------------------------------------------------------------


class TestSyncSQLiteColumnsIdempotent:
    def test_second_call_does_not_raise(self, tmp_path):
        """Calling _sync_sqlite_columns twice on the same DB must not raise."""
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()  # first call — adds columns
            db_module._sync_sqlite_columns()  # second call — must be a no-op

    def test_second_call_does_not_duplicate_columns(self, tmp_path):
        """Column names must appear exactly once after two sync calls."""
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()
            db_module._sync_sqlite_columns()

        inspector = inspect(engine)
        col_names = [col["name"] for col in inspector.get_columns("music_files")]
        # No duplicates
        assert len(col_names) == len(set(col_names))

    def test_call_on_fully_up_to_date_schema_does_not_raise(self, tmp_path):
        """Syncing a DB already created by create_all() must be harmless."""
        from src.database.models import Base

        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        Base.metadata.create_all(bind=engine)  # creates all tables with all columns

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()  # must not raise


# ---------------------------------------------------------------------------
# Tests: partial existing columns are preserved
# ---------------------------------------------------------------------------


class TestSyncSQLiteColumnsPreservesExistingColumns:
    def test_existing_column_not_duplicated(self, tmp_path):
        """A column already in the table must still appear exactly once."""
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE music_files " "(id INTEGER PRIMARY KEY, file_path VARCHAR(512))")
            )

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        col_names = [c["name"] for c in inspect(engine).get_columns("music_files")]
        assert col_names.count("file_path") == 1

    def test_original_id_column_still_present(self, tmp_path):
        engine = _engine_with_partial_schema(f"sqlite:///{tmp_path / 'test.db'}")

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        assert "id" in _col_names(engine, "music_files")


# ---------------------------------------------------------------------------
# Tests: tables absent from Base.metadata are untouched
# ---------------------------------------------------------------------------


class TestSyncSQLiteColumnsIgnoresUnknownTables:
    def test_custom_table_columns_unchanged(self, tmp_path):
        """Tables not defined in Base.metadata must not be modified."""
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE custom_table (id INTEGER PRIMARY KEY, data TEXT)"))

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()

        cols = _col_names(engine, "custom_table")
        assert cols == {"id", "data"}

    def test_does_not_create_nonexistent_model_tables(self, tmp_path):
        """_sync_sqlite_columns skips (does not create) tables absent from the DB."""
        engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
        # DB is empty — no tables at all

        with patch.object(db_module, "engine", engine):
            db_module._sync_sqlite_columns()  # must not raise

        inspector = inspect(engine)
        assert inspector.get_table_names() == []


# ---------------------------------------------------------------------------
# Tests: non-SQLite engine is skipped
# ---------------------------------------------------------------------------


class TestSyncSQLiteColumnsSkipsNonSQLite:
    def test_returns_early_for_non_sqlite_dialect(self, monkeypatch):
        """_sync_sqlite_columns is a no-op for non-SQLite backends."""
        # Use a mock engine whose dialect.name != "sqlite"
        from unittest.mock import MagicMock

        mock_engine = MagicMock()
        mock_engine.dialect.name = "postgresql"

        with patch.object(db_module, "engine", mock_engine):
            db_module._sync_sqlite_columns()

        # inspect() and begin() must never be called for non-SQLite
        mock_engine.begin.assert_not_called()
