# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
streamlit run src/app/main.py        # starts at http://localhost:8501
./run.sh                             # convenience wrapper for the above

# Tests
pytest                               # runs tests/ with -v --tb=short (configured in pyproject.toml)
pytest tests/test_database.py::TestMusicPiece::test_create_music_piece  # single test

# Integration tests (standalone script, not pytest-integrated)
python test_integration.py

# Formatting (not enforced in CI)
black src/ tests/
isort src/ tests/

# Docker
docker-compose up -d
```

## Architecture

The app is a three-layer Python stack: **Streamlit UI → SQLAlchemy ORM → SQLite**.

### Database layer (`src/database/`)
- `models.py`: Four ORM models — `MusicPiece` (core entity, ~23 fields), `MusicFile` (attached files), `Tag` (many-to-many via `MusicPieceTag`), `UsageHistory` (performance log).
- `database.py`: Module-level engine/session factory created on import. Use `get_db_session()` (context manager, auto-commit/rollback) for all writes. `get_db()` exists but does not manage lifecycle — prefer the context manager. `init_db()` is called once at app startup to create tables.
- `DATABASE_URL` env var controls the DB; defaults to `sqlite:///church_music.db` in the working directory.

### OCR layer (`src/ocr/`)
- `sheet_music_ocr.py`: Wraps Tesseract. Preprocesses images (grayscale → adaptive threshold → denoise), runs OCR with Polish + English language packs, scores confidence, and detects staff lines via Hough transforms. Works on both images and multi-page PDFs (via pdf2image).
- `musicxml_converter.py`: Uses music21 to generate/convert MusicXML notation. Requires MuseScore installed for `.mscz` export.

### UI layer (`src/app/main.py`)
Single 560-line Streamlit file. Navigation is driven by `st.session_state` with two top-level views: collection list and individual song detail. The app calls `init_db()` on every cold start and interacts with the database through direct SQLAlchemy sessions (not via a service layer). File uploads are saved to `data/uploads/`; OCR outputs go to `data/processed/`.

## Key conventions

- **File types** are controlled by the `FileType` enum in `models.py` (`SCAN`, `PDF`, `MUSESCORE`, `XML`, `TEXT`, `OTHER`). File type detection in the UI uses `python-magic` (requires system `libmagic`).
- **Cascade deletes** are set on `MusicPiece` → `files` and `usage_history`. Deleting a piece removes all its files and history. Tags are not cascaded (shared across pieces).
- **Line length**: 100 characters (Black/isort configured in `pyproject.toml`).
- **Python target**: 3.8+ syntax.
- The database file (`church_music.db`) is created in the working directory at runtime — not committed to the repo.
- System dependencies required locally: `tesseract-ocr` with `tesseract-ocr-pol` and `tesseract-ocr-eng` language packs, `poppler-utils` (pdf2image), `libmagic`. See `Dockerfile` for the canonical install commands.
