"""Step 1 — Ingestion: convert PDF/image inputs to per-page PNG images.

This module provides standalone functionality for the first OMR pipeline
step.  It can be used from the CLI, from tests, or from any other caller.

Typical usage::

    from src.ocr.ingestion import Ingester

    ingester = Ingester()
    report = ingester.run("data/uploads/score.pdf")
    print(report.pages_actual, "pages ingested")

    # Or measure an already-existing image:
    page = ingester.measure_page("page_001.png", page_number=1)
    print(page.laplacian_variance)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    """Measured properties of a single ingested page image."""

    page_number: int
    image_path: str
    width_px: int = 0
    height_px: int = 0
    estimated_dpi: int = 0
    laplacian_variance: float = 0.0
    black_pixel_ratio: float = 0.0
    is_readable: bool = False  # laplacian_variance > 100


@dataclass
class IngestionReport:
    """Full ingestion report for one input file."""

    case_id: str
    source_path: str
    source_type: str  # "pdf" | "png" | "jpg" etc.
    timestamp: str = ""
    pages_expected: int = 0
    pages_actual: int = 0
    has_text_layer_expected: Optional[bool] = None
    has_text_layer_actual: Optional[bool] = None
    page_results: List[PageResult] = field(default_factory=list)
    page_image_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    passed: bool = False

    # -- serialisation helpers --

    def to_dict(self) -> dict:
        """Convert the full report tree to a plain dict."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: Path | str) -> Path:
        """Write the report as JSON to *path*."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def detect_text_layer(pdf_path: Path | str) -> bool:
    """Return ``True`` if the PDF contains an extractable text layer.

    Args:
        pdf_path: Path to a PDF file.

    Returns:
        ``True`` when at least one page has >10 characters of text.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        for page in doc:
            text = page.get_text().strip()
            if len(text) > 10:
                doc.close()
                return True
        doc.close()
        return False
    except Exception:
        return False


def measure_page(image_path: str | Path, page_number: int = 1) -> PageResult:
    """Read an image and compute quality metrics.

    Metrics computed:

    * **width_px / height_px** — pixel dimensions
    * **estimated_dpi** — heuristic estimate assuming A4-sized pages
    * **laplacian_variance** — sharpness indicator (>100 = readable)
    * **black_pixel_ratio** — fraction of dark pixels (ink density)

    Args:
        image_path: Path to a grayscale or colour image.
        page_number: 1-based page index (for labelling only).

    Returns:
        A :class:`PageResult` with all metrics populated.
    """
    image_path = str(image_path)
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return PageResult(page_number=page_number, image_path=image_path)

    h, w = img.shape[:2]

    # Laplacian variance — measure of sharpness / information content
    lap = cv2.Laplacian(img, cv2.CV_64F)
    lap_var = float(lap.var())

    # Black pixel ratio (assuming binary-ish image where ink is dark)
    black_ratio = float(np.sum(img < 128)) / (h * w) if h * w > 0 else 0.0

    # Estimate DPI from page dimensions (A4 = 210 × 297 mm)
    if h > w:
        dpi_est = int(round(h / 11.69))  # 297 mm ≈ 11.69 in
    else:
        dpi_est = int(round(w / 11.69))

    return PageResult(
        page_number=page_number,
        image_path=image_path,
        width_px=w,
        height_px=h,
        estimated_dpi=dpi_est,
        laplacian_variance=round(lap_var, 2),
        black_pixel_ratio=round(black_ratio, 4),
        is_readable=lap_var > 100,
    )


# ---------------------------------------------------------------------------
# Ingester — orchestrator
# ---------------------------------------------------------------------------


class Ingester:
    """Run step-1 ingestion: source file → page images + quality metrics.

    Args:
        dpi: Resolution to use when rendering PDF pages (default 300).
        output_dir: Directory for temporary page images (PDFs only).
            If ``None``, a ``_temp`` sibling dir next to the source is used.
        cleanup: Whether to delete temporary images after measurement
            (default ``False`` — keep them for downstream steps).
    """

    def __init__(
        self,
        dpi: int = 300,
        output_dir: str | Path | None = None,
        cleanup: bool = False,
    ) -> None:
        self.dpi = dpi
        self.output_dir = Path(output_dir) if output_dir else None
        self.cleanup = cleanup

    # -- public API ---------------------------------------------------------

    def run(
        self,
        source_path: str | Path,
        *,
        case_id: str = "",
        pages_expected: int = 0,
        has_text_layer_expected: bool | None = None,
    ) -> IngestionReport:
        """Ingest *source_path* and return a filled :class:`IngestionReport`.

        Args:
            source_path: Path to a PDF or image file.
            case_id: Optional identifier (used in reports).
            pages_expected: Expected page count from test case config.
            has_text_layer_expected: Expected text-layer presence (PDFs).

        Returns:
            An :class:`IngestionReport` with per-page quality metrics.
        """
        source_path = Path(source_path)
        suffix = source_path.suffix.lower()

        report = IngestionReport(
            case_id=case_id or source_path.stem,
            source_path=str(source_path),
            source_type=suffix.lstrip("."),
            timestamp=datetime.now().isoformat(timespec="seconds"),
            pages_expected=pages_expected,
            has_text_layer_expected=has_text_layer_expected,
        )

        if not source_path.exists():
            report.errors.append(f"Source file not found: {source_path}")
            return report

        # --- produce page images ---
        try:
            page_images = self._ingest(source_path, suffix)
            if suffix == ".pdf":
                report.has_text_layer_actual = detect_text_layer(source_path)
            else:
                report.has_text_layer_actual = False
        except Exception as exc:
            report.errors.append(f"Ingestion failed: {exc}")
            return report

        report.pages_actual = len(page_images)
        report.page_image_paths = list(page_images)

        # --- per-page metrics ---
        for i, img_path in enumerate(page_images):
            pr = measure_page(img_path, page_number=i + 1)
            report.page_results.append(pr)

        # --- optional cleanup ---
        if self.cleanup and suffix == ".pdf":
            self._cleanup_temp(source_path)

        # --- verdict ---
        pages_ok = report.pages_actual == report.pages_expected or pages_expected == 0
        all_readable = all(pr.is_readable for pr in report.page_results)
        text_layer_ok = (
            has_text_layer_expected is None
            or report.has_text_layer_actual == has_text_layer_expected
        )
        report.passed = pages_ok and all_readable and text_layer_ok and not report.errors

        return report

    # -- internal -----------------------------------------------------------

    def _ingest(self, source_path: Path, suffix: str) -> list[str]:
        """Return a list of page-image paths."""
        if suffix == ".pdf":
            from .preprocessing import ImagePreprocessor

            temp_dir = self.output_dir or source_path.parent / "_temp"
            preprocessor = ImagePreprocessor(output_dir=str(temp_dir))
            images = preprocessor.pdf_to_images(str(source_path), dpi=self.dpi)
            if not images:
                raise RuntimeError("pdf_to_images returned no pages")
            return images
        else:
            # Image input — the file itself is the single "page"
            return [str(source_path)]

    def _cleanup_temp(self, source_path: Path) -> None:
        """Remove temporary directory created during PDF ingestion."""
        import shutil

        temp_dir = self.output_dir or source_path.parent / "_temp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
