"""Service layer for filesystem library layout management.

The library lives outside the repository in a directory configured via
``CMO_LIBRARY_ROOT`` (defaults to ``../church-music-library`` next to the repo).

Design contract
---------------
- **Filesystem = source of truth.**  Every mutation first writes to the FS
  (``piece.yaml`` + files), then the caller updates the SQLite index in the
  same operation (write-through).
- **``reindex_from_fs``** scans the library root and upserts the SQLite index
  — used for recovery and to pick up manual edits.
- All path operations resolve symlinks and verify the result stays inside the
  intended directory (path-traversal guard, same approach as ``FileService``).

Library layout::

    church-music-library/
      pieces/
        0001_ave-maria-arcadelt/
          piece.yaml          # canonical metadata (human + AI readable)
          sources/            # original scans / PDFs
          scores/             # MusicXML / mxl / mscz (versioned)
          texts/              # lyrics.md, translation_<lang>_<kind>.md
          knowledge/          # knowledge notes (.md)
          derived/            # raw OMR output, intermediate artefacts
      composers/              # (future — skeleton, not populated here)
"""

import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Polish character transliteration table
# ---------------------------------------------------------------------------

_PL_CHARS: Dict[str, str] = {
    "ą": "a",
    "ć": "c",
    "ę": "e",
    "ł": "l",
    "ń": "n",
    "ó": "o",
    "ś": "s",
    "ź": "z",
    "ż": "z",
    "Ą": "A",
    "Ć": "C",
    "Ę": "E",
    "Ł": "L",
    "Ń": "N",
    "Ó": "O",
    "Ś": "S",
    "Ź": "Z",
    "Ż": "Z",
}

# Sub-directory names for MusicFileKind groups
_KIND_TO_SUBDIR: Dict[str, str] = {
    "source_scan": "sources",
    "source_pdf": "sources",
    "omr_raw": "derived",
    "corrected": "scores",
    "final": "scores",
    "reference": "scores",
    "editable": "scores",
    "other": "derived",
}


