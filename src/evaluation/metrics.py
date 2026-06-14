"""Pure-function quality metrics for each pipeline stage.

No database access — callers load the necessary objects (ProcessingStep rows,
MusicFile.extracted_text) and pass them in. This keeps the module fully
testable without a real DB session or any heavy dependencies.

Public surface
--------------
* :class:`StageMetric`         — computed quality result for one stage.
* :class:`PipelineQualityReport` — aggregate report for all stages of a piece.
* ``compute_ocr_metrics``      — metrics dict for the OCR stage.
* ``compute_clean_text_metrics`` — metrics dict for the clean-text stage.
* ``compute_omr_metrics``      — metrics dict for the OMR stage.
* ``compute_analysis_metrics`` — metrics dict for the score-analysis stage.
* ``compute_correct_score_metrics`` — metrics dict for the correction stage.
* ``compute_underlay_metrics`` — metrics dict for the underlay stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StageMetric:
    """Quality result for one pipeline stage.

    Parameters
    ----------
    key:         step_key (e.g. ``"ocr"``, ``"analysis"``).
    label:       Human-readable step label shown to the user.
    status:      ``"ok"`` | ``"warn"`` | ``"fail"`` | ``"missing"``.
    present:     True when at least one :class:`ProcessingStep` row exists for this stage.
    duration_ms: Wall-clock time of the step in milliseconds (None if unavailable).
    metrics:     Dict of stage-specific measurement values (raw numbers / booleans).
    notes:       Short human-readable note (e.g. source of a warning).
    """

    key: str
    label: str
    status: str  # "ok" | "warn" | "fail" | "missing"
    present: bool
    duration_ms: Optional[int]
    metrics: Dict
    notes: str


@dataclass
class PipelineQualityReport:
    """Aggregate quality report for all pipeline stages of a single music piece.

    ``to_dict()`` serialises the report to a plain dict suitable for JSON archival.
    """

    piece_id: int
    piece_title: str
    stages: List[StageMetric]
    overall_status: str  # worst non-missing stage status; "missing" if nothing ran
    stages_ok: int
    stages_total: int  # number of non-missing stages
    end_to_end_ok: bool
    total_duration_ms: int

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON archival / diffing."""
        return {
            "piece_id": self.piece_id,
            "piece_title": self.piece_title,
            "overall_status": self.overall_status,
            "stages_ok": self.stages_ok,
            "stages_total": self.stages_total,
            "end_to_end_ok": self.end_to_end_ok,
            "total_duration_ms": self.total_duration_ms,
            "stages": [
                {
                    "key": s.key,
                    "label": s.label,
                    "status": s.status,
                    "present": s.present,
                    "duration_ms": s.duration_ms,
                    "metrics": s.metrics,
                    "notes": s.notes,
                }
                for s in self.stages
            ],
        }


# ---------------------------------------------------------------------------
# Analysis completeness — curated set of informative ScoreDescriptor fields
# ---------------------------------------------------------------------------

# Fields from ScoreDescriptor.to_dict() that carry meaningful analytic information.
# Metadata (title/composer/source_file) and raw numeric accumulators are intentionally
# excluded — we want to measure how much the analyser *understood* the score.
_ANALYSIS_INFORMATIVE_FIELDS: List[str] = [
    "detected_key",
    "key_confidence",
    "mode",
    "time_signatures",
    "voice_count",
    "voice_names",
    "measure_count",
    "texture_type",
    "harmony_epoch",
    "form_type",
    "text_setting_type",
    "estimated_grade",
    "grade_label",
    "voice_ranges",
    "harmonic_rhythm",
]

# Values that indicate a field was not meaningfully populated by the analyser.
_EMPTY_STRING_VALUES = frozenset({"unknown", "none", "n/a", ""})


