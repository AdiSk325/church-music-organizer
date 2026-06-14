"""Database models for church music organizer."""

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class FileType(enum.Enum):
    """Enum for file types."""

    SCAN = "scan"
    PDF = "pdf"
    MUSESCORE = "musescore"
    XML = "xml"
    TEXT = "text"
    OTHER = "other"


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
    lyrics = Column(Text)  # tekst utworu
    musescore_link = Column(String(512))  # link do zapisu w MuseScore
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
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
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    music_piece = relationship("MusicPiece", back_populates="files")


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
