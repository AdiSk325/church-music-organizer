"""Unit tests for src/ocr/text_region_extractor.py.

All tests are synthetic (numpy/cv2 only) — no Tesseract call, no real files.
They are fast and deterministic.

Synthetic image layout
----------------------
A white-on-black image (H=200, W=400) is built with:
  * 5 horizontal staff lines: full-width, 2 px tall, at rows 40, 52, 64, 76, 88
  * 3 "text" rectangles: shorter width (≤40 px), at rows 120–135, 145–160, 165–180
    These simulate word-level letter blobs after binarisation.

After staff removal we expect:
  * The staff-line pixel rows are substantially reduced (>= 80% removed).
  * The text rectangles survive (>= 80% of their pixels remain).
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers to build the synthetic image
# ---------------------------------------------------------------------------

IMAGE_H = 200
IMAGE_W = 400

# Staff-line rows (inclusive start of each 2-px band) — must be < IMAGE_H
STAFF_ROW_STARTS = [40, 52, 64, 76, 88]  # 5 lines, spacing = 12 px
STAFF_LINE_HEIGHT = 2  # pixels tall

# Text blobs: (row_start, row_end, col_start, col_end)  — kept deliberately
# narrow (<= 20 px) so they are NOT picked up as "staff lines" by the long
# horizontal kernel (kernel_len = max(40, W//20) = 40 at W=400).
# Real letter strokes at 200 DPI are similarly short relative to page width.
TEXT_BLOBS = [
    (120, 136, 50, 70),    # 20 px wide, 16 px tall
    (145, 161, 100, 120),  # 20 px wide, 16 px tall
    (165, 181, 200, 220),  # 20 px wide, 16 px tall
]


def _make_synthetic_binary_inv() -> np.ndarray:
    """Return a uint8 array (H×W) with ink=255, background=0.

    This is the internal format used by the extractor (``THRESH_BINARY_INV``
    convention).  The staff lines are long full-width ink bands; text blobs
    are shorter ink rectangles.
    """
    img = np.zeros((IMAGE_H, IMAGE_W), dtype=np.uint8)

    # Draw full-width staff lines
    for r in STAFF_ROW_STARTS:
        img[r : r + STAFF_LINE_HEIGHT, :] = 255

    # Draw text blobs (shorter — won't survive the long-horizontal-kernel OPEN)
    for r0, r1, c0, c1 in TEXT_BLOBS:
        img[r0:r1, c0:c1] = 255

    return img


def _make_synthetic_bgr() -> np.ndarray:
    """Return a BGR image (H×W×3) matching the synthetic layout.

    Paper = white (255,255,255), ink = black (0,0,0) — as a real scan would be.
    The extractor should binarise this and produce the same logical layout.
    """
    bgr = np.full((IMAGE_H, IMAGE_W, 3), 255, dtype=np.uint8)  # white background

    # Dark (black) staff lines
    for r in STAFF_ROW_STARTS:
        bgr[r : r + STAFF_LINE_HEIGHT, :] = 0  # black

    # Dark (black) text blobs
    for r0, r1, c0, c1 in TEXT_BLOBS:
        bgr[r0:r1, c0:c1] = 0  # black

    return bgr


# ---------------------------------------------------------------------------
# Tests — _build_staff_mask
# ---------------------------------------------------------------------------


class TestBuildStaffMask:
    """The staff mask should cover the full-width lines but not the text blobs."""

    def test_staff_rows_have_high_mask_coverage(self):
        """At least 80 % of pixels in a staff-line row are detected."""
        from src.ocr.text_region_extractor import _build_staff_mask

        binary = _make_synthetic_binary_inv()
        mask = _build_staff_mask(binary)

        for r in STAFF_ROW_STARTS:
            # Check the first row of each staff-line band
            row_pixels = binary[r, :]
            mask_row = mask[r, :]
            # Only count pixels that are ink in the original
            ink_count = int(np.count_nonzero(row_pixels))
            if ink_count == 0:
                continue
            detected = int(np.count_nonzero(mask_row))
            fraction_detected = detected / ink_count
            assert fraction_detected >= 0.80, (
                f"Staff row {r}: only {fraction_detected:.1%} of ink pixels detected as staff"
            )

    def test_text_blobs_not_in_mask(self):
        """Short text rectangles must NOT be detected as staff lines."""
        from src.ocr.text_region_extractor import _build_staff_mask

        binary = _make_synthetic_binary_inv()
        mask = _build_staff_mask(binary)

        for r0, r1, c0, c1 in TEXT_BLOBS:
            blob_mask_pixels = int(np.count_nonzero(mask[r0:r1, c0:c1]))
            blob_total = (r1 - r0) * (c1 - c0)
            # At most 10 % of a text blob should appear in the staff mask.
            assert blob_mask_pixels / blob_total <= 0.10, (
                f"Text blob ({r0}:{r1},{c0}:{c1}): "
                f"{blob_mask_pixels}/{blob_total} pixels wrongly in staff mask"
            )


# ---------------------------------------------------------------------------
# Tests — _subtract_staff_lines
# ---------------------------------------------------------------------------


class TestSubtractStaffLines:
    """After subtraction, staff rows should be mostly blank; text rows intact."""

    def test_staff_rows_substantially_removed(self):
        """Staff-line pixels are >= 80 % removed after subtraction."""
        from src.ocr.text_region_extractor import _subtract_staff_lines

        binary = _make_synthetic_binary_inv()
        original_staff_pixels = sum(
            int(np.count_nonzero(binary[r : r + STAFF_LINE_HEIGHT, :]))
            for r in STAFF_ROW_STARTS
        )
        cleaned = _subtract_staff_lines(binary)
        remaining_staff_pixels = sum(
            int(np.count_nonzero(cleaned[r : r + STAFF_LINE_HEIGHT, :]))
            for r in STAFF_ROW_STARTS
        )

        assert original_staff_pixels > 0, "Synthetic image must have staff pixels"
        fraction_remaining = remaining_staff_pixels / original_staff_pixels
        assert fraction_remaining <= 0.20, (
            f"After subtraction {fraction_remaining:.1%} of staff pixels remain "
            "(expected ≤ 20 %)"
        )

    def test_text_blobs_survive(self):
        """At least 80 % of text-blob pixels survive staff removal."""
        from src.ocr.text_region_extractor import _subtract_staff_lines

        binary = _make_synthetic_binary_inv()
        cleaned = _subtract_staff_lines(binary)

        for r0, r1, c0, c1 in TEXT_BLOBS:
            original_count = int(np.count_nonzero(binary[r0:r1, c0:c1]))
            remaining_count = int(np.count_nonzero(cleaned[r0:r1, c0:c1]))
            if original_count == 0:
                continue
            survival_rate = remaining_count / original_count
            assert survival_rate >= 0.80, (
                f"Text blob ({r0}:{r1},{c0}:{c1}): only {survival_rate:.1%} survived removal"
            )


# ---------------------------------------------------------------------------
# Tests — _filter_tiny_components
# ---------------------------------------------------------------------------


class TestFilterTinyComponents:
    def test_removes_single_pixel_noise(self):
        """Isolated single pixels (area=1) are removed when min_area=2."""
        from src.ocr.text_region_extractor import _filter_tiny_components

        img = np.zeros((50, 50), dtype=np.uint8)
        img[10, 10] = 255  # single isolated pixel
        img[10, 12] = 255  # another isolated pixel (not 8-connected)

        filtered = _filter_tiny_components(img, min_area=2)

        assert np.count_nonzero(filtered) == 0, (
            "Single-pixel components should be removed by min_area=2"
        )

    def test_keeps_large_components(self):
        """A large rectangle (area >> min_area) is fully retained."""
        from src.ocr.text_region_extractor import _filter_tiny_components

        img = np.zeros((50, 50), dtype=np.uint8)
        img[10:25, 10:35] = 255  # 15×25 = 375 px rectangle

        filtered = _filter_tiny_components(img, min_area=5)

        original_count = int(np.count_nonzero(img))
        remaining_count = int(np.count_nonzero(filtered))
        assert remaining_count == original_count, (
            "Large component should be fully preserved"
        )

    def test_mixed_sizes_selective_removal(self):
        """Only the small component is removed when there is also a large one."""
        from src.ocr.text_region_extractor import _filter_tiny_components

        img = np.zeros((100, 100), dtype=np.uint8)
        img[5, 5] = 255                   # isolated pixel (area=1) → removed
        img[20:35, 20:50] = 255          # 15×30 = 450 px rectangle → kept

        filtered = _filter_tiny_components(img, min_area=5)

        assert filtered[5, 5] == 0, "Isolated pixel must be removed"
        assert np.count_nonzero(filtered[20:35, 20:50]) > 0, (
            "Large rectangle must survive"
        )


# ---------------------------------------------------------------------------
# Tests — extract_text_image  (end-to-end on synthetic BGR)
# ---------------------------------------------------------------------------


class TestExtractTextImage:
    """Integration test for the full pipeline using a synthetic BGR image."""

    def test_output_is_uint8_2d(self):
        """Output must be a 2-D uint8 array (no colour channels)."""
        from src.ocr.text_region_extractor import extract_text_image

        bgr = _make_synthetic_bgr()
        result = extract_text_image(bgr)

        assert result.ndim == 2, "Output should be grayscale (H×W)"
        assert result.dtype == np.uint8

    def test_output_shape_matches_input(self):
        """Output spatial dimensions must equal input dimensions."""
        from src.ocr.text_region_extractor import extract_text_image

        bgr = _make_synthetic_bgr()
        result = extract_text_image(bgr)

        assert result.shape == (IMAGE_H, IMAGE_W)

    def test_output_is_binary(self):
        """Output pixels must be exactly 0 or 255 (binary image)."""
        from src.ocr.text_region_extractor import extract_text_image

        bgr = _make_synthetic_bgr()
        result = extract_text_image(bgr)

        unique_vals = set(np.unique(result))
        assert unique_vals.issubset({0, 255}), (
            f"Expected only {{0, 255}} in output, got {unique_vals}"
        )

    def test_output_convention_white_background(self):
        """The dominant value should be 255 (white background)."""
        from src.ocr.text_region_extractor import extract_text_image

        bgr = _make_synthetic_bgr()
        result = extract_text_image(bgr)

        white_pixels = int(np.count_nonzero(result == 255))
        total = result.size
        assert white_pixels / total > 0.5, (
            "More than half of pixels should be white (background)"
        )

    def test_grayscale_input_accepted(self):
        """extract_text_image must accept a 2-D grayscale array without error."""
        from src.ocr.text_region_extractor import extract_text_image

        bgr = _make_synthetic_bgr()
        import cv2
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        result = extract_text_image(gray)

        assert result.ndim == 2
        assert result.shape == (IMAGE_H, IMAGE_W)

    def test_staff_rows_lighter_after_removal(self):
        """Rows that had staff lines should have more white (bg) pixels after removal.

        In the output (white-bg, black-text convention), staff rows in the
        *original* would have many black pixels; after removal they should be
        mostly white.
        """
        from src.ocr.text_region_extractor import extract_text_image

        bgr = _make_synthetic_bgr()
        result = extract_text_image(bgr)

        # Count black pixels (0) in staff rows — should be low after removal.
        black_in_staff = sum(
            int(np.count_nonzero(result[r : r + STAFF_LINE_HEIGHT, :] == 0))
            for r in STAFF_ROW_STARTS
        )
        total_staff_pixels = len(STAFF_ROW_STARTS) * STAFF_LINE_HEIGHT * IMAGE_W
        # Expect < 20 % residual black in staff rows
        assert black_in_staff / total_staff_pixels < 0.20, (
            f"Too many black pixels remain in staff rows: "
            f"{black_in_staff}/{total_staff_pixels} = "
            f"{black_in_staff/total_staff_pixels:.1%}"
        )


# ---------------------------------------------------------------------------
# Tests — staff_line_fraction  (diagnostic helper)
# ---------------------------------------------------------------------------


class TestStaffLineFraction:
    def test_returns_float_between_0_and_1(self):
        from src.ocr.text_region_extractor import staff_line_fraction

        bgr = _make_synthetic_bgr()
        frac = staff_line_fraction(bgr)
        assert isinstance(frac, float)
        assert 0.0 <= frac <= 1.0

    def test_higher_for_image_with_staff_lines(self):
        """An image with full-width staff lines should score higher than a blank image."""
        from src.ocr.text_region_extractor import staff_line_fraction

        staff_img = _make_synthetic_bgr()
        blank_img = np.full((IMAGE_H, IMAGE_W, 3), 255, dtype=np.uint8)  # all white

        frac_staff = staff_line_fraction(staff_img)
        frac_blank = staff_line_fraction(blank_img)

        assert frac_staff > frac_blank, (
            f"Staff image fraction ({frac_staff:.4f}) should exceed "
            f"blank image fraction ({frac_blank:.4f})"
        )
