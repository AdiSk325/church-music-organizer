#!/usr/bin/env python3
"""CLI for repeatable pipeline quality monitoring.

Usage examples
--------------
Evaluate one piece and print its quality table::

    python scripts/eval_pipeline.py --piece 42

Evaluate all pieces and print an aggregate summary; exit 1 if any stage fails::

    python scripts/eval_pipeline.py --all

Same with a JSON dump for archival / diffing::

    python scripts/eval_pipeline.py --all --json reports/latest.json

Exit codes
----------
* 0 — all evaluated pieces have overall status ``ok`` or ``warn``.
* 1 — at least one piece has a ``fail`` stage, or ``--piece`` was not found.

This script reads only persisted data (ProcessingStep rows, MusicFile fields).
No Tesseract, Audiveris, or LLM calls are made.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so "src" is importable when the
# script is run directly (python scripts/eval_pipeline.py) from any cwd.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.database.database import get_db_session  # noqa: E402  (after path setup)
from src.database.models import MusicPiece  # noqa: E402
from src.evaluation.evaluator import (  # noqa: E402
    evaluate_piece,
    report_to_table_rows,
)
from src.evaluation.metrics import PipelineQualityReport  # noqa: E402

# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

_COL_W_LABEL = 38
_COL_W_STATUS = 8
_COL_W_DUR = 9


def _print_piece_report(report: PipelineQualityReport) -> None:
    """Print a human-readable quality table for one piece."""
    print()
    print(f"  Utwór : {report.piece_title}  (id={report.piece_id})")
    print(f"  Status: {report.overall_status.upper()}")
    print(
        f"  Etapy : {report.stages_ok}/{report.stages_total} ok  |  "
        f"End-to-end: {'TAK' if report.end_to_end_ok else 'NIE'}  |  "
        f"Czas: {report.total_duration_ms} ms"
    )
    print()
    header = (
        f"  {'Etap':<{_COL_W_LABEL}} {'Status':<{_COL_W_STATUS}} {'Czas ms':>{_COL_W_DUR}}  "
        "Uwagi"
    )
    print(header)
    print("  " + "-" * (len(header) - 2 + 20))

    for key, label, glyph, duration_ms, notes in report_to_table_rows(report):
        dur_str = str(duration_ms) if duration_ms is not None else "—"
        print(
            f"  {label:<{_COL_W_LABEL}} {glyph:<{_COL_W_STATUS}} {dur_str:>{_COL_W_DUR}}  {notes}"
        )
    print()


def _print_aggregate(reports: list[PipelineQualityReport]) -> None:
    """Print one summary row per piece with per-stage status glyphs."""
    keys = ["ocr", "clean_text", "omr", "analysis", "correct_score", "underlay"]
    key_short = {"ocr": "OCR", "clean_text": "TXT", "omr": "OMR",
                 "analysis": "ANA", "correct_score": "COR", "underlay": "UND"}

    # Header
    header_stages = "  ".join(f"{key_short[k]:>4}" for k in keys)
    print(f"\n  {'Tytuł':<40} {'Ogólny':<8}  {header_stages}")
    print("  " + "-" * 90)

    fail_count = 0
    for r in reports:
        stage_by_key = {s.key: s for s in r.stages}
        glyphs = []
        for k in keys:
            s = stage_by_key.get(k)
            raw = s.status if s else "missing"
            glyph_map = {"ok": " ok ", "warn": "WARN", "fail": "FAIL", "missing": " -  "}
            glyphs.append(glyph_map.get(raw, " ?  "))
        stages_str = "  ".join(f"{g:>4}" for g in glyphs)
        overall = r.overall_status.upper()
        title = (r.piece_title[:37] + "...") if len(r.piece_title) > 40 else r.piece_title
        print(f"  {title:<40} {overall:<8}  {stages_str}")
        if r.overall_status == "fail":
            fail_count += 1

    # Tally
    total = len(reports)
    ok_warn = sum(1 for r in reports if r.overall_status in ("ok", "warn"))
    print(f"\n  Podsumowanie: {ok_warn}/{total} bez błędów krytycznych. "
          f"Nieudane: {fail_count}.")
    if reports:
        e2e = sum(1 for r in reports if r.end_to_end_ok)
        print(f"  End-to-end ok: {e2e}/{total}.")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Ocena jakości potoku transkrypcji (Church Music Organizer).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--piece",
        metavar="ID",
        type=int,
        help="Oceń jeden utwór o podanym ID i wypisz szczegółowy raport.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Oceń wszystkie utwory i wypisz tabelę zbiorczą.",
    )
    p.add_argument(
        "--json",
        metavar="PATH",
        help="Zrzuć pełny raport (lub listę raportów) jako JSON do wskazanego pliku.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    reports: list[PipelineQualityReport] = []
    exit_code = 0

    with get_db_session() as db:
        if args.piece:
            try:
                r = evaluate_piece(db, args.piece)
            except ValueError as exc:
                print(f"Błąd: {exc}", file=sys.stderr)
                return 1
            _print_piece_report(r)
            reports = [r]
            if r.overall_status == "fail":
                exit_code = 1

        else:  # --all
            piece_ids = [row[0] for row in db.query(MusicPiece.id).all()]
            if not piece_ids:
                print("Brak utworów w bazie danych.")
                return 0
            for pid in piece_ids:
                try:
                    r = evaluate_piece(db, pid)
                    reports.append(r)
                except Exception as exc:  # pragma: no cover - defensive
                    print(f"  [WARN] Nie udało się ocenić piece_id={pid}: {exc}", file=sys.stderr)
            _print_aggregate(reports)
            if any(r.overall_status == "fail" for r in reports):
                exit_code = 1

    # Optional JSON dump (works independently of --piece / --all)
    if args.json and reports:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            reports[0].to_dict() if len(reports) == 1 else [r.to_dict() for r in reports]
        )
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Raport JSON zapisany: {json_path}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
