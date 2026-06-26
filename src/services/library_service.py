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
        - For each directory, reads ``piece.yaml`` (slug, difficulty, sources,
          usage_categories) and scans ``texts/translation_<lang>_<kind>.md``
          and ``knowledge/<category>_<slug>.md`` files.
        - Upserts: ``MusicPiece.slug``/difficulty, ``Source``, ``Translation``,
          ``UsageCategory`` (M2M), ``KnowledgeNote`` rows.
        - Does **not** overwrite ``title``/``composer`` from YAML — the DB is
          the source of truth for those fields; YAML is written *from* the DB.
        - Idempotent: repeated calls produce the same state with no duplicates.
          Natural keys used per entity:

          - ``Source``: ``(music_piece_id, source_type, url, label, event_name, ensemble)``
          - ``Translation``: ``(music_piece_id, language, kind)``
          - ``UsageCategory``: ``name`` (global); link: ``(piece_id, category_id)``
          - ``KnowledgeNote``: ``(music_piece_id, category, title)``

        Args:
            db: An active SQLAlchemy ``Session`` instance.

        Returns:
            Summary dict with keys ``"scanned"``, ``"updated"``, ``"sources"``,
            ``"translations"``, ``"categories"``, ``"knowledge"``.
        """
        # Import inside method to avoid circular import at module level
        from src.database.models import (  # noqa: PLC0415
            KnowledgeCategory,
            KnowledgeNote,
            MusicPiece,
            PieceUsageCategory,
            RightsStatus,
            Source,
            SourceType,
            Translation,
            TranslationKind,
            UsageCategory,
        )

        root = LibraryService.library_root()
        pieces_dir = root / "pieces"
        if not pieces_dir.exists():
            return {
                "scanned": 0,
                "updated": 0,
                "sources": 0,
                "translations": 0,
                "categories": 0,
                "knowledge": 0,
            }

        scanned = 0
        updated = 0
        sources_count = 0
        translations_count = 0
        categories_count = 0
        knowledge_count = 0
        dir_pattern = re.compile(r"^(\d{4})_(.+)$")
        # Pre-build set of valid KnowledgeCategory values for fast lookup
        _known_categories = {c.value for c in KnowledgeCategory}

        for entry in sorted(pieces_dir.iterdir()):
            if not entry.is_dir():
                continue
            match = dir_pattern.match(entry.name)
            if not match:
                continue

            piece_id = int(match.group(1))
            # Sanitise the slug taken from the directory name: a hand-crafted
            # directory like ``0001_../../evil`` would otherwise flow into
            # ``piece_dir()`` and escape library_root (path traversal). Same
            # normalisation as ``slugify`` so values stay consistent.
            slug_from_dir = re.sub(r"[^\w\-]", "-", match.group(2)).strip("-") or "slug"
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

            # ------------------------------------------------------------------
            # 1. Slug + difficulty sync
            # ------------------------------------------------------------------
            if piece.slug != slug_from_dir:
                piece.slug = slug_from_dir
                dirty = True

            difficulty_grade = yaml_data.get("difficulty_grade")
            # difficulty_grade is an Integer column; YAML may yield a non-int
            # (e.g. "moderate") which would corrupt the row on flush — skip it.
            if isinstance(difficulty_grade, int) and hasattr(piece, "difficulty_grade"):
                if piece.difficulty_grade != difficulty_grade:
                    piece.difficulty_grade = difficulty_grade
                    dirty = True

            difficulty_notes = yaml_data.get("difficulty_notes")
            if difficulty_notes is not None and hasattr(piece, "difficulty_notes"):
                if piece.difficulty_notes != difficulty_notes:
                    piece.difficulty_notes = difficulty_notes
                    dirty = True

            # ------------------------------------------------------------------
            # 2. Source upsert from piece.yaml
            # ------------------------------------------------------------------
            for src_dict in yaml_data.get("sources", []) or []:
                type_val = src_dict.get("type") or ""
                try:
                    source_type = SourceType(type_val)
                except ValueError:
                    logger.warning("Unknown source type %r in %s — skipping", type_val, yaml_path)
                    continue

                rights_val = src_dict.get("rights_status") or "unknown"
                try:
                    rights_status = RightsStatus(rights_val)
                except ValueError:
                    rights_status = RightsStatus.UNKNOWN

                src_url = src_dict.get("url")
                src_label = src_dict.get("label")
                src_event = src_dict.get("event_name")
                src_ensemble = src_dict.get("ensemble")

                existing_src = (
                    db.query(Source)
                    .filter(
                        Source.music_piece_id == piece_id,
                        Source.source_type == source_type,
                        Source.url == src_url,
                        Source.label == src_label,
                        Source.event_name == src_event,
                        Source.ensemble == src_ensemble,
                    )
                    .first()
                )
                if existing_src is None:
                    db.add(
                        Source(
                            music_piece_id=piece_id,
                            source_type=source_type,
                            url=src_url,
                            label=src_label,
                            rights_status=rights_status,
                            event_name=src_event,
                            ensemble=src_ensemble,
                        )
                    )
                    sources_count += 1
                    dirty = True
                elif existing_src.rights_status != rights_status:
                    existing_src.rights_status = rights_status
                    sources_count += 1
                    dirty = True

            # ------------------------------------------------------------------
            # 3. Translation upsert from texts/translation_<lang>_<kind>.md
            # ------------------------------------------------------------------
            texts_dir = entry / "texts"
            if texts_dir.exists():
                _tr_pattern = re.compile(r"^translation_([a-z]{2,5})_([a-z]+)\.md$")
                for text_file in sorted(texts_dir.iterdir()):
                    if not text_file.is_file():
                        continue
                    m = _tr_pattern.match(text_file.name)
                    if not m:
                        continue

                    lang = m.group(1)
                    kind_val = m.group(2)
                    try:
                        kind = TranslationKind(kind_val)
                    except ValueError:
                        logger.warning(
                            "Unknown TranslationKind %r in %s — skipping",
                            kind_val,
                            text_file,
                        )
                        continue

                    text_content = text_file.read_text(encoding="utf-8")

                    existing_tr = (
                        db.query(Translation)
                        .filter(
                            Translation.music_piece_id == piece_id,
                            Translation.language == lang,
                            Translation.kind == kind,
                        )
                        .first()
                    )
                    if existing_tr is None:
                        # Mark as primary if no other primary for this lang exists yet
                        already_primary = (
                            db.query(Translation)
                            .filter(
                                Translation.music_piece_id == piece_id,
                                Translation.language == lang,
                                Translation.is_primary.is_(True),
                            )
                            .count()
                        ) > 0
                        db.add(
                            Translation(
                                music_piece_id=piece_id,
                                language=lang,
                                kind=kind,
                                text=text_content,
                                source="reindex",
                                is_primary=(not already_primary),
                            )
                        )
                        translations_count += 1
                        dirty = True
                    elif existing_tr.text != text_content:
                        existing_tr.text = text_content
                        translations_count += 1
                        dirty = True

            # ------------------------------------------------------------------
            # 4. UsageCategory M2M upsert from piece.yaml
            # ------------------------------------------------------------------
            for cat_name in yaml_data.get("usage_categories", []) or []:
                if not cat_name:
                    continue
                uc = db.query(UsageCategory).filter(UsageCategory.name == cat_name).first()
                if uc is None:
                    uc = UsageCategory(name=cat_name)
                    db.add(uc)
                    # Newly created — cannot be linked yet; append directly.
                    piece.usage_categories.append(uc)
                    categories_count += 1
                    dirty = True
                else:
                    # Existing category — check association table to avoid duplicates.
                    link_exists = (
                        db.query(PieceUsageCategory)
                        .filter(
                            PieceUsageCategory.music_piece_id == piece_id,
                            PieceUsageCategory.usage_category_id == uc.id,
                        )
                        .first()
                    ) is not None
                    if not link_exists:
                        piece.usage_categories.append(uc)
                        categories_count += 1
                        dirty = True

            # ------------------------------------------------------------------
            # 5. KnowledgeNote upsert from knowledge/*.md
            # ------------------------------------------------------------------
            knowledge_dir = entry / "knowledge"
            if knowledge_dir.exists():
                for md_file in sorted(knowledge_dir.iterdir()):
                    if not md_file.is_file() or md_file.suffix != ".md":
                        continue

                    stem = md_file.stem  # e.g. "historical_historia-utworu"

                    # Parse category prefix from known enum values
                    cat_val: Optional[str] = None
                    for cv in _known_categories:
                        if stem.startswith(cv + "_"):
                            cat_val = cv
                            break

                    try:
                        note_category = (
                            KnowledgeCategory(cat_val) if cat_val else KnowledgeCategory.GENERAL
                        )
                    except ValueError:
                        note_category = KnowledgeCategory.GENERAL

                    # Parse "# Title\n\nbody" format written by write_knowledge()
                    content = md_file.read_text(encoding="utf-8")
                    if content.startswith("# "):
                        first_nl = content.find("\n")
                        if first_nl == -1:
                            note_title: Optional[str] = content[2:].strip()
                            body_md = ""
                        else:
                            note_title = content[2:first_nl].strip()
                            body_md = content[first_nl + 1 :].lstrip("\n")
                    else:
                        note_title = None
                        body_md = content

                    existing_note = (
                        db.query(KnowledgeNote)
                        .filter(
                            KnowledgeNote.music_piece_id == piece_id,
                            KnowledgeNote.category == note_category,
                            KnowledgeNote.title == note_title,
                        )
                        .first()
                    )
                    if existing_note is None:
                        db.add(
                            KnowledgeNote(
                                music_piece_id=piece_id,
                                category=note_category,
                                title=note_title,
                                body_md=body_md,
                            )
                        )
                        knowledge_count += 1
                        dirty = True
                    elif existing_note.body_md != body_md:
                        existing_note.body_md = body_md
                        knowledge_count += 1
                        dirty = True

            if dirty:
                updated += 1

        return {
            "scanned": scanned,
            "updated": updated,
            "sources": sources_count,
            "translations": translations_count,
            "categories": categories_count,
            "knowledge": knowledge_count,
        }
