"""Database initialization and session management."""

import logging
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

logger = logging.getLogger(__name__)

# Database URL - using SQLite for simplicity
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///church_music.db")

# Create engine
engine = create_engine(DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _sync_sqlite_columns():
    """Add columns present in the models but missing from existing tables.

    ``create_all`` creates missing *tables* but never alters existing ones, so a
    database created against an older model is left without newly added columns
    (e.g. ``music_files.extracted_text``). Reading such a table then raises
    ``OperationalError: no such column``. This lightweight, idempotent migration
    closes that gap for SQLite without requiring a full Alembic setup.
    """
    if engine.dialect.name != "sqlite":
        return  # ALTER TABLE ADD COLUMN semantics differ on other backends

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all() already produced it with all columns
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
                conn.execute(text(ddl))
                logger.info("Auto-migrated: added column %s.%s", table.name, column.name)


def init_db():
    """Initialize the database by creating all tables (and sync new columns)."""
    Base.metadata.create_all(bind=engine)
    _sync_sqlite_columns()


def get_db() -> Session:
    """Get a database session."""
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise


@contextmanager
def get_db_session():
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
