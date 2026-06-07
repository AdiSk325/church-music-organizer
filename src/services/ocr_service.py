"""Orchestrates OCR processing and persists results via FileService."""

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.database.models import MusicFile
from src.ocr.sheet_music_ocr import SheetMusicOCR
from src.services.file_service import FileService

logger = logging.getLogger(__name__)


class OCRService:
    """Runs OCR on a MusicFile and persists the result."""

    def __init__(self):
        self._ocr = SheetMusicOCR()

    def process_file(self, db: Session, file_id: int) -> Optional[dict]:
        """Run OCR on MusicFile.file_path and save results.

        Returns dict with keys: text, confidence, has_music_notation, file_id
        Returns None if file not found or OCR fails.
        Caller must commit the session.

        Args:
            db: Active SQLAlchemy session.
            file_id: Primary key of the MusicFile to process.

        Returns:
            Dict with OCR results, or None on failure.
        """
        music_file: Optional[MusicFile] = db.query(MusicFile).filter(MusicFile.id == file_id).first()
        if music_file is None:
            logger.warning("OCRService: MusicFile id=%s not found", file_id)
            return None

        file_path = music_file.file_path
        if not Path(file_path).exists():
            logger.warning("OCRService: file not found on disk: %s", file_path)
            return None

        try:
            result = self._ocr.process_file(file_path)
        except Exception:
            logger.exception("OCRService: OCR failed for file_id=%s path=%s", file_id, file_path)
            return None

        # process_file może zwrócić listę (PDF wielostronicowy) lub dict
        if isinstance(result, list):
            # Połącz tekst z wszystkich stron
            combined_text = "\n\n--- Strona ---\n\n".join(
                page.get("text", "") for page in result
            )
            confidence = int(
                sum(page.get("confidence", 0) for page in result) / max(len(result), 1)
            )
            has_notation = any(page.get("has_music_notation", False) for page in result)
        else:
            combined_text = result.get("text", "")
            confidence = int(result.get("confidence", 0))
            has_notation = result.get("has_music_notation", False)

        FileService.save_ocr_result(db, file_id, combined_text, confidence)

        logger.info(
            "OCRService: processed file_id=%s confidence=%s has_notation=%s",
            file_id,
            confidence,
            has_notation,
        )
        return {
            "file_id": file_id,
            "text": combined_text,
            "confidence": confidence,
            "has_music_notation": has_notation,
        }
