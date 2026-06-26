"""Database models for church music organizer."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, object_session, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# Enums — istniejące
# ---------------------------------------------------------------------------


class FileType(enum.Enum):
    """Enum for file types."""

    SCAN = "scan"
    PDF = "pdf"
    MUSESCORE = "musescore"
    XML = "xml"
    TEXT = "text"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Enums — nowe (Zadanie A)
# ---------------------------------------------------------------------------


class MusicFileKind(enum.Enum):
    """Semantic kind of a MusicFile — replaces brittle filename-prefix conventions."""

    SOURCE_SCAN = "source_scan"
    SOURCE_PDF = "source_pdf"
    OMR_RAW = "omr_raw"
    CORRECTED = "corrected"
    FINAL = "final"
    REFERENCE = "reference"
    EDITABLE = "editable"  # mscz / mscx — opens in MuseScore
    OTHER = "other"


class SourceType(enum.Enum):
    """How/where a piece was obtained."""

    EXTERNAL_LINK = "external_link"
    EVENT_ENSEMBLE = "event_ensemble"
    LOCAL_UPLOAD = "local_upload"


class RightsStatus(enum.Enum):
    """Copyright / licensing status of a source."""

    PUBLIC_DOMAIN = "public_domain"
    LICENSED = "licensed"
    UNKNOWN = "unknown"


class TranslationKind(enum.Enum):
    """Purpose of a translation text."""

    LITERAL = "literal"
    SINGABLE = "singable"
    RHYMED = "rhymed"


class KnowledgeCategory(enum.Enum):
    """Category of a KnowledgeNote entry."""

    HISTORICAL = "historical"
    STYLISTIC = "stylistic"
    HARMONIC = "harmonic"
    PERFORMANCE = "performance"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# MusicPiece
# ---------------------------------------------------------------------------


class MusicPiece(Base):
    """Model for music pieces."""

    __tablename__ = "music_pieces"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    composer = Column(String(255))
    arranger = Column(String(255))
    lyrics_author = Column(String(255))  # autor słów
    music_author = Column(String(255))  # autor muzyki
    harmony_author = Column(String(255))  # autor harmonii
    genre = Column(String(100))
    key_signature = Column(String(50))
    time_signature = Column(String(50))
    measures_count = Column(Integer)  # ilość taktów
    tempo = Column(String(100))
    occasion = Column(String(100))  # e.g., "Easter", "Christmas", "Wedding"
    liturgical_season = Column(String(100))  # e.g., "Advent", "Lent"
    language = Column(String(50))
    description = Column(Text)  # szczegółowy opis utworu
    lyrics = Column(Text)  # tekst utworu (oryginał)
    lyrics_translation_pl = Column(Text)  # tłumaczenie tekstu na polski (Gemini LLM) — legacy
    musescore_link = Column(String(512))  # link do zapisu w MuseScore
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Nowe pola — Zadanie A
    slug = Column(String(255), unique=True, index=True, nullable=True)
    difficulty_grade = Column(Integer, nullable=True)
    difficulty_notes = Column(Text, nullable=True)

    # Relationships — istniejące
    files = relationship("MusicFile", back_populates="music_piece", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary="music_piece_tags", back_populates="music_pieces")
    usage_history = relationship(
        "UsageHistory", back_populates="music_piece", cascade="all, delete-orphan"
    )
    processing_steps = relationship(
        "ProcessingStep",
        back_populates="music_piece",
        cascade="all, delete-orphan",
        order_by="ProcessingStep.created_at",
    )

    # Relationships — nowe (Zadanie A)
    sources = relationship("Source", back_populates="music_piece", cascade="all, delete-orphan")
    translations = relationship(
        "Translation", back_populates="music_piece", cascade="all, delete-orphan"
    )
    knowledge_notes = relationship(
        "KnowledgeNote", back_populates="music_piece", cascade="all, delete-orphan"
    )
    usage_categories = relationship(
        "UsageCategory", secondary="piece_usage_categories", back_populates="music_pieces"
    )

    @property
    def primary_translation_pl(self) -> Optional[str]:
        """Return the text of the primary Polish translation, falling back to the legacy column.

        Resolution order:
        1. The Translation row with language='pl' and is_primary=True.
        2. The newest Translation row with language='pl' (by created_at descending).
        3. The legacy lyrics_translation_pl column value.

        When the instance is attached to a live session the property issues fresh SQL queries
        so that rows added/modified after the last ``refresh`` (e.g. immediately after a
        ``flush``) are always visible — avoiding stale-collection bugs (WAŻNE-2).
        """
        sess = object_session(self)
        if sess is not None and self.id is not None:
            # Fresh queries bypass any cached translations collection on the ORM instance.
            primary = (
                sess.query(Translation)
                .filter(
                    Translation.music_piece_id == self.id,
                    Translation.language == "pl",
                    Translation.is_primary.is_(True),
                )
                .first()
            )
            if primary is not None:
                return primary.text

            newest = (
                sess.query(Translation)
                .filter(
                    Translation.music_piece_id == self.id,
                    Translation.language == "pl",
                )
                .order_by(Translation.created_at.desc())
                .first()
            )
            if newest is not None:
                return newest.text
        else:
            # Detached instance — use the already-loaded in-memory collection.
            primary = next(
                (t for t in self.translations if t.language == "pl" and t.is_primary), None
            )
            if primary is not None:
                return primary.text

            pl_list = sorted(
                [t for t in self.translations if t.language == "pl"],
                key=lambda t: t.created_at or datetime.min,
                reverse=True,
            )
            if pl_list:
                return pl_list[0].text

        return self.lyrics_translation_pl  # legacy column — fallback


# ---------------------------------------------------------------------------
# MusicFile
# ---------------------------------------------------------------------------


class MusicFile(Base):
    """Model for files associated with music pieces."""

    __tablename__ = "music_files"

    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    original_filename = Column(String(255))
    file_size = Column(Integer)  # in bytes
    mime_type = Column(String(100))
    description = Column(Text)
    is_processed = Column(Integer, default=0)  # 0 = not processed, 1 = processed
    extracted_text = Column(Text, nullable=True)  # wynik OCR
    ocr_confidence = Column(Integer, nullable=True)  # 0-100
    # Wersja w obrębie "rodzaju" pliku wyjściowego (np. kolejne korekty / finalne pliki tego
    # samego utworu). Nadawana przez PipelineService przy zapisie; None dla plików wgranych ręcznie.
    version = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Nowe pola — Zadanie A
    kind = Column(Enum(MusicFileKind), nullable=True)
    opens_externally = Column(Boolean, default=False, nullable=False)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="files")


# ---------------------------------------------------------------------------
# ProcessingStep
# ---------------------------------------------------------------------------


class ProcessingStep(Base):
    """A single recorded step of the transcription pipeline.

    Append-only audit trail: every run of a step (OCR, text cleaning, OMR, analysis,
    score correction, lyric underlay) writes one row, so intermediate results — status,
    human-readable report and structured payload — survive page reloads and are shown
    per-section in the UI. The newest row per ``step_key`` is the current result.
    """

    __tablename__ = "processing_steps"

    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), nullable=False)
    source_file_id = Column(Integer, ForeignKey("music_files.id"), nullable=True)  # input
    output_file_id = Column(Integer, ForeignKey("music_files.id"), nullable=True)  # produced
    step_key = Column(String(50), nullable=False)  # ocr|clean_text|omr|analysis|correct_score|...
    step_label = Column(String(255))  # human-readable name shown in the UI
    status = Column(String(20), nullable=False)  # ok | skipped | error
    detail = Column(Text)  # short one-line summary
    report = Column(Text, nullable=True)  # full LLM/analysis report (markdown)
    data_json = Column(Text, nullable=True)  # structured payload, e.g. ScoreDescriptor.to_dict()
    duration_ms = Column(Integer, nullable=True)  # wall-clock time of the step
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="processing_steps")


# ---------------------------------------------------------------------------
# Tag / MusicPieceTag
# ---------------------------------------------------------------------------


class Tag(Base):
    """Model for tags to categorize music pieces."""

    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)

    # Relationships
    music_pieces = relationship("MusicPiece", secondary="music_piece_tags", back_populates="tags")


class MusicPieceTag(Base):
    """Association table for music pieces and tags."""

    __tablename__ = "music_piece_tags"

    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id"), primary_key=True)


# ---------------------------------------------------------------------------
# UsageHistory
# ---------------------------------------------------------------------------


class UsageHistory(Base):
    """Model for tracking when a music piece was used."""

    __tablename__ = "usage_history"

    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), nullable=False)
    usage_date = Column(DateTime, nullable=False)
    event_name = Column(String(255))  # e.g., "Sunday Mass", "Wedding"
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="usage_history")


# ---------------------------------------------------------------------------
# Source — źródło dostępności utworu (Zadanie A)
# ---------------------------------------------------------------------------


class Source(Base):
    """Records how/where a music piece was obtained.

    A piece can have multiple sources: an external MuseScore link, a local upload,
    and a note about which ensemble performed it — all three at once.
    """

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), nullable=False)
    source_type = Column(Enum(SourceType), nullable=False)
    url = Column(String(512), nullable=True)
    label = Column(String(255), nullable=True)
    rights_status = Column(Enum(RightsStatus), default=RightsStatus.UNKNOWN, nullable=True)
    event_name = Column(String(255), nullable=True)
    ensemble = Column(String(255), nullable=True)
    acquired_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="sources")


# ---------------------------------------------------------------------------
# Translation — wielojęzyczne tłumaczenia (Zadanie A)
# ---------------------------------------------------------------------------


class Translation(Base):
    """A translation of a piece's lyrics into a given language and style.

    Replaces the single ``MusicPiece.lyrics_translation_pl`` column with a
    scalable, multi-language, multi-kind store.  The ``is_primary`` flag marks
    the canonical translation shown in the UI by default.
    """

    __tablename__ = "translations"

    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), nullable=False)
    language = Column(String(10), nullable=False)  # BCP-47 tag, e.g. "pl", "en", "la"
    kind = Column(Enum(TranslationKind), nullable=False, default=TranslationKind.LITERAL)
    text = Column(Text, nullable=False)
    source = Column(String(50), nullable=True)  # e.g. "gemini", "human", "cli"
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="translations")


# ---------------------------------------------------------------------------
# UsageCategory + PieceUsageCategory (M2M) — Zadanie A
# ---------------------------------------------------------------------------


class UsageCategory(Base):
    """Controlled vocabulary for liturgical/musical usage context.

    Examples: "Komunia", "Uwielbienie", "Procesja", "Koncert".
    A piece can belong to multiple categories; categories are shared across pieces
    (no cascade delete — same pattern as Tag).
    """

    __tablename__ = "usage_categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    # Relationships
    music_pieces = relationship(
        "MusicPiece", secondary="piece_usage_categories", back_populates="usage_categories"
    )


class PieceUsageCategory(Base):
    """Association table for MusicPiece ↔ UsageCategory (many-to-many)."""

    __tablename__ = "piece_usage_categories"

    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), primary_key=True)
    usage_category_id = Column(Integer, ForeignKey("usage_categories.id"), primary_key=True)


# ---------------------------------------------------------------------------
# KnowledgeNote — gromadzona wiedza o utworze (Zadanie A)
# ---------------------------------------------------------------------------


class KnowledgeNote(Base):
    """An append-friendly knowledge entry about a music piece.

    Stores historical context, performance notes, harmonic analysis, etc. in
    Markdown.  Each note belongs to one piece and is categorized for filtering.
    """

    __tablename__ = "knowledge_notes"

    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey("music_pieces.id"), nullable=False)
    category = Column(Enum(KnowledgeCategory), default=KnowledgeCategory.GENERAL, nullable=True)
    title = Column(String(255), nullable=True)
    body_md = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="knowledge_notes")
