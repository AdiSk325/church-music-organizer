"""Quality-metrics evaluation harness for the transcription pipeline.

Public API
----------
* :class:`StageMetric`           — quality result for one pipeline stage.
* :class:`PipelineQualityReport` — aggregate report for all stages of a piece.
* :func:`evaluate_piece`         — build a report from persisted step rows.
* :func:`report_to_markdown`     — render as a Markdown table string.
* :func:`report_to_table_rows`   — compact list[tuple] for CLI / tabular display.

Threshold constants live in :mod:`src.evaluation.scorecard` and can be edited
there without touching any computation logic.
"""

from src.evaluation.evaluator import (
    evaluate_piece,
    report_to_markdown,
    report_to_table_rows,
)
from src.evaluation.metrics import PipelineQualityReport, StageMetric

__all__ = [
    "StageMetric",
    "PipelineQualityReport",
    "evaluate_piece",
    "report_to_markdown",
    "report_to_table_rows",
]
