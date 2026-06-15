"""Reference-based comparison of a generated score against a ground-truth MusicXML.

Shared by the evaluation scripts and the Song Detail UI: given a reference file (the
"target" — a clean ``.musicxml``/``.mxl`` either supplied for tests or hand-edited by the
user) and a candidate produced by the pipeline, compute reference-based quality metrics so
the user can see, concretely, what still needs improving.

Design notes
------------
* Key is compared by **key-signature fifths** (number of sharps/flats), not ``analyze('key')``
  — the latter is unreliable on modal/Renaissance music. A missing ``<key>`` ≡ 0 fifths.
* ``note_recall`` is capped at 1.0 (under-detection); ``note_ratio`` (>1 = over-detection)
  is reported separately so spurious extra notes are visible.
* ``measure_match`` allows ±1 measure (pickup/cover-page off-by-one).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def _extract(score) -> dict:
    """Structural facts used by the comparison metrics."""
    parts = list(score.parts)
    notes = sum(1 for _ in score.flatten().notes)
    measures = max((len(list(p.getElementsByClass("Measure"))) for p in parts), default=0)
    flat = score.flatten()
    ts = [t.ratioString for t in flat.getElementsByClass("TimeSignature")]
    keysigs = list(flat.getElementsByClass("KeySignature"))
    fifths = getattr(keysigs[0], "sharps", None) if keysigs else None
    return {
        "parts": len(parts),
        "notes": notes,
        "measures": measures,
        "first_ts": ts[0] if ts else None,
        "fifths": fifths,
    }


def compare_musicxml(reference_path: str, candidate_path: str) -> dict:
    """Compare a candidate score against a reference, returning reference-based metrics.

    Args:
        reference_path: Path to the ground-truth ``.musicxml``/``.mxl``.
        candidate_path: Path to the pipeline-produced ``.mxl``/``.xml``.

    Returns:
        A dict with ``valid_musicxml``, ``is_mxl``, ``ref``/``conv`` structure dicts,
        ``note_recall``, ``note_ratio``, ``measure_match``, ``key_match``, ``ts_match``,
        ``part_match`` and a weighted ``overall_score`` (0–1). On a hard failure returns
        ``{"error": "..."}``.
    """
    from music21 import converter

    from src.llm.musicxml_validate import load_musicxml_text, validate_musicxml

    # Validity / format of the candidate
    is_mxl = Path(candidate_path).suffix.lower() == ".mxl"
    valid = False
    valid_reason: Optional[str] = None
    try:
        ok, reason, _score = validate_musicxml(load_musicxml_text(candidate_path))
        valid, valid_reason = ok, reason
    except Exception as exc:
        valid_reason = f"Nie udało się wczytać/zwalidować kandydata: {exc}"

    try:
        ref = converter.parse(str(reference_path))
        conv = converter.parse(str(candidate_path))
    except Exception as exc:
        return {"error": str(exc), "valid_musicxml": valid, "valid_reason": valid_reason}

    r = _extract(ref)
    c = _extract(conv)

    note_recall = min(c["notes"], r["notes"]) / r["notes"] if r["notes"] else 0.0
    note_ratio = c["notes"] / r["notes"] if r["notes"] else 0.0
    measure_match = abs(c["measures"] - r["measures"]) <= 1
    ref_fifths = r["fifths"] if r["fifths"] is not None else 0
    conv_fifths = c["fifths"] if c["fifths"] is not None else 0
    key_match = ref_fifths == conv_fifths
    ts_match = r["first_ts"] is not None and r["first_ts"] == c["first_ts"]
    part_match = r["parts"] == c["parts"]
    overall = (
        min(1.0, note_recall) * 0.5
        + (0.2 if key_match else 0.0)
        + (0.15 if ts_match else 0.0)
        + (0.15 if part_match else 0.0)
    )

    return {
        "valid_musicxml": valid,
        "valid_reason": valid_reason,
        "is_mxl": is_mxl,
        "ref": r,
        "conv": c,
        "note_recall": round(note_recall, 3),
        "note_ratio": round(note_ratio, 3),
        "measure_match": measure_match,
        "key_match": key_match,
        "ts_match": ts_match,
        "part_match": part_match,
        "overall_score": round(overall, 3),
    }
