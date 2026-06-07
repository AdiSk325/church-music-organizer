"""Service layer — analyse a MusicXML file and persist the result."""

import json
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.analysis.score_analyzer import ScoreAnalyzer
from src.analysis.score_descriptor import ScoreDescriptor

logger = logging.getLogger(__name__)


class AnalysisService:
    """Analyse MusicXML scores and optionally persist results to the database."""

    def __init__(self):
        self._analyzer = ScoreAnalyzer()

    def analyze_file(self, file_path: str) -> Optional[ScoreDescriptor]:
        """Parse a MusicXML file and return a ScoreDescriptor.

        Args:
            file_path: Absolute or relative path to a .xml / .mxl file.

        Returns:
            ScoreDescriptor, or None if the file cannot be parsed.
        """
        from music21 import converter

        path = Path(file_path)
        if not path.exists():
            logger.error("File not found: %s", path)
            return None

        try:
            score = converter.parse(str(path))
        except Exception:
            logger.exception("Failed to parse MusicXML: %s", path)
            return None

        try:
            descriptor = self._analyzer.analyze(score, source_file=str(path))
            return descriptor
        except Exception:
            logger.exception("Analysis failed for: %s", path)
            return None

    def analyze_and_store(
        self,
        db: Session,
        file_id: int,
        file_path: str,
    ) -> Optional[dict]:
        """Analyse a MusicXML file and store the JSON result on the MusicFile record.

        Sets the `extracted_text` field on MusicFile to the narrative description
        and `ocr_confidence` to the key detection confidence (scaled 0–100).
        Caller is responsible for committing the session.

        Returns the descriptor as a dict, or None on failure.
        """
        from src.database.models import MusicFile

        descriptor = self.analyze_file(file_path)
        if descriptor is None:
            return None

        music_file: Optional[MusicFile] = (
            db.query(MusicFile).filter(MusicFile.id == file_id).first()
        )
        if music_file is None:
            logger.warning("MusicFile id=%d not found, cannot persist analysis", file_id)
            return descriptor.to_dict()

        # Store narrative in extracted_text; full JSON in a side field if available
        music_file.extracted_text = descriptor.narrative_description
        music_file.ocr_confidence = int(descriptor.key_confidence * 100)
        music_file.is_processed = 1
        db.flush()

        return descriptor.to_dict()