def _is_meaningful(value: object) -> bool:
    """Return True when a descriptor field contains usable analysis output.

    Rules (in order):
    * None → False
    * bool  → always True  (False is valid information: "no lyrics", "no repetition")
    * str   → True only if non-empty and not in ``_EMPTY_STRING_VALUES``
    * int / float → True only when non-zero
    * list  → True only when non-empty
    * other → bool(value)
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, str):
        return value.lower().strip() not in _EMPTY_STRING_VALUES
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, list):
        return len(value) > 0
    return bool(value)


def _analysis_completeness(data: dict) -> float:
    """Fraction of the curated informative fields that are meaningfully populated (0–1)."""
    if not data:
        return 0.0
    meaningful = sum(
        1 for f in _ANALYSIS_INFORMATIVE_FIELDS if _is_meaningful(data.get(f))
    )
    return round(meaningful / len(_ANALYSIS_INFORMATIVE_FIELDS), 3)


# ---------------------------------------------------------------------------
# Alpha-ratio helper (OCR text quality)
# ---------------------------------------------------------------------------


def _alpha_ratio(text: Optional[str]) -> float:
    """Return the fraction of non-space characters that are letters.

    A low ratio (close to 0) indicates garbage / symbol-heavy OCR output.
    Returns 0.0 for empty or whitespace-only text.
    """
    if not text:
        return 0.0
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return 0.0
    alpha_count = sum(1 for c in non_space if c.isalpha())
    return round(alpha_count / len(non_space), 3)


# ---------------------------------------------------------------------------
# Underlay syllable parser
# ---------------------------------------------------------------------------

_SYLLABLE_RE = re.compile(r"Pod[łl]o[zż]ono\s+(\d+)\s+sylab", re.IGNORECASE)


def _parse_syllables_placed(report: Optional[str]) -> Optional[int]:
    """Parse the syllable count from an underlay step report.

    Looks for the phrase ``"Podłożono N sylab"`` (case-insensitive, tolerant
    of ASCII fallback ``Podlozono``).  Returns None when the phrase is absent.
    """
    if not report:
        return None
    m = _SYLLABLE_RE.search(report)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Per-stage metrics computation
# ---------------------------------------------------------------------------


def compute_ocr_metrics(data: Optional[dict], extracted_text: Optional[str]) -> dict:
    """Compute quality metrics for the OCR stage.

    Parameters
    ----------
    data:           Decoded ``data_json`` of the OCR :class:`ProcessingStep`.
    extracted_text: ``MusicFile.extracted_text`` of the source file that was OCR'd.
                    Used to compute ``alpha_ratio`` independently of what the engine
                    stored in ``data_json``.

    Returns
    -------
    dict with keys: ``confidence`` (int 0–100), ``char_count`` (int),
    ``alpha_ratio`` (float 0–1), ``has_music_notation`` (bool).
    """
    d = data or {}
    confidence = int(d.get("confidence") or 0)
    char_count = int(d.get("chars") or 0)
    has_notation = bool(d.get("has_music_notation", False))
    alpha = _alpha_ratio(extracted_text)
    return {
        "confidence": confidence,
        "char_count": char_count,
        "alpha_ratio": alpha,
        "has_music_notation": has_notation,
    }


def compute_clean_text_metrics(data: Optional[dict]) -> dict:
    """Compute quality metrics for the LLM text-cleaning stage.

    Returns
    -------
    dict with keys: ``language`` (str or None), ``lyrics_len`` (int).
    """
    d = data or {}
    language = d.get("language") or None
    lyrics = d.get("lyrics") or ""
    return {
        "language": language,
        "lyrics_len": len(lyrics),
    }


def compute_omr_metrics(output_file_id: Optional[int], duration_ms: Optional[int]) -> dict:
    """Compute quality metrics for the OMR stage.

    Returns
    -------
    dict with keys: ``produced_file`` (bool), ``duration_ms`` (int or None).
    """
    return {
        "produced_file": output_file_id is not None,
        "duration_ms": duration_ms,
    }


def compute_analysis_metrics(data: Optional[dict]) -> dict:
    """Compute quality metrics for the score-analysis stage.

    Returns
    -------
    dict with keys: ``key`` (str or None), ``key_confidence`` (float),
    ``voice_count`` (int), ``completeness`` (float 0–1).
    """
    d = data or {}
    key_name = d.get("detected_key") or None
    key_confidence = float(d.get("key_confidence") or 0.0)
    voice_count = int(d.get("voice_count") or 0)
    completeness = _analysis_completeness(d)
    return {
        "key": key_name,
        "key_confidence": key_confidence,
        "voice_count": voice_count,
        "completeness": completeness,
    }


def compute_correct_score_metrics(
    output_file_id: Optional[int],
    db_status: Optional[str],
    duration_ms: Optional[int],
) -> dict:
    """Compute quality metrics for the LLM score-correction stage.

    ``changed`` — True when the LLM produced a new MusicFile (corrected XML).
    ``accepted`` — True when the step finished with status ``"ok"`` (validation passed).
    """
    return {
        "changed": output_file_id is not None,
        "accepted": db_status == "ok",
        "duration_ms": duration_ms,
    }


def compute_underlay_metrics(
    output_file_id: Optional[int],
    report: Optional[str],
    duration_ms: Optional[int],
) -> dict:
    """Compute quality metrics for the LLM lyric-underlay stage.

    ``changed``          — True when a final MusicFile was produced.
    ``syllables_placed`` — Integer parsed from ``"Podłożono N sylab"`` in report, or None.
    ``duration_ms``      — Step wall-clock time.
    """
    return {
        "changed": output_file_id is not None,
        "syllables_placed": _parse_syllables_placed(report),
        "duration_ms": duration_ms,
    }