class LibraryService:
    """Manages the library filesystem layout.

    All public methods are static — no instance state.  Callers obtain the
    canonical library root via :meth:`library_root` and then use the other
    helpers to interact with individual piece directories.
    """

    # ------------------------------------------------------------------
    # Root / directory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def library_root(create: bool = True) -> Path:
        """Return the library root ``Path``, creating it if absent.

        Reads ``CMO_LIBRARY_ROOT`` from the environment.  When the variable is
        not set the default is ``<repo_parent>/church-music-library`` (one level
        above the repository — keeps the library outside the repo). Pass
        ``create=False`` to compute the path with no filesystem side effects.
        """
        env_val = os.getenv("CMO_LIBRARY_ROOT")
        if env_val:
            root = Path(env_val)
        else:
            # src/services/library_service.py → src/services → src → project root → parent
            root = Path(__file__).resolve().parent.parent.parent.parent / "church-music-library"
        if create:
            root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def slugify(title: str) -> str:
        """Convert *title* to an ASCII-safe, lowercase, hyphen-separated slug.

        Handles Polish diacritics explicitly (``ą`` → ``a``, ``ł`` → ``l``,
        etc.) before stripping remaining non-ASCII via Unicode normalization.
        An empty or whitespace-only input returns ``"utwor"``.

        Examples::

            slugify("Ave Maria")           → "ave-maria"
            slugify("Alleluja – Śpiewnik") → "alleluja-spiewnik"
            slugify("Chwała na wysokości") → "chwala-na-wysokosci"
        """
        # 1. Replace Polish diacritics
        result = title
        for char, replacement in _PL_CHARS.items():
            result = result.replace(char, replacement)

        # 2. Strip remaining non-ASCII via NFKD normalisation
        result = unicodedata.normalize("NFKD", result)
        result = result.encode("ascii", "ignore").decode("ascii")

        # 3. Lowercase
        result = result.lower()

        # 4. Replace anything that is not alphanumeric or underscore with a hyphen
        result = re.sub(r"[^\w]", "-", result)

        # 5. Collapse consecutive hyphens / underscores → single hyphen
        result = re.sub(r"[-_]+", "-", result)

        # 6. Strip leading/trailing hyphens
        result = result.strip("-")

        return result or "utwor"

    @staticmethod
    def piece_dirname(piece_id: int, slug: str) -> str:
        """Return the directory name for a piece: ``0001_ave-maria``."""
        return f"{piece_id:04d}_{slug}"

    @staticmethod
    def piece_dir(piece: Any, create: bool = True) -> Path:
        """Return the piece's top-level library directory.

        When *create* is True (default), sub-directories ``sources/``,
        ``scores/``, ``texts/``, ``knowledge/`` and ``derived/`` are created so
        callers can write to any of them without extra checks. Pass
        ``create=False`` to only compute the path with no filesystem side
        effects (e.g. dry-run inspection).

        Args:
            piece: A :class:`~src.database.models.MusicPiece` ORM instance.
            create: Whether to create the directory tree on disk.

        Returns:
            Absolute path to the piece directory.
        """
        slug = piece.slug or LibraryService.slugify(piece.title)
        dirname = LibraryService.piece_dirname(piece.id, slug)
        piece_path = LibraryService.library_root(create=create) / "pieces" / dirname
        if create:
            for subdir in ("sources", "scores", "texts", "knowledge", "derived"):
                (piece_path / subdir).mkdir(parents=True, exist_ok=True)
        return piece_path

    # ------------------------------------------------------------------
    # YAML metadata serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def write_piece_yaml(piece: Any) -> Path:
        """Serialise canonical metadata to ``piece.yaml`` in the piece directory.

        The YAML file is the filesystem source of truth for human and AI edits.
        It stores the fields most likely to be edited outside the app (title,
        authors, difficulty, sources, categories, tags).

        Args:
            piece: A :class:`~src.database.models.MusicPiece` ORM instance.

        Returns:
            Absolute path to the written ``piece.yaml``.

        Raises:
            ImportError: If ``pyyaml`` is not installed.
        """
        import yaml  # type: ignore[import]

        data: Dict[str, Any] = {
            "id": piece.id,
            "title": piece.title,
            "slug": piece.slug,
            "composer": piece.composer,
            "arranger": piece.arranger,
            "lyrics_author": piece.lyrics_author,
            "music_author": piece.music_author,
            "harmony_author": piece.harmony_author,
            "key_signature": piece.key_signature,
            "time_signature": piece.time_signature,
            "difficulty_grade": (
                piece.difficulty_grade if hasattr(piece, "difficulty_grade") else None
            ),
            "difficulty_notes": (
                piece.difficulty_notes if hasattr(piece, "difficulty_notes") else None
            ),
            "occasion": piece.occasion,
            "liturgical_season": piece.liturgical_season,
            "language": piece.language,
            "sources": [
                {
                    "type": s.source_type.value if s.source_type else None,
                    "url": s.url,
                    "label": s.label,
                    "rights_status": (s.rights_status.value if s.rights_status else "unknown"),
                    "event_name": s.event_name,
                    "ensemble": s.ensemble,
                }
                for s in (piece.sources if hasattr(piece, "sources") else [])
            ],
            "tags": [t.name for t in (piece.tags if hasattr(piece, "tags") else [])],
            "usage_categories": [
                uc.name
                for uc in (piece.usage_categories if hasattr(piece, "usage_categories") else [])
            ],
            "updated_at": (piece.updated_at.isoformat() if piece.updated_at else None),
        }

        yaml_path = LibraryService.piece_dir(piece) / "piece.yaml"
        with open(yaml_path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return yaml_path

    @staticmethod
    def read_piece_yaml(path: Path) -> Dict[str, Any]:
        """Read ``piece.yaml`` and return its contents as a plain dict.

        Args:
            path: Absolute or relative path to a ``piece.yaml`` file.

        Returns:
            Parsed dictionary; empty dict if the file is empty.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ImportError: If ``pyyaml`` is not installed.
        """
        import yaml  # type: ignore[import]

        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------
    # File placement
    # ------------------------------------------------------------------

    @staticmethod
    def subdir_for_kind(kind: Any) -> str:  # kind: MusicFileKind
        """Map a ``MusicFileKind`` value to the target sub-directory name.

        +-----------------------------------+------------+
        | Kind                              | Sub-dir    |
        +===================================+============+
        | ``SOURCE_SCAN``, ``SOURCE_PDF``   | sources    |
        +-----------------------------------+------------+
        | ``CORRECTED``, ``FINAL``,         | scores     |
        | ``REFERENCE``, ``EDITABLE``       |            |
        +-----------------------------------+------------+
        | ``OMR_RAW``, ``OTHER``            | derived    |
        +-----------------------------------+------------+
        """
        value: str = kind.value if hasattr(kind, "value") else str(kind)
        return _KIND_TO_SUBDIR.get(value, "derived")

    @staticmethod
    def place_file(piece: Any, data: bytes, kind: Any, filename: str) -> str:
        """Write *data* to the appropriate sub-directory of the piece's library dir.

        Applies the same filename sanitisation and path-traversal guard as
        :meth:`~src.services.file_service.FileService.save_uploaded_file`.

        Args:
            piece: A :class:`~src.database.models.MusicPiece` ORM instance.
            data: Raw bytes of the file content.
            kind: A :class:`~src.database.models.MusicFileKind` value that
                determines the target sub-directory.
            filename: Original filename (only the basename is used; directory
                components are stripped before sanitisation).

        Returns:
            Absolute path to the written file as a string.

        Raises:
            ValueError: If the sanitised path would resolve outside the target
                directory (path-traversal attack prevention).
        """
        # Keep only the basename — drop any directory components
        safe_name = Path(filename).name

        # Replace characters outside the safe set with underscores
        safe_name = re.sub(r"[^\w.\-]", "_", safe_name)

        # Guard against names that collapsed to empty or just dots
        if not safe_name or safe_name.strip(".") == "":
            safe_name = "upload"

        subdir = LibraryService.subdir_for_kind(kind)
        dest_dir = LibraryService.piece_dir(piece) / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / safe_name

        # Verify resolved path stays within dest_dir (guards against symlink attacks).
        # Append os.sep so a sibling like ``/lib/foo-evil`` cannot pass as ``/lib/foo``.
        if not str(dest.resolve()).startswith(str(dest_dir.resolve()) + os.sep):
            raise ValueError(f"Unsafe upload path resolved outside target directory: {dest}")

        dest.write_bytes(data)
        return str(dest)

    # ------------------------------------------------------------------
    # Text and knowledge writing
    # ------------------------------------------------------------------

    @staticmethod
    def write_text(piece: Any, basename: str, md: str) -> Path:
        """Write Markdown text to the ``texts/`` sub-directory.

        Typical basenames: ``lyrics.md``,
        ``translation_pl_literal.md``, ``translation_en_singable.md``.

        Args:
            piece: A :class:`~src.database.models.MusicPiece` ORM instance.
            basename: Filename for the text file (basename only; sanitised).
            md: Markdown content to write.

        Returns:
            Absolute path to the written file.
        """
        texts_dir = LibraryService.piece_dir(piece) / "texts"
        texts_dir.mkdir(parents=True, exist_ok=True)

        safe_basename = re.sub(r"[^\w.\-]", "_", Path(basename).name) or "text.md"
        path = texts_dir / safe_basename
        path.write_text(md, encoding="utf-8")
        return path

    @staticmethod
    def write_knowledge(piece: Any, note: Any) -> Path:
        """Write a :class:`~src.database.models.KnowledgeNote` to ``knowledge/``.

        The filename is derived from the note's category and title so it is
        human-readable in a file manager.  The file contains the note title as
        a Markdown heading followed by ``body_md``.

        Args:
            piece: A :class:`~src.database.models.MusicPiece` ORM instance.
            note: A :class:`~src.database.models.KnowledgeNote` ORM instance.

        Returns:
            Absolute path to the written Markdown file.
        """
        knowledge_dir = LibraryService.piece_dir(piece) / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        category: str = note.category.value if note.category else "general"
        title_slug = LibraryService.slugify(note.title or "note")
        basename = f"{category}_{title_slug}.md"

        path = knowledge_dir / basename
        header = f"# {note.title}\n\n" if note.title else ""
        path.write_text(header + note.body_md, encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Re-index
    # ------------------------------------------------------------------

    @staticmethod
    def reindex_from_fs(db: Any) -> Dict[str, int]:
        """Scan the library filesystem and upsert the SQLite index.

        Contract
        --------
        - Scans ``library_root()/pieces/`` for directories matching the pattern
          ``<id:04d>_<slug>`` (e.g. ``0001_ave-maria``).
        - For each directory, reads ``piece.yaml`` if present.
        - Upserts the SQLite ``MusicPiece`` row: updates ``slug``,
          ``difficulty_grade`` and ``difficulty_notes`` from the YAML.
          Does **not** overwrite ``title``/``composer`` from YAML (the DB is
          the source of truth for those fields; the YAML is written *from* the
          DB by :meth:`write_piece_yaml`).
        - Returns a summary dict ``{"scanned": N, "updated": M}``.

        Note
        ----
        Full upsert logic (Source, Translation, UsageCategory rows) is deferred
        to a later task (qa-engineer / devops-engineer).  This implementation
        establishes the scanning loop, YAML parsing, and slug/difficulty sync.

        Args:
            db: An active SQLAlchemy ``Session`` instance.

        Returns:
            Summary dict with keys ``"scanned"`` and ``"updated"``.
        """
        # Import inside method to avoid circular import at module level
        from src.database.models import MusicPiece  # noqa: PLC0415

        root = LibraryService.library_root()
        pieces_dir = root / "pieces"
        if not pieces_dir.exists():
            return {"scanned": 0, "updated": 0}

        scanned = 0
        updated = 0
        dir_pattern = re.compile(r"^(\d{4})_(.+)$")

        for entry in sorted(pieces_dir.iterdir()):
            if not entry.is_dir():
                continue
            match = dir_pattern.match(entry.name)
            if not match:
                continue

            piece_id = int(match.group(1))
            slug_from_dir = match.group(2)
            scanned += 1

            yaml_data: Dict[str, Any] = {}
            yaml_path = entry / "piece.yaml"
            if yaml_path.exists():
                try:
                    yaml_data = LibraryService.read_piece_yaml(yaml_path)
                except Exception:  # noqa: BLE001
                    # malformed YAML — skip, do not crash the whole reindex
                    logger.warning("Skipping malformed piece.yaml: %s", yaml_path, exc_info=True)

            piece: Optional[Any] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
            if piece is None:
                continue  # orphaned FS directory — no matching DB row

            dirty = False

            if piece.slug != slug_from_dir:
                piece.slug = slug_from_dir
                dirty = True

            difficulty_grade = yaml_data.get("difficulty_grade")
            if difficulty_grade is not None and hasattr(piece, "difficulty_grade"):
                if piece.difficulty_grade != difficulty_grade:
                    piece.difficulty_grade = difficulty_grade
                    dirty = True

            difficulty_notes = yaml_data.get("difficulty_notes")
            if difficulty_notes is not None and hasattr(piece, "difficulty_notes"):
                if piece.difficulty_notes != difficulty_notes:
                    piece.difficulty_notes = difficulty_notes
                    dirty = True

            if dirty:
                updated += 1

        return {"scanned": scanned, "updated": updated}
