"""Ties metrics.py + scorecard.py together using the persisted pipeline data.

Public API
----------
* :func:`evaluate_piece`        — build a :class:`PipelineQualityReport` for one piece.
* :func:`report_to_markdown`    — render the report as a Markdown table (UI / logging).
* :func:`report_to_table_rows`  — compact list[tuple] for CLI / tabular rendering.

All functions operate on already-persisted data (ProcessingStep rows, MusicFile
fields) — no Tesseract, Audiveris, or LLM calls are made here.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from src.database.models import MusicFile, MusicPiece, ProcessingStep
from src.evaluation.metrics import (
    PipelineQualityReport,
    StageMetric,
    compute_analysis_metrics,
    compute_clean_text_metrics,
    compute_correct_score_metrics,
    compute_musicxml_structure,
    compute_ocr_metrics,
    compute_omr_metrics,
    compute_underlay_metrics,
)
from src.evaluation.scorecard import (
    compute_end_to_end_ok,
    compute_overall_status,
    compute_stage_status,
)
from src.services.pipeline_service import STEP_LABELS, STEP_SEQUENCE
from src.services.processing_step_service import ProcessingStepService

logger = logging.getLogger(__name__)

# Status → display glyph for CLI / Markdown output
_STATUS_GLYPH: Dict[str, str] = {
    "ok": "[ok]  ",
    "warn": "[WARN]",
    "fail": "[FAIL]",
    "missing": "[-]   ",
}


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


def evaluate_piece(db: Session, piece_id: int) -> PipelineQualityReport:
    """Build a :class:`PipelineQualityReport` for ``piece_id`` from persisted data.

    Parameters
    ----------
    db:       Active SQLAlchemy session (read-only; nothing is written).
    piece_id: Primary key of the :class:`MusicPiece` to evaluate.

    Returns
    -------
    :class:`PipelineQualityReport` — can be serialised with ``.to_dict()``.

    Raises
    ------
    ValueError: When ``piece_id`` does not exist in the database.
    """
    piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
    if piece is None:
        raise ValueError(f"MusicPiece id={piece_id} nie istnieje w bazie.")

    # Latest step per key (append-only → newest wins)
    latest: Dict[str, ProcessingStep] = ProcessingStepService.latest_by_key(db, piece_id)

    stages: List[StageMetric] = []
    stage_map: Dict[str, StageMetric] = {}

    for key in STEP_SEQUENCE:
        step: Optional[ProcessingStep] = latest.get(key)
        label = STEP_LABELS.get(key, key)
        present = step is not None
        db_status: Optional[str] = step.status if step else None
        duration_ms: Optional[int] = step.duration_ms if step else None
        data = ProcessingStepService.data(step)  # decoded data_json or None

        # ----------------------------------------------------------------
        # Compute stage-specific metrics
        # ----------------------------------------------------------------
        if key == "ocr":
            # Fetch the source file's extracted_text for alpha_ratio computation
            extracted_text: Optional[str] = None
            if step and step.source_file_id:
                src_file: Optional[MusicFile] = db.query(MusicFile).filter(
                    MusicFile.id == step.source_file_id
                ).first()
                if src_file:
                    extracted_text = src_file.extracted_text
            metrics = compute_ocr_metrics(data, extracted_text)

        elif key == "clean_text":
            metrics = compute_clean_text_metrics(data)

        elif key == "omr":
            metrics = compute_omr_metrics(
                output_file_id=step.output_file_id if step else None,
                duration_ms=duration_ms,
            )

        elif key == "analysis":
            metrics = compute_analysis_metrics(data)

        elif key == "correct_score":
            metrics = compute_correct_score_metrics(
                output_file_id=step.output_file_id if step else None,
                db_status=db_status,
                duration_ms=duration_ms,
            )

        elif key == "underlay":
            metrics = compute_underlay_metrics(
                output_file_id=step.output_file_id if step else None,
                report=step.report if step else None,
                duration_ms=duration_ms,
            )

        else:
            metrics = {}

        # Enrich file-producing stages with reference-free structural metrics of the
        # actual output document (validity, .mxl format, note/measure/part counts) so
        # raw OMR can be compared against the post-LLM result.
        if key in ("omr", "correct_score", "underlay"):
            metrics.update(_output_structure(db, step))

        # ----------------------------------------------------------------
        # Derive quality status from metrics + thresholds
        # ----------------------------------------------------------------
        quality_status = compute_stage_status(key, metrics, db_status)
        notes = _build_notes(key, metrics, quality_status, step)

        stage = StageMetric(
            key=key,
            label=label,
            status=quality_status,
            present=present,
            duration_ms=duration_ms,
            metrics=metrics,
            notes=notes,
        )
        stages.append(stage)
        stage_map[key] = stage

    # ----------------------------------------------------------------
    # Aggregate report fields
    # ----------------------------------------------------------------
    overall_status = compute_overall_status(stages)
    end_to_end_ok = compute_end_to_end_ok(stage_map)

    non_missing = [s for s in stages if s.status != "missing"]
    stages_ok = sum(1 for s in non_missing if s.status == "ok")
    stages_total = len(non_missing)

    total_ms = sum(s.duration_ms for s in stages if s.duration_ms is not None)

    return PipelineQualityReport(
        piece_id=piece_id,
        piece_title=piece.title or "(bez tytułu)",
        stages=stages,
        overall_status=overall_status,
        stages_ok=stages_ok,
        stages_total=stages_total,
        end_to_end_ok=end_to_end_ok,
        total_duration_ms=total_ms,
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def report_to_markdown(report: PipelineQualityReport) -> str:
    """Render the quality report as a Markdown table string.

    Suitable for logging, Streamlit ``st.markdown()``, or stdout printing.
    """
    lines = [
        f"## Raport jakości — {report.piece_title} (id={report.piece_id})\n",
        f"**Status ogólny:** {report.overall_status.upper()}  "
        f"| Etapy: {report.stages_ok}/{report.stages_total} ok  "
        f"| End-to-end: {'TAK' if report.end_to_end_ok else 'NIE'}  "
        f"| Czas łączny: {report.total_duration_ms} ms\n",
        "| Etap | Status | Czas (ms) | Metryki | Uwagi |",
        "|------|--------|-----------|---------|-------|",
    ]
    for s in report.stages:
        glyph = _STATUS_GLYPH.get(s.status, s.status)
        dur = str(s.duration_ms) if s.duration_ms is not None else "—"
        metrics_str = "; ".join(f"{k}={v}" for k, v in s.metrics.items())
        notes = s.notes.replace("|", "\\|")  # escape pipes inside Markdown cells
        lines.append(f"| {s.label} | {glyph} | {dur} | {metrics_str} | {notes} |")
    return "\n".join(lines)


def report_to_table_rows(report: PipelineQualityReport) -> List[tuple]:
    """Return a compact list of tuples for CLI / tabular rendering.

    Each tuple: ``(step_key, label, status_glyph, duration_ms_or_None, notes)``
    """
    rows = []
    for s in report.stages:
        glyph = _STATUS_GLYPH.get(s.status, s.status).strip()
        rows.append((s.key, s.label, glyph, s.duration_ms, s.notes))
    return rows


# ---------------------------------------------------------------------------
# Output-file structure loader (reference-free)
# ---------------------------------------------------------------------------


def _output_structure(db: Session, step: Optional[ProcessingStep]) -> dict:
    """Load a stage's produced MusicFile and return reference-free structure metrics.

    Returns an empty dict when there is no output file or it cannot be read; otherwise
    a dict with ``valid``, ``reason``, ``note_count``, ``measure_count``, ``part_count``
    plus ``is_mxl`` (True when the artefact is a compressed ``.mxl``).
    """
    if step is None or not step.output_file_id:
        return {}
    mf: Optional[MusicFile] = (
        db.query(MusicFile).filter(MusicFile.id == step.output_file_id).first()
    )
    if mf is None or not mf.file_path:
        return {}

    from pathlib import Path

    p = Path(mf.file_path)
    if not p.exists():
        return {}

    try:
        from src.llm.musicxml_validate import load_musicxml_text

        text = load_musicxml_text(str(p))
    except Exception as exc:
        logger.warning("evaluate: nie udało się wczytać pliku wyjściowego %s: %s", p, exc)
        return {}

    structure = compute_musicxml_structure(text)
    structure["is_mxl"] = p.suffix.lower() == ".mxl"
    return structure


# ---------------------------------------------------------------------------
# Internal note builder
# ---------------------------------------------------------------------------


def _build_notes(
    key: str,
    metrics: dict,
    quality_status: str,
    step: Optional[ProcessingStep],
) -> str:
    """Generate a short human-readable note for a stage, useful for warnings."""
    if quality_status == "missing":
        return "Etap nie został uruchomiony." if step is None else "Etap pominięty."

    parts: List[str] = []

    if key == "ocr":
        conf = metrics.get("confidence", 0)
        alpha = metrics.get("alpha_ratio", 0.0)
        if conf < 60:
            parts.append(f"Niska pewność OCR: {conf}%.")
        if alpha < 0.35:
            parts.append(f"Niski alpha_ratio: {alpha:.2f} (możliwy szum).")

    elif key == "analysis":
        kc = metrics.get("key_confidence", 0.0)
        comp = metrics.get("completeness", 0.0)
        if kc < 0.50:
            parts.append(f"Niska pewność tonacji: {kc:.2f}.")
        if comp < 0.60:
            parts.append(f"Niska kompletność analizy: {comp:.0%}.")

    elif key == "omr" and not metrics.get("produced_file"):
        parts.append("OMR nie wygenerował pliku MusicXML.")

    elif key == "underlay":
        syl = metrics.get("syllables_placed")
        if syl is not None:
            parts.append(f"Podłożono {syl} sylab.")
        if not metrics.get("changed"):
            parts.append("Nie wygenerowano nowego pliku.")

    if step and step.detail:
        # Append the engine's own one-line summary when no custom note was built
        if not parts:
            return step.detail
    return " ".join(parts) if parts else "OK."
