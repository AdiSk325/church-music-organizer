"""Service layer for file management and OCR result persistence."""

import re
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session


class FileService:
    """Handles file upload storage and OCR result persistence."""

    @staticmethod
    def save_uploaded_file(
        piece_id: int,
        filename: str,
        file_data: bytes,
        upload_dir: str = "data/uploads",
        use_library: bool = False,
        piece: Optional[object] = None,
        kind: Optional[object] = None,
    ) -> str:
        """Save uploaded bytes to storage.

        When *use_library* is ``False`` (default) the file is saved under
        ``{upload_dir}/{piece_id}/{safe_filename}`` — legacy behaviour, fully
        backwards-compatible with existing callers and tests.

        When *use_library* is ``True`` the file is routed through
        :class:`~src.services.library_service.LibraryService` and placed in
        the appropriate sub-directory of the piece's library folder (the
        ``CMO_LIBRARY_ROOT`` tree).  In that mode *piece* (a ``MusicPiece``
        ORM instance) is required; *kind* (a ``MusicFileKind`` value) defaults
        to ``MusicFileKind.OTHER`` when omitted.

        The filename is sanitised to its basename only (strips path traversal
        sequences such as ``../``), and non-alphanumeric characters other than
        dots, hyphens and underscores are replaced with underscores.

        Args:
            piece_id: ID of the MusicPiece this file belongs to.
            filename: Original filename provided by the uploader.
            file_data: Raw bytes of the file content.
            upload_dir: Root directory for uploads (relative to CWD or absolute).
                Ignored when *use_library* is ``True``.
            use_library: Route the file through LibraryService instead of the
                legacy ``data/uploads/{piece_id}/`` path.
            piece: ``MusicPiece`` ORM instance — required when *use_library* is
                ``True``.
            kind: ``MusicFileKind`` value — used by LibraryService to choose the
                target sub-directory.  Defaults to ``MusicFileKind.OTHER`` when
                *use_library* is ``True`` and *kind* is ``None``.

        Returns:
            Path of the saved file as a string (relative to CWD when
            upload_dir is relative, or absolute when routed through
            LibraryService).

        Raises:
            ValueError: If the sanitised path resolves outside the intended
                directory (path-traversal guard), or if *use_library* is
                ``True`` but *piece* is ``None``.
        """
        if use_library:
            if piece is None:
                raise ValueError("piece must be provided when use_library=True")
            # Import lazily to avoid circular imports at module level
            from src.database.models import MusicFileKind  # noqa: PLC0415
            from src.services.library_service import LibraryService  # noqa: PLC0415

            effective_kind = kind if kind is not None else MusicFileKind.OTHER
            return LibraryService.place_file(piece, file_data, effective_kind, filename)

        # ------------------------------------------------------------------
        # Legacy behaviour — unchanged; existing tests continue to pass
        # ------------------------------------------------------------------
        dest_dir = Path(upload_dir) / str(piece_id)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Keep only the basename — drop any directory components
        safe_name = Path(filename).name

        # Replace characters outside the safe set with underscores
        safe_name = re.sub(r"[^\w.\-]", "_", safe_name)

        # Guard against names that collapsed to empty or just dots
        if not safe_name or safe_name.strip(".") == "":
            safe_name = "upload"

        dest = dest_dir / safe_name

        # Verify resolved path stays within upload_dir (guards against symlink attacks)
        if not str(dest.resolve()).startswith(str(Path(upload_dir).resolve())):
            raise ValueError(f"Unsafe upload path resolved outside upload_dir: {dest}")

        dest.write_bytes(file_data)
        return str(dest)

    @staticmethod
    def save_ocr_result(
        db: Session,
        file_id: int,
        extracted_text: str,
        confidence: int,
    ) -> None:
        """Persist OCR output on a MusicFile record (caller commits).

        Sets ``is_processed = 1`` alongside the text and confidence score.

        Args:
            db: Active SQLAlchemy session.
            file_id: Primary key of the MusicFile to update.
            extracted_text: Text extracted by OCR.
            confidence: OCR confidence score in the range 0–100.
        """
        from src.database.models import MusicFile  # avoid circular import at module level

        music_file: Optional[MusicFile] = (
            db.query(MusicFile).filter(MusicFile.id == file_id).first()
        )
        if music_file is not None:
            music_file.extracted_text = extracted_text
            music_file.ocr_confidence = confidence
            music_file.is_processed = 1
            db.flush()
