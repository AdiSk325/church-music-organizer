"""Orchestrates OMR processing (PDF → MusicXML via Audiveris) and persists results."""

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.database.models import FileType, MusicFile
from src.ocr.pdf_to_musicxml import PdfToMusicXml, audiveris_available

logger = logging.getLogger(__name__)

# File types that can be fed to Audiveris OMR.
_SUPPORTED_TYPES = {FileType.PDF, FileType.SCAN}


class OMRService:
    """Run Audiveris OMR on a MusicFile and persist the resulting MusicXML.

    Usage::

        service = OMRService()
        if OMRService.is_available():
            result = service.process_file(db, file_id=42)
            if result and result["success"]:
                db.commit()
    """

    def __init__(self, output_dir: str = "data/processed"):
        """Initialise the service.

        Args:
            output_dir: Directory where Audiveris will write its MusicXML
                output.  Created automatically if it does not exist.
        """
        self._output_dir = output_dir
        self._converter = PdfToMusicXml()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Return True when Audiveris is installed and can be invoked.

        Used by the UI layer to show / hide the OMR button gracefully instead
        of raising an exception.
        """
        return audiveris_available()

    def process_file(self, db: Session, file_id: int) -> Optional[dict]:
        """Run Audiveris OMR on a MusicFile and save the resulting MusicXML.

        The generated MusicXML is persisted as a new ``MusicFile`` record
        (``FileType.XML``) attached to the same ``music_piece_id``.

        **The caller is responsible for committing the session** — this mirrors
        the convention used by ``OCRService`` / ``FileService``.

        Args:
            db: Active SQLAlchemy session.
            file_id: Primary key of the source ``MusicFile`` to process.
                     Must be of type ``PDF`` or ``SCAN``.

        Returns:
            On success::

                {
                    "success": True,
                    "file_id": <source file id>,
                    "music_piece_id": <int>,
                    "musicxml_path": "<absolute path to .mxl/.xml>",
                    "output_file_id": <new MusicFile id>,
                }

            On failure: ``None`` (or a dict with ``"success": False`` and
            ``"error": "<message>"`` when the source record exists but
            conversion failed).
        """
        # --- Locate source MusicFile record ---
        music_file: Optional[MusicFile] = (
            db.query(MusicFile).filter(MusicFile.id == file_id).first()
        )
        if music_file is None:
            logger.warning("OMRService: MusicFile id=%s not found", file_id)
            return None

        # --- Validate file type ---
        if music_file.file_type not in _SUPPORTED_TYPES:
            logger.warning(
                "OMRService: file_id=%s has unsupported type %s (expected PDF or SCAN)",
                file_id,
                music_file.file_type,
            )
            return {
                "success": False,
                "file_id": file_id,
                "error": (
                    f"Unsupported file type {music_file.file_type.value!r}. "
                    "OMR requires a PDF or SCAN file."
                ),
            }

        # --- Validate the file exists on disk ---
        src_path = Path(music_file.file_path)
        if not src_path.exists():
            logger.warning("OMRService: source file not on disk: %s", src_path)
            return {
                "success": False,
                "file_id": file_id,
                "error": f"Source file not found on disk: {src_path}",
            }

        # --- Run Audiveris ---
        logger.info(
            "OMRService: starting Audiveris for file_id=%s path=%s",
            file_id,
            src_path,
        )
        try:
            musicxml_path = self._converter.convert(
                input_path=str(src_path),
                output_dir=self._output_dir,
            )
        except Exception:
            logger.exception("OMRService: Audiveris raised an exception for file_id=%s", file_id)
            return {
                "success": False,
                "file_id": file_id,
                "error": "Audiveris raised an unexpected exception — see logs for details.",
            }

        if musicxml_path is None:
            logger.error("OMRService: Audiveris produced no output for file_id=%s", file_id)
            return {
                "success": False,
                "file_id": file_id,
                "error": "Audiveris completed but produced no MusicXML output.",
            }

        # --- Persist the generated MusicXML as a new MusicFile ---
        xml_path = Path(musicxml_path)
        output_record = MusicFile(
            music_piece_id=music_file.music_piece_id,
            file_path=str(xml_path),
            file_type=FileType.XML,
            original_filename=xml_path.name,
            file_size=xml_path.stat().st_size if xml_path.exists() else None,
            description="OMR output (Audiveris)",
            is_processed=1,
        )
        db.add(output_record)
        db.flush()  # populate output_record.id before returning

        logger.info(
            "OMRService: saved MusicXML as file_id=%s for music_piece_id=%s path=%s",
            output_record.id,
            music_file.music_piece_id,
            xml_path,
        )
        return {
            "success": True,
            "file_id": file_id,
            "music_piece_id": music_file.music_piece_id,
            "musicxml_path": str(xml_path),
            "output_file_id": output_record.id,
        }
