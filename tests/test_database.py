"""Tests for database models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Base, MusicPiece, MusicFile, Tag, FileType


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_music_piece(db_session):
    """Test creating a music piece."""
    piece = MusicPiece(
        title="Ave Maria",
        composer="Franz Schubert",
        genre="Hymn",
        key_signature="C major"
    )
    db_session.add(piece)
    db_session.commit()
    
    assert piece.id is not None
    assert piece.title == "Ave Maria"
    assert piece.composer == "Franz Schubert"


def test_create_music_file(db_session):
    """Test creating a music file."""
    piece = MusicPiece(title="Test Piece")
    db_session.add(piece)
    db_session.commit()
    
    music_file = MusicFile(
        music_piece_id=piece.id,
        file_path="/path/to/file.pdf",
        file_type=FileType.PDF,
        original_filename="file.pdf"
    )
    db_session.add(music_file)
    db_session.commit()
    
    assert music_file.id is not None
    assert music_file.music_piece_id == piece.id
    assert music_file.file_type == FileType.PDF


def test_music_piece_with_tags(db_session):
    """Test music piece with tags."""
    piece = MusicPiece(title="Christmas Carol")
    tag1 = Tag(name="Christmas")
    tag2 = Tag(name="Festive")
    
    piece.tags.append(tag1)
    piece.tags.append(tag2)
    
    db_session.add(piece)
    db_session.commit()
    
    assert len(piece.tags) == 2
    assert tag1.name in [t.name for t in piece.tags]
    assert tag2.name in [t.name for t in piece.tags]


def test_music_piece_relationship(db_session):
    """Test relationship between music piece and files."""
    piece = MusicPiece(title="Test Piece")
    db_session.add(piece)
    db_session.commit()
    
    file1 = MusicFile(
        music_piece_id=piece.id,
        file_path="/path/to/scan.pdf",
        file_type=FileType.PDF,
        original_filename="scan.pdf"
    )
    file2 = MusicFile(
        music_piece_id=piece.id,
        file_path="/path/to/score.mscz",
        file_type=FileType.MUSESCORE,
        original_filename="score.mscz"
    )
    
    db_session.add(file1)
    db_session.add(file2)
    db_session.commit()
    
    # Refresh to load relationships
    db_session.refresh(piece)
    
    assert len(piece.files) == 2
    assert any(f.file_type == FileType.PDF for f in piece.files)
    assert any(f.file_type == FileType.MUSESCORE for f in piece.files)
