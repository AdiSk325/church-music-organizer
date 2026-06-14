"""Before/after comparison: staff-line removal vs. original OCR on a sheet-music PDF.

Usage (from the project root):
    python scripts/compare_ocr.py [path/to/file.pdf]

Defaults to ``data/uploads/AveMaria_Arcadelt_2sys.pdf`` when no argument is given.

Output -- for each page and in aggregate:
  * character count (total chars)
  * alpha_chars    (number of alphabetic characters; main lyrics proxy)
  * Tesseract confidence (0-100)
  * alpha_ratio    (fraction of non-space chars that are letters; higher = cleaner)

Each variant is run ONCE; no loops.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path so the src package is importable
# when the script is run with plain ``python`` from any working directory.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.evaluation.metrics import _alpha_ratio  # noqa: E402
from src.ocr.sheet_music_ocr import SheetMusicOCR  # noqa: E402

# ---------------------------------------------------------------------------
# Default PDF
# ---------------------------------------------------------------------------
_DEFAULT_PDF = _PROJECT_ROOT / "data" / "uploads" / "AveMaria_Arcadelt_2sys.pdf"


def _alpha_chars(text: str) -> int:
    """Return the count of alphabetic characters in *text*."""
    return sum(1 for c in text if c.isalpha())


def _summarise(pages: list[dict], label: str) -> tuple[str, int, int, float, float]:
    """Print per-page stats and return (all_text, chars, a_chars, conf, alpha)."""
    print("\n" + "=" * 64)
    print(f"  {label}")
    print("=" * 64)
    print(f"  {'Page':>4}  {'chars':>6}  {'a_chars':>7}  {'conf':>6}  {'alpha':>6}")
    print("  " + "-" * 38)

    total_chars = 0
    total_alpha_chars = 0
    total_conf_weighted = 0.0
    all_text = ""

    for page in pages:
        text = page.get("text", "")
        conf = page.get("confidence", 0)
        chars = len(text)
        a_ch = _alpha_chars(text)
        alpha = _alpha_ratio(text)
        all_text += text

        total_chars += chars
        total_alpha_chars += a_ch
        total_conf_weighted += conf

        page_no = page.get("page", "?")
        print(f"  {page_no:>4}  {chars:>6}  {a_ch:>7}  {conf:>6.1f}  {alpha:>6.3f}")

    n = max(len(pages), 1)
    agg_conf = total_conf_weighted / n
    agg_alpha = _alpha_ratio(all_text)

    print("  " + "-" * 38)
    print(
        f"  {'TOT':>4}  {total_chars:>6}  {total_alpha_chars:>7}  "
        f"{agg_conf:>6.1f}  {agg_alpha:>6.3f}"
    )
    return all_text, total_chars, total_alpha_chars, agg_conf, agg_alpha


def main(pdf_path: Path) -> None:
    print(f"PDF: {pdf_path}")

    if not pdf_path.exists():
        print(f"ERROR: file not found - {pdf_path}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # OLD: standard OCR, no staff removal
    # ------------------------------------------------------------------
    print("\nRunning OLD (no staff removal)...", flush=True)
    ocr_old = SheetMusicOCR(remove_staff_lines=False)
    pages_old = ocr_old.process_pdf(str(pdf_path))
    _old_text, chars_old, a_chars_old, conf_old, alpha_old = _summarise(
        pages_old, "OLD - original pipeline (no staff removal, PSM 3)"
    )

    # ------------------------------------------------------------------
    # NEW: staff removal enabled
    # ------------------------------------------------------------------
    print("\nRunning NEW (staff removal ON)...", flush=True)
    ocr_new = SheetMusicOCR(remove_staff_lines=True)
    pages_new = ocr_new.process_pdf(str(pdf_path))
    _new_text, chars_new, a_chars_new, conf_new, alpha_new = _summarise(
        pages_new, "NEW - staff removal + PSM 6"
    )

    # ------------------------------------------------------------------
    # Delta summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("  DELTA (NEW - OLD)")
    print("=" * 64)
    print(f"  chars      : {chars_old:>5} -> {chars_new:>5}  ({chars_new - chars_old:+d})")
    print(
        f"  alpha_chars: {a_chars_old:>5} -> {a_chars_new:>5}  ({a_chars_new - a_chars_old:+d})"
    )
    print(f"  conf       : {conf_old:>5.1f} -> {conf_new:>5.1f}  ({conf_new - conf_old:+.1f})")
    print(
        f"  alpha_ratio: {alpha_old:.3f} -> {alpha_new:.3f}  ({alpha_new - alpha_old:+.3f})"
    )

    # Primary improvement signal: more alphabetic characters = more lyrics recovered.
    # alpha_ratio difference within 3 pp is considered noise for this scan quality.
    alpha_chars_delta = a_chars_new - a_chars_old
    alpha_ratio_delta = alpha_new - alpha_old

    if alpha_chars_delta > 0 and alpha_ratio_delta >= -0.03:
        verdict = "NEW is BETTER: more lyrics recovered, alpha_ratio within noise"
    elif alpha_ratio_delta > 0.03:
        verdict = "NEW is BETTER: higher alpha_ratio"
    elif alpha_ratio_delta < -0.05:
        verdict = "NEW is WORSE: noticeably lower alpha_ratio"
    else:
        verdict = "roughly equivalent"

    print(f"\n  VERDICT: {verdict}")
    print()


if __name__ == "__main__":
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_PDF
    main(pdf)
