"""Database models for church music organizer."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, relationship
import enum

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
    __tablename__ = 'music_pieces'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    composer = Column(String(255))
    arranger = Column(String(255))
    genre = Column(String(100))
    key_signature = Column(String(50))
    time_signature = Column(String(50))
    tempo = Column(String(100))
    occasion = Column(String(100))  # e.g., "Easter", "Christmas", "Wedding"
    liturgical_season = Column(String(100))  # e.g., "Advent", "Lent"
    language = Column(String(50))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    files = relationship("MusicFile", back_populates="music_piece", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary="music_piece_tags", back_populates="music_pieces")


class MusicFile(Base):
    """Model for files associated with music pieces."""
    __tablename__ = 'music_files'
    
    id = Column(Integer, primary_key=True)
    music_piece_id = Column(Integer, ForeignKey('music_pieces.id'), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    original_filename = Column(String(255))
    file_size = Column(Integer)  # in bytes
    mime_type = Column(String(100))
    description = Column(Text)
    is_processed = Column(Integer, default=0)  # 0 = not processed, 1 = processed
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    music_piece = relationship("MusicPiece", back_populates="files")


class Tag(Base):
    """Model for tags to categorize music pieces."""
    __tablename__ = 'tags'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    
    # Relationships
    music_pieces = relationship("MusicPiece", secondary="music_piece_tags", back_populates="tags")


class MusicPieceTag(Base):
    """Association table for music pieces and tags."""
    __tablename__ = 'music_piece_tags'
    
    music_piece_id = Column(Integer, ForeignKey('music_pieces.id'), primary_key=True)
    tag_id = Column(Integer, ForeignKey('tags.id'), primary_key=True)
