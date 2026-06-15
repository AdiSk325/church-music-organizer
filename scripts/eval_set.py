"""End-to-end reference-based evaluation of the pdf -> musicxml (OMR) pipeline.

For every piece in ``data/tests`` (pdf + ground-truth musicxml):
  1. run Audiveris on the pdf -> converted .mxl (cached in data/processed/eval/omr)
  2. validate the converted output (MuseScore-safe gate)
  3. compare converted vs reference with reference-based metrics
  4. write JSON + a Markdown report

Reference-based metrics (per piece):
  valid_musicxml   - converted output parses + passes strict validation
  note_recall      - min(conv,ref)/ref   (capped; under-detection)
  note_ratio       - conv/ref            (>1 => over-detection / spurious notes)
  measure_match    - |conv-ref| <= 1
  key_match        - SAME key signature in fifths (robust vs analyze('key'))
  ts_match         - same first time signature
  part_match       - same part count (note: closed scores reduce part count)
  overall_score    - 0.5*min(1,recall) + 0.2*key + 0.15*ts + 0.15*part

Run:  poetry run python scripts/eval_set.py
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Optional

TESTS = Path("data/tests")
OMR_OUT = Path("data/processed/eval/omr")
OUT = Path("data/processed/eval")


def extract(score) -> dict:
    parts = list(score.parts)
    notes = sum(1 for _ in score.flatten().notes)
    measures = max((len(list(p.getElementsByClass("Measure"))) for p in parts), default=0)
    flat = score.flatten()
    ts = [t.ratioString for t in flat.getElementsByClass("TimeSignature")]
    ks = list(flat.getElementsByClass("KeySignature"))
    fifths = None
    if ks:
        fifths = getattr(ks[0], "sharps", None)
    return {
        "parts": len(parts),
        "notes": notes,
        "measures": measures,
        "first_ts": ts[0] if ts else None,
        "fifths": fifths,
    }


def run_omr(pdf: Path) -> Optional[str]:
    """Run Audiveris (cached). Returns path to converted .mxl or None."""
    OMR_OUT.mkdir(parents=True, exist_ok=True)
    cached = OMR_OUT / f"{pdf.stem}.mxl"
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)
    from src.ocr.pdf_to_musicxml import PdfToMusicXml

    conv = PdfToMusicXml().convert(str(pdf), output_dir=str(OMR_OUT), timeout=420)
    return conv


def compare(ref_path: Path, conv_path: str) -> dict:
    from music21 import converter

    from src.llm.musicxml_validate import load_musicxml_text, validate_musicxml

    # Validity / format of the converted output
    is_mxl = Path(conv_path).suffix.lower() == ".mxl"
    valid = False
    valid_reason = None
    try:
        ok, reason, _score = validate_musicxml(load_musicxml_text(conv_path))
        valid, valid_reason = ok, reason
    except Exception as exc:
        valid_reason = f"load/validate error: {exc}"

    ref = converter.parse(str(ref_path))
    conv = converter.parse(conv_path)
    r = extract(ref)
    c = extract(conv)

    note_recall = min(c["notes"], r["notes"]) / r["notes"] if r["notes"] else 0.0
    note_ratio = c["notes"] / r["notes"] if r["notes"] else 0.0
    measure_match = abs(c["measures"] - r["measures"]) <= 1
    # No <key> element ≡ 0 fifths (no sharps/flats) — normalise None→0 so a missing key
    # signature is not falsely counted as a mismatch against a C-major/0-accidental ref.
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(TESTS.glob("*.pdf"))
    results = {}
    for pdf in pdfs:
        ref = pdf.with_suffix(".musicxml")
        if not ref.exists():
            print(f"[skip] brak referencji dla {pdf.name}", flush=True)
            continue
        print(f"\n=== {pdf.stem} ===", flush=True)
        rec: dict = {"piece": pdf.stem}
        t0 = time.time()
        try:
            conv = run_omr(pdf)
            rec["omr_seconds"] = round(time.time() - t0, 1)
            if not conv:
                rec["status"] = "omr_failed"
                print(f"  OMR FAILED ({rec['omr_seconds']}s)", flush=True)
            else:
                rec["converted"] = conv
                rec.update(compare(ref, conv))
                rec["status"] = "ok"
                print(
                    f"  omr={rec['omr_seconds']}s valid={rec['valid_musicxml']} "
                    f"mxl={rec['is_mxl']}",
                    flush=True,
                )
                print(
                    f"  notes ref={rec['ref']['notes']} conv={rec['conv']['notes']} "
                    f"recall={rec['note_recall']} ratio={rec['note_ratio']}",
                    flush=True,
                )
                print(
                    f"  parts {rec['ref']['parts']}/{rec['conv']['parts']} match={rec['part_match']}"
                    f" | measures {rec['ref']['measures']}/{rec['conv']['measures']} "
                    f"match={rec['measure_match']}",
                    flush=True,
                )
                print(
                    f"  key fifths {rec['ref']['fifths']}/{rec['conv']['fifths']} "
                    f"match={rec['key_match']} | ts {rec['ref']['first_ts']}/"
                    f"{rec['conv']['first_ts']} match={rec['ts_match']}",
                    flush=True,
                )
                print(f"  OVERALL={rec['overall_score']}", flush=True)
        except Exception as exc:
            rec["status"] = "error"
            rec["error"] = str(exc)
            rec["traceback"] = traceback.format_exc()
            print(f"  ERROR: {exc}", flush=True)
        results[pdf.stem] = rec

    out = OUT / "eval_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nZapisano wyniki do {out}", flush=True)


if __name__ == "__main__":
    main()
