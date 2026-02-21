"""Step 01 — Ingestion tests.

Tests the first pipeline step: converting a PDF or image file into
per-page PNG images at a controlled DPI.

For each active test case in ``tests/fixtures/manifest.yaml``:
- run ``Ingester.run()`` from ``src.ocr.ingestion``
- assert expected page count, image quality, text-layer, DPI
- persist per-case and summary reports as JSON artifacts

All tests use the **current** implementation as-is; the goal is to
record a baseline and identify problems for improvement.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from src.ocr.ingestion import Ingester, IngestionReport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
REPORTS_DIR = ROOT / "tests" / "OMR" / "reports" / "step_01_ingestion"


# ---------------------------------------------------------------------------
# Test-case helpers (manifest / case.yaml loading)
# ---------------------------------------------------------------------------


def _load_manifest() -> list[dict]:
    """Load manifest.yaml and return list of active test case entries."""
    manifest_path = FIXTURES / "manifest.yaml"
    if not manifest_path.exists():
        return []
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return [
        tc for tc in data.get("test_cases", [])
        if tc.get("status") in ("active", "wip")
    ]


def _load_case(tc_entry: dict) -> tuple[dict, Path]:
    """Return (case_dict, fixture_dir) for a manifest entry."""
    fixture_dir = FIXTURES / tc_entry["path"]
    case_path = fixture_dir / "case.yaml"
    case = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    return case, fixture_dir


def _case_params():
    """Build pytest parametrize params from manifest."""
    manifest = _load_manifest()
    params = []
    for tc in manifest:
        case_id = tc["id"]
        fixture_dir = FIXTURES / tc["path"]
        case_path = fixture_dir / "case.yaml"
        source_name = ""
        if case_path.exists():
            case = yaml.safe_load(case_path.read_text(encoding="utf-8"))
            source_name = case.get("source", "")
        source_exists = (fixture_dir / source_name).exists() if source_name else False
        params.append(
            pytest.param(
                tc,
                id=case_id,
                marks=(
                    [] if source_exists
                    else [pytest.mark.skip(reason=f"Input file missing: {source_name}")]
                ),
            )
        )
    return params


# ---------------------------------------------------------------------------
# Shared runner — ingests a case and saves the report
# ---------------------------------------------------------------------------

_ingester = Ingester(dpi=300, cleanup=False)


def _run_ingestion(case: dict, fixture_dir: Path) -> IngestionReport:
    """Run ingestion via :class:`Ingester` and persist the report."""
    step = case.get("step_01_ingestion", {})
    source_path = fixture_dir / case.get("source", "")

    report = _ingester.run(
        source_path,
        case_id=case.get("id", "unknown"),
        pages_expected=step.get("expected_pages", 1),
        has_text_layer_expected=step.get("has_text_layer"),
    )

    # Save per-case report artifact
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report.save(REPORTS_DIR / f"{report.case_id}.json")

    return report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestion:
    """Run step-01 ingestion on every active test case and record results."""

    @pytest.mark.parametrize("tc_entry", _case_params())
    def test_ingestion_page_count(self, tc_entry: dict) -> None:
        """Ingest the source file and verify page count matches case.yaml."""
        case, fixture_dir = _load_case(tc_entry)
        report = _run_ingestion(case, fixture_dir)

        assert not report.errors, f"Ingestion errors: {report.errors}"
        assert report.pages_actual == report.pages_expected, (
            f"Expected {report.pages_expected} page(s), got {report.pages_actual}"
        )

    @pytest.mark.parametrize("tc_entry", _case_params())
    def test_ingestion_image_quality(self, tc_entry: dict) -> None:
        """All ingested pages should be sharp enough (Laplacian variance > 100)."""
        case, fixture_dir = _load_case(tc_entry)
        report = _run_ingestion(case, fixture_dir)

        assert report.page_results, "No page images produced"
        for pr in report.page_results:
            assert pr.is_readable, (
                f"Page {pr.page_number} not readable: "
                f"laplacian_variance={pr.laplacian_variance:.1f} (need >100)"
            )

    @pytest.mark.parametrize("tc_entry", _case_params())
    def test_ingestion_text_layer(self, tc_entry: dict) -> None:
        """For PDFs, text layer presence should match case.yaml expectation."""
        case, fixture_dir = _load_case(tc_entry)
        step = case.get("step_01_ingestion", {})
        expected = step.get("has_text_layer")

        if expected is None:
            pytest.skip("has_text_layer not specified in case.yaml")

        source = fixture_dir / case.get("source", "")
        if source.suffix.lower() != ".pdf":
            pytest.skip("Text layer check only applies to PDFs")

        report = _run_ingestion(case, fixture_dir)
        assert report.has_text_layer_actual == expected, (
            f"Text layer: expected={expected}, actual={report.has_text_layer_actual}"
        )

    @pytest.mark.parametrize("tc_entry", _case_params())
    def test_ingestion_image_dimensions(self, tc_entry: dict) -> None:
        """Ingested images should have reasonable dimensions (not tiny, not huge)."""
        case, fixture_dir = _load_case(tc_entry)
        report = _run_ingestion(case, fixture_dir)

        for pr in report.page_results:
            assert pr.width_px > 500, (
                f"Page {pr.page_number}: width={pr.width_px}px too small"
            )
            assert pr.height_px > 500, (
                f"Page {pr.page_number}: height={pr.height_px}px too small"
            )
            assert pr.width_px < 10000, (
                f"Page {pr.page_number}: width={pr.width_px}px unexpectedly large"
            )
            assert pr.height_px < 10000, (
                f"Page {pr.page_number}: height={pr.height_px}px unexpectedly large"
            )

    @pytest.mark.parametrize("tc_entry", _case_params())
    def test_ingestion_dpi_estimate(self, tc_entry: dict) -> None:
        """Estimated DPI should be at least 200 (minimum usable for OMR)."""
        case, fixture_dir = _load_case(tc_entry)
        report = _run_ingestion(case, fixture_dir)

        for pr in report.page_results:
            assert pr.estimated_dpi >= 200, (
                f"Page {pr.page_number}: estimated DPI={pr.estimated_dpi} "
                f"(need >=200 for OMR)"
            )


# ---------------------------------------------------------------------------
# Summary report — runs after all parametrized tests
# ---------------------------------------------------------------------------


def test_generate_summary_report() -> None:
    """Generate a combined summary report from all individual case reports.

    This test always passes — its purpose is to aggregate and persist
    the results for human review.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    case_reports = sorted(REPORTS_DIR.glob("*.json"))
    case_reports = [r for r in case_reports if r.name != "summary.json"]

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total_cases": len(case_reports),
        "passed": 0,
        "failed": 0,
        "cases": [],
    }

    for rp in case_reports:
        try:
            data = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        passed = data.get("passed", False)
        summary["passed" if passed else "failed"] += 1
        summary["cases"].append({
            "case_id": data.get("case_id"),
            "source_type": data.get("source_type"),
            "pages_expected": data.get("pages_expected"),
            "pages_actual": data.get("pages_actual"),
            "has_text_layer": data.get("has_text_layer_actual"),
            "readable": all(
                pr.get("is_readable", False)
                for pr in data.get("page_results", [])
            ),
            "passed": passed,
            "errors": data.get("errors", []),
        })

    summary_path = REPORTS_DIR / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        f"Step 01 summary: {summary['passed']}/{summary['total_cases']} passed"
        f" -> {summary_path}"
    )
