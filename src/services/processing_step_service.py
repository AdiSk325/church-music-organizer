"""Read access to the persisted pipeline step records (``processing_steps`` table).

The pipeline writes one append-only :class:`ProcessingStep` row per step run (see
``PipelineService``). The UI reads the **newest row per ``step_key``** to show the current
state of each stage, and can pull the full history of a single step on demand.
"""

import json
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from src.database.models import ProcessingStep

logger = logging.getLogger(__name__)


class ProcessingStepService:
    """Query helpers over the ``processing_steps`` audit trail."""

    @staticmethod
    def latest_by_key(db: Session, piece_id: int) -> Dict[str, ProcessingStep]:
        """Return the most recent step per ``step_key`` for a piece.

        Rows are append-only, so we walk them oldest→newest and keep the last seen for
        each key — leaving each key mapped to its current result.
        """
        rows = (
            db.query(ProcessingStep)
            .filter(ProcessingStep.music_piece_id == piece_id)
            .order_by(ProcessingStep.created_at, ProcessingStep.id)
            .all()
        )
        latest: Dict[str, ProcessingStep] = {}
        for row in rows:
            latest[row.step_key] = row
        return latest

    @staticmethod
    def history(db: Session, piece_id: int, step_key: str) -> List[ProcessingStep]:
        """Return all runs of one step for a piece, newest first."""
        return (
            db.query(ProcessingStep)
            .filter(
                ProcessingStep.music_piece_id == piece_id,
                ProcessingStep.step_key == step_key,
            )
            .order_by(ProcessingStep.created_at.desc(), ProcessingStep.id.desc())
            .all()
        )

    @staticmethod
    def data(step: Optional[ProcessingStep]) -> Optional[dict]:
        """Decode a step's ``data_json`` payload, tolerating missing/invalid JSON."""
        if step is None or not step.data_json:
            return None
        try:
            return json.loads(step.data_json)
        except (ValueError, TypeError):
            logger.warning(
                "ProcessingStep ma niepoprawny data_json (id=%s)", getattr(step, "id", None)
            )
            return None
