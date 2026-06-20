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
    from src.evaluation.reference_compare import compare_musicxml

    return compare_musicxml(str(ref_path), conv_path)


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
