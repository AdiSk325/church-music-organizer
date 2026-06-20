# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

Dependencies are managed with **Poetry**; the virtual environment lives in `.venv` inside the
project directory (configured via `poetry.toml`).

```bash
# First-time setup
pip install poetry          # if Poetry is not already installed
poetry install              # creates .venv and installs all deps (including dev)

# Activate the shell (optional — all commands below work without it via `poetry run`)
poetry shell
```

## Commands

```bash
# Run the application
poetry run streamlit run src/app/main.py   # starts at http://localhost:8501
./run.sh                                   # convenience wrapper for the above

# Tests
poetry run pytest                    # all tests; -v --tb=short configured in pyproject.toml
poetry run pytest tests/unit/        # unit tests only (models, database)
poetry run pytest tests/functional/  # OCR pipeline tests (skipped until fixtures added)
poetry run pytest tests/unit/test_database.py::test_create_music_piece  # single test

# Integration tests (standalone script, not pytest-integrated)
poetry run python test_integration.py

# Formatting (not enforced in CI)
poetry run black src/ tests/
poetry run isort src/ tests/

# Dependency management
poetry add <package>                 # add a runtime dependency
poetry add --group dev <package>     # add a dev-only dependency
poetry update                        # update all deps within declared constraints

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

### LLM pipeline layer (`src/llm/`, `src/services/pipeline_service.py`)
A 5-step transcription pipeline that chains the existing OCR/OMR engines with three new
Gemini-powered agents. Runnable as a cascade (`PipelineService.run_full`) or step by step:

1. **OCR** (Tesseract) → raw text — `OCRService` *(existing)*
2. **LLM clean text** → `MusicPiece.lyrics` — `src/llm/lyrics_cleaner.py` (structured output: language + cleaned lyrics)
3. **OMR** (Audiveris) → MusicXML — `OMRService` *(existing)*
4. **LLM correct score** → new `MusicFile(XML)` + change report — `src/llm/score_corrector.py`
5. **LLM align + programmatic underlay** → new `MusicFile(XML)` — `src/llm/lyric_underlayer.py` (LLM returns a syllable-per-onset plan; music21 inserts `<lyric>` and re-exports — output size is bounded by the score, not the token budget)

- `src/llm/client.py`: `LLMClient` wraps the Google Gemini SDK `google-genai` (imported lazily). `llm_available()` gates the UI like `tesseract_available()`/`audiveris_available()`. Step 4 streams text (`generate_content_stream`); steps 2/5 use structured outputs (`response_schema` + `response.parsed`). "Thinking" is disabled by default (`thinking_budget=0`, override via `CMO_LLM_THINKING_BUDGET`) so the output budget is not starved; noisy OCR is pre-filtered before step 2 to avoid Gemini's `PROHIBITED_CONTENT` prompt filter.
- `src/llm/musicxml_validate.py`: `load_musicxml_text()` decompresses `.mxl`; `validate_musicxml()` round-trips LLM output through music21 — **invalid output is rejected and the previous good file is kept** (steps 4/5 never overwrite the original OMR file; they always write a NEW `MusicFile`).
- **Auth**: default `genai.Client()` is zero-config — it reads `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) from the environment. No key in code. `.env` is loaded by `client.py` on import.
- **Config (.env)**: `GEMINI_API_KEY` (required), `CMO_LLM_MODEL` (default `gemini-2.5-flash`), and per-step overrides `CMO_LLM_MODEL_TEXT` / `CMO_LLM_MODEL_SCORE` / `CMO_LLM_MODEL_LYRICS`.

### UI layer (`src/app/main.py`)
Single 560-line Streamlit file. Navigation is driven by `st.session_state` with two top-level views: collection list and individual song detail. The app calls `init_db()` on every cold start and interacts with the database through direct SQLAlchemy sessions (not via a service layer). File uploads are saved to `data/uploads/`; OCR outputs go to `data/processed/`.

## Agent system (`.claude/agents/`)

This project uses specialized Claude Code subagents. Invoke them by name when the task matches their scope:

| Agent | Model | Use for |
|-------|-------|---------|
| `product-owner` | Opus 4.8 | Project strategy, roadmap, task delegation, domain questions (Polish church music) |
| `backend-engineer` | Sonnet 4.6 | SQLAlchemy models, Alembic migrations, service layer, query optimization |
| `ocr-engineer` | Sonnet 4.6 | Tesseract pipeline, OpenCV preprocessing, music21, MusicXML conversion |
| `ui-engineer` | Sonnet 4.6 | Streamlit pages/components, UX forms, navigation, file viewers |
| `qa-engineer` | Sonnet 4.6 | pytest tests, fixtures, coverage, edge cases |
| `devops-engineer` | Haiku 4.5 | Docker, GitHub Actions CI, Alembic setup, pre-commit hooks, backups |
| `code-reviewer` | Sonnet 4.6 | Code review, security audit, convention checks before merge |

Start a conversation with `product-owner` for strategic work and feature planning. Each agent's definition contains full project context so it can operate independently.

## Database migrations

**Alembic** (configured in `alembic.ini` with `render_as_batch=True` for SQLite) is the canonical
tool for schema changes. Run `poetry run alembic upgrade head` to apply all migrations.

The legacy `init_db()` in `src/database/database.py` (which uses `Base.metadata.create_all`)
is retained for rapid test setup and first-time startup — it quickly creates all tables without
running migration files. Use Alembic for **any new schema changes** going forward; `init_db()` is
not modified by new migrations.

Example workflow:
```bash
# After modifying src/database/models.py, generate a migration:
poetry run alembic revision --autogenerate -m "your_description"

# Apply it to development/production database:
poetry run alembic upgrade head

# Rollback one migration if needed:
poetry run alembic downgrade -1
```

## Key conventions

- **File types** are controlled by the `FileType` enum in `models.py` (`SCAN`, `PDF`, `MUSESCORE`, `XML`, `TEXT`, `OTHER`). File type detection in the UI uses `python-magic` (requires system `libmagic`).
- **Semantic file kinds** (`MusicFile.kind`) replace brittle filename prefixes — use enums like
  `SOURCE_SCAN`, `OMR_RAW`, `CORRECTED`, `FINAL`, `EDITABLE` for categorization.
- **Library root** (`CMO_LIBRARY_ROOT`, default `../church-music-library`) is the filesystem
  source of truth for piece storage (metadata, scores, texts, knowledge). SQLite (`church_music.db`)
  is a fast index. See plan in `docs/ROADMAP.md` and task #2 in the devops roadmap.
- **Cascade deletes** are set on `MusicPiece` → `files` and `usage_history`. Deleting a piece removes all its files and history. Tags are not cascaded (shared across pieces).
- **Line length**: 100 characters (Black/isort configured in `pyproject.toml`).
- **Python target**: 3.8+ syntax.
- The database file (`church_music.db`) is created in the working directory at runtime — not committed to the repo.
- System dependencies required locally: `tesseract-ocr` with `tesseract-ocr-pol` and `tesseract-ocr-eng` language packs, `poppler-utils` (pdf2image), `libmagic`. See `Dockerfile` for the canonical install commands.
- **LLM steps (2/4/5)** require the `google-genai` package plus a Gemini API key (`GEMINI_API_KEY` or `GOOGLE_API_KEY`, from Google AI Studio). When absent, `PipelineService.llm_available()` is `False`, the LLM buttons are disabled, and cascade steps 2/4/5 are skipped — OCR (1) and OMR (3) still run standalone.
