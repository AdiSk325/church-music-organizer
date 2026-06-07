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
    ) -> str:
        """Save uploaded bytes to data/uploads/{piece_id}/{safe_filename}.

        The filename is sanitised to its basename only (strips path traversal
        sequences such as ``../``), and non-alphanumeric characters other than
        dots, hyphens and underscores are replaced with underscores.

        Args:
            piece_id: ID of the MusicPiece this file belongs to.
            filename: Original filename provided by the uploader.
            file_data: Raw bytes of the file content.
            upload_dir: Root directory for uploads (relative to CWD or absolute).

        Returns:
            Path of the saved file as a string (relative to CWD when
            upload_dir is relative).
        """
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
