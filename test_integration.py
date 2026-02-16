#!/usr/bin/env python3
"""
Simple integration test script to verify the church music organizer setup.
This script tests the core functionality without requiring external dependencies like Tesseract.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from src.database import init_db, get_db_session, MusicPiece, MusicFile, Tag, FileType
        print("✓ Database module imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import database module: {e}")
        return False
    
    try:
        from src.ocr import SheetMusicOCR, MusicXMLConverter
        print("✓ OCR module imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import OCR module: {e}")
        return False
    
    return True


def test_database():
    """Test database operations."""
    print("\nTesting database operations...")
    
    from src.database import init_db, get_db_session, MusicPiece, MusicFile, Tag, FileType
    
    # Clean up any existing test database
    import os
    test_db_path = "test_church_music.db"
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    # Set test database
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"
    
    # Reinitialize with test database
    from src.database.database import create_engine, Base, SessionLocal
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(f"sqlite:///{test_db_path}")
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    
    try:
        # Test creating a music piece
        session = TestSession()
        piece = MusicPiece(
            title="Test Hymn",
            composer="Test Composer",
            genre="Hymn",
            key_signature="C major"
        )
        session.add(piece)
        session.commit()
        piece_id = piece.id
        session.close()
        print(f"✓ Created music piece (ID: {piece_id})")
        
        # Test adding a tag
        session = TestSession()
        piece = session.query(MusicPiece).filter_by(id=piece_id).first()
        tag = Tag(name="test")
        piece.tags.append(tag)
        session.commit()
        session.close()
        print("✓ Added tag to music piece")
        
        # Test adding a file
        session = TestSession()
        music_file = MusicFile(
            music_piece_id=piece_id,
            file_path="/test/path.pdf",
            file_type=FileType.PDF,
            original_filename="test.pdf"
        )
        session.add(music_file)
        session.commit()
        session.close()
        print("✓ Added file to music piece")
        
        # Test querying
        session = TestSession()
        pieces = session.query(MusicPiece).all()
        assert len(pieces) == 1
        assert pieces[0].title == "Test Hymn"
        assert len(pieces[0].tags) == 1
        assert len(pieces[0].files) == 1
        session.close()
        print(f"✓ Query returned {len(pieces)} piece(s)")
        
        # Clean up
        os.remove(test_db_path)
        print("✓ Database tests passed")
        return True
        
    except Exception as e:
        print(f"✗ Database test failed: {e}")
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        return False


def test_models():
    """Test model relationships."""
    print("\nTesting model relationships...")
    
    from src.database.models import MusicPiece, MusicFile, Tag, FileType
    
    try:
        # Create objects (not persisted)
        piece = MusicPiece(title="Test Piece")
        assert piece.title == "Test Piece"
        print("✓ MusicPiece model works")
        
        tag = Tag(name="test_tag")
        assert tag.name == "test_tag"
        print("✓ Tag model works")
        
        # Test FileType enum
        assert FileType.PDF.value == "pdf"
        assert FileType.MUSESCORE.value == "musescore"
        print("✓ FileType enum works")
        
        return True
    except Exception as e:
        print(f"✗ Model test failed: {e}")
        return False


def test_directory_structure():
    """Test that required directories exist."""
    print("\nTesting directory structure...")
    
    required_dirs = [
        "src",
        "src/database",
        "src/ocr",
        "src/app",
        "data",
        "data/uploads",
        "data/processed",
        "tests"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if not Path(dir_path).exists():
            print(f"✗ Missing directory: {dir_path}")
            all_exist = False
        else:
            print(f"✓ Directory exists: {dir_path}")
    
    return all_exist


def test_required_files():
    """Test that required files exist."""
    print("\nTesting required files...")
    
    required_files = [
        "requirements.txt",
        "README.md",
        "src/database/models.py",
        "src/database/database.py",
        "src/ocr/sheet_music_ocr.py",
        "src/ocr/musicxml_converter.py",
        "src/ocr/scan_processor.py",
        "src/app/main.py",
        "tests/test_database.py",
        "tests/test_ocr.py"
    ]
    
    all_exist = True
    for file_path in required_files:
        if not Path(file_path).exists():
            print(f"✗ Missing file: {file_path}")
            all_exist = False
        else:
            print(f"✓ File exists: {file_path}")
    
    return all_exist


def main():
    """Run all tests."""
    print("=" * 60)
    print("Church Music Organizer - Integration Test")
    print("=" * 60)
    
    tests = [
        ("Directory Structure", test_directory_structure),
        ("Required Files", test_required_files),
        ("Module Imports", test_imports),
        ("Model Definitions", test_models),
        ("Database Operations", test_database),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'=' * 60}")
        print(f"Running: {test_name}")
        print(f"{'=' * 60}")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' raised an exception: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! The application is ready to use.")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
