"""Centralised, tunable thresholds that map raw stage metrics → quality status.

Each threshold is a named module-level constant so users can adjust them without
touching any logic.  Edit the constants here; the evaluator picks up changes
automatically on the next run.

Status levels (ordered worst → best): ``"fail"`` > ``"warn"`` > ``"ok"``
Stages with no DB row (or that were skipped) have status ``"missing"`` and are
excluded from the overall-status calculation.
"""

from __future__ import annotations

from typing import List, Optional

from src.evaluation.metrics import StageMetric

# ---------------------------------------------------------------------------
# Threshold constants — OCR stage
# ---------------------------------------------------------------------------

# Tesseract confidence score (0–100).
OCR_CONFIDENCE_OK = 60    # >= 60  → ok
OCR_CONFIDENCE_WARN = 40  # >= 40  → warn, else fail

# Alpha ratio: fraction of non-whitespace characters that are letters.
# Low values indicate garbage / symbol-heavy output (noise, page borders, etc.).
OCR_ALPHA_OK = 0.35    # >= 0.35 → ok
OCR_ALPHA_WARN = 0.20  # >= 0.20 → warn, else fail

# ---------------------------------------------------------------------------
# Threshold constants — score-analysis stage
# ---------------------------------------------------------------------------

# Key-detection confidence returned by music21 (0–1).
ANALYSIS_KEY_CONFIDENCE_OK = 0.50    # >= 0.50 → ok
ANALYSIS_KEY_CONFIDENCE_WARN = 0.30  # >= 0.30 → warn, else fail

# Fraction of the curated informative fields that are meaningfully populated (0–1).
ANALYSIS_COMPLETENESS_OK = 0.60    # >= 0.60 → ok
ANALYSIS_COMPLETENESS_WARN = 0.40  # >= 0.40 → warn, else fail

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATUS_ORDER = {"ok": 0, "warn": 1, "fail": 2, "missing": 3}


def _threshold_status(value: float, ok_threshold: float, warn_threshold: float) -> str:
    """Map a numeric value to ``"ok"`` / ``"warn"`` / ``"fail"`` via two thresholds."""
    if value >= ok_threshold:
        return "ok"
    if value >= warn_threshold:
        return "warn"
    return "fail"


def _worst(statuses: List[str]) -> str:
    """Return the highest-severity status from a list, ignoring ``"missing"``."""
    relevant = [s for s in statuses if s != "missing"]
    if not relevant:
        return "ok"
    return max(relevant, key=lambda s: _STATUS_ORDER.get(s, 0))


# ---------------------------------------------------------------------------
# Per-stage status computation
# ---------------------------------------------------------------------------


def compute_stage_status(
    key: str,
    metrics: dict,
    db_status: Optional[str],
) -> str:
    """Map a stage's raw DB status + computed metrics → quality status.

    Parameters
    ----------
    key:       Step key (``"ocr"``, ``"clean_text"``, … ``"underlay"``).
    metrics:   Dict returned by the corresponding ``compute_*_metrics`` function.
    db_status: ``step.status`` from the DB row (``"ok"`` | ``"skipped"`` | ``"error"``),
               or ``None`` when the row is absent.

    Returns
    -------
    ``"ok"`` | ``"warn"`` | ``"fail"`` | ``"missing"``
    """
    # No row or intentionally skipped → missing (not a failure of the step itself)
    if db_status is None or db_status == "skipped":
        return "missing"
    # Engine / LLM reported an error
    if db_status == "error":
        return "fail"
    # db_status == "ok" → apply metric thresholds for stages that have them
    if key == "ocr":
        return _ocr_status(metrics)
    if key == "analysis":
        return _analysis_status(metrics)
    # All other stages: if the DB says ok and no stage-specific threshold applies,
    # trust the persisted status.
    return "ok"


def _ocr_status(metrics: dict) -> str:
    """Derive OCR quality from confidence and alpha_ratio."""
    conf_status = _threshold_status(
        metrics.get("confidence", 0), OCR_CONFIDENCE_OK, OCR_CONFIDENCE_WARN
    )
    alpha_status = _threshold_status(
        metrics.get("alpha_ratio", 0.0), OCR_ALPHA_OK, OCR_ALPHA_WARN
    )
    return _worst([conf_status, alpha_status])


def _analysis_status(metrics: dict) -> str:
    """Derive analysis quality from key_confidence and completeness."""
    kc_status = _threshold_status(
        metrics.get("key_confidence", 0.0),
        ANALYSIS_KEY_CONFIDENCE_OK,
        ANALYSIS_KEY_CONFIDENCE_WARN,
    )
    comp_status = _threshold_status(
        metrics.get("completeness", 0.0),
        ANALYSIS_COMPLETENESS_OK,
        ANALYSIS_COMPLETENESS_WARN,
    )
    return _worst([kc_status, comp_status])


# ---------------------------------------------------------------------------
# Overall status aggregation
# ---------------------------------------------------------------------------


def compute_overall_status(stages: List[StageMetric]) -> str:
    """Return the worst status across all non-missing stages.

    If every stage is missing (nothing ran), returns ``"missing"``.
    """
    present_statuses = [s.status for s in stages if s.status != "missing"]
    if not present_statuses:
        return "missing"
    return max(present_statuses, key=lambda s: _STATUS_ORDER.get(s, 0))


def compute_end_to_end_ok(stage_map: dict) -> bool:
    """Return True when the pipeline produced a usable final artefact.

    Condition A (LLM pipeline completed): the ``underlay`` stage is present,
    status ``"ok"``, and produced a new file (``changed = True``).

    Condition B (LLM stages skipped, engine-only run): ``clean_text``,
    ``correct_score``, and ``underlay`` are all ``"missing"``, AND both
    ``omr`` and ``analysis`` stages finished with status ``"ok"``.

    ``stage_map`` is a dict[step_key → StageMetric].
    """
    underlay = stage_map.get("underlay")
    omr = stage_map.get("omr")
    analysis = stage_map.get("analysis")

    # Condition A
    if (
        underlay is not None
        and underlay.status == "ok"
        and underlay.metrics.get("changed", False)
    ):
        return True

    # Condition B — LLM stages were intentionally skipped
    llm_keys = ("clean_text", "correct_score", "underlay")
    llm_all_missing = all(
        stage_map.get(k) is None or stage_map[k].status == "missing" for k in llm_keys
    )
    omr_ok = omr is not None and omr.status == "ok"
    analysis_ok = analysis is not None and analysis.status == "ok"

    if llm_all_missing and omr_ok and analysis_ok:
        return True

    return False
