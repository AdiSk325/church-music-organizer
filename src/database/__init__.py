"""Database module for church music organizer."""

from .database import engine, get_db, get_db_session, init_db
from .models import (
    Base,
    FileType,
    KnowledgeCategory,
    KnowledgeNote,
    MusicFile,
    MusicFileKind,
    MusicPiece,
    MusicPieceTag,
    PieceUsageCategory,
    ProcessingStep,
    RightsStatus,
    Source,
    SourceType,
    Tag,
    Translation,
    TranslationKind,
    UsageCategory,
    UsageHistory,
)

__all__ = [
    # Database helpers
    "Base",
    "engine",
    "get_db",
    "get_db_session",
    "init_db",
    # Enums — istniejące
    "FileType",
    # Enums — nowe
    "MusicFileKind",
    "SourceType",
    "RightsStatus",
    "TranslationKind",
    "KnowledgeCategory",
    # Modele — istniejące
    "MusicPiece",
    "MusicFile",
    "Tag",
    "MusicPieceTag",
    "ProcessingStep",
    "UsageHistory",
    # Modele — nowe
    "Source",
    "Translation",
    "UsageCategory",
    "PieceUsageCategory",
    "KnowledgeNote",
]
