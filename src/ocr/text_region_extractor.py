"""Staff-line removal and text-region extraction for sheet-music OCR pre-processing.

The goal is to produce a clean binary image (white background, black text) from a raw
scan that contains both musical notation (staff lines, noteheads, stems) and lyric text.
Removing the five-line staves BEFORE Tesseract reduces symbol noise such as
``Ba = + p p = e p p 2 > p`` that the OCR engine emits when it tries to read staff lines.

Algorithm
---------
1. Convert BGR → grayscale if the input is a colour image.
2. Binarise with adaptive Gaussian threshold (``THRESH_BINARY_INV``): ink → 255 (white),
   paper → 0 (black).  This is the standard convention for morphological operations.
3. Detect staff lines by applying a *long* horizontal structuring element via
   ``cv2.morphologyEx(MORPH_OPEN)``.  Only pixels that belong to horizontal white runs
   at least *kernel_len* pixels wide survive the opening; short letter strokes vanish.
4. Subtract the staff-line mask from the binarised image.
5. Remove connected components that are smaller than *min_area* pixels (isolated dot
   noise, broken note stems, etc.).  This filter is deliberately conservative:
   ``min_area=5`` keeps all letter fragments while removing single-pixel artefacts.
6. Invert back to white background / black text for Tesseract.

Public surface
--------------
* ``extract_text_image(gray_or_bgr, *, filter_components=True) -> np.ndarray``
  Full pipeline: returns a Tesseract-ready binary image.
* ``extract_text(image, lang="pol+eng") -> str``
  Convenience wrapper: runs Tesseract on the cleaned image and returns the raw string.
"""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuneable constants (single source of truth for the algorithm)
# ---------------------------------------------------------------------------

# Adaptive threshold block size (must be odd).  Larger values handle broad
# lighting gradients across the page; smaller values preserve fine detail.
_BINARISE_BLOCK = 25

# Adaptive threshold C: subtracted from the local mean before thresholding.
# Higher values make the binarisation more aggressive at rejecting low-contrast noise.
_BINARISE_C = 10

# The horizontal structuring element for line detection is this fraction of the
# page width.  Staff lines span most of the page; letter strokes are much shorter.
_STAFF_KERNEL_WIDTH_FRACTION = 20  # kernel_len = max(40, page_width // 20)
_STAFF_KERNEL_MIN_LEN = 40

# Minimum connected-component area (pixels) to keep after staff removal.
# Below this threshold a component is considered noise.  Very conservative:
# a 2×3 pixel fragment (area=6) is already kept so no letter strokes are lost.
_MIN_COMPONENT_AREA = 5

# Tesseract config applied to the cleaned (staff-free) image.
# PSM 6 = "assume a single uniform block of text" — appropriate once staves are gone.
_TESSERACT_CONFIG = "--psm 6 --oem 3"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_binary_ink_on_black(gray_or_bgr: np.ndarray) -> np.ndarray:
    """Convert a raw page image to a binary array with ink=255, paper=0.

    Uses adaptive Gaussian thresholding so the binarisation degrades gracefully
    across scans with uneven lighting (common in phone/photocopier scans).

    Args:
        gray_or_bgr: Grayscale (H×W) or BGR (H×W×3) uint8 numpy array.

    Returns:
        Binary uint8 array (H×W), ink pixels = 255, background = 0.
    """
    if gray_or_bgr.ndim == 3:
        gray = cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = gray_or_bgr.copy()

    # THRESH_BINARY_INV: dark (ink) pixels fall below local mean → mapped to 255.
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        _BINARISE_BLOCK,
        _BINARISE_C,
    )
    return binary


def _build_staff_mask(binary_ink_on_black: np.ndarray) -> np.ndarray:
    """Detect horizontal staff lines and return a binary mask of those pixels.

    Strategy: morphological OPEN with a wide, 1-pixel-tall structuring element.
    MORPH_OPEN = erode then dilate.  After erosion, only pixels that are part of
    a continuous horizontal white run >= *kernel_len* pixels wide survive.
    Dilation restores those surviving pixels to their original width.
    Letter strokes (20–50px wide at 200 DPI) vanish; staff lines (>80% of page
    width) survive.

    Args:
        binary_ink_on_black: Binary uint8 array, ink=255, background=0.

    Returns:
        Binary uint8 array marking detected staff-line pixels (value 255).
    """
    _h, w = binary_ink_on_black.shape
    kernel_len = max(_STAFF_KERNEL_MIN_LEN, w // _STAFF_KERNEL_WIDTH_FRACTION)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    staff_mask = cv2.morphologyEx(
        binary_ink_on_black, cv2.MORPH_OPEN, h_kernel, iterations=1
    )
    return staff_mask


def _subtract_staff_lines(binary_ink_on_black: np.ndarray) -> np.ndarray:
    """Return *binary_ink_on_black* with the detected staff line pixels zeroed out.

    Args:
        binary_ink_on_black: Binary uint8 array, ink=255, background=0.

    Returns:
        Cleaned binary uint8 array with staff pixels removed.
    """
    staff_mask = _build_staff_mask(binary_ink_on_black)
    return cv2.subtract(binary_ink_on_black, staff_mask)


def _filter_tiny_components(
    binary_ink_on_black: np.ndarray, min_area: int = _MIN_COMPONENT_AREA
) -> np.ndarray:
    """Remove connected components whose area (in pixels) is below *min_area*.

    This pass eliminates isolated dot-noise and tiny broken artefacts that
    survive after staff removal (e.g. a lone pixel from a severed notehead).
    The filter is deliberately conservative: *min_area* defaults to 5, which
    keeps any fragment large enough to be part of a letter stroke.

    Args:
        binary_ink_on_black: Binary uint8 array, ink=255, background=0.
        min_area: Components strictly smaller than this are discarded.

    Returns:
        Filtered binary uint8 array.
    """
    num_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary_ink_on_black, connectivity=8
    )
    output = np.zeros_like(binary_ink_on_black)
    for label in range(1, num_labels):  # label 0 is the background
        if stats[label, cv2.CC_STAT_AREA] >= min_area:
            output[labels == label] = 255
    return output


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_text_image(
    gray_or_bgr: np.ndarray,
    *,
    filter_components: bool = True,
) -> np.ndarray:
    """Remove staff lines and return a Tesseract-ready binary image.

    The output uses the **white-background / black-text** convention (the same
    as ``cv2.adaptiveThreshold(... THRESH_BINARY ...)``), which is what
    ``SheetMusicOCR.preprocess_image`` and Tesseract expect.

    Args:
        gray_or_bgr: Raw page image as a numpy uint8 array (grayscale or BGR).
        filter_components: When True (default), remove connected components
            smaller than ``_MIN_COMPONENT_AREA`` pixels.  Set to False to skip
            this step for speed when the binarised image is already clean.

    Returns:
        Binary uint8 numpy array (H×W), white=255 background, black=0 text.
    """
    # Step 1: binarise with ink=255, background=0
    binary = _to_binary_ink_on_black(gray_or_bgr)

    # Step 2: detect and remove horizontal staff lines
    cleaned = _subtract_staff_lines(binary)

    # Step 3: (optional) drop tiny isolated noise components
    if filter_components:
        cleaned = _filter_tiny_components(cleaned)

    # Step 4: invert to white-bg / black-text for Tesseract
    return cv2.bitwise_not(cleaned)


def extract_text(
    image: np.ndarray,
    lang: str = "pol+eng",
    *,
    config: str = _TESSERACT_CONFIG,
) -> str:
    """Clean *image* and run Tesseract on it, returning the raw OCR string.

    This is a convenience function for standalone use.  The ``SheetMusicOCR``
    integration uses ``extract_text_image`` directly so it can also collect
    confidence scores.

    Args:
        image: Raw page image (grayscale or BGR numpy uint8 array).
        lang: Tesseract language string, e.g. ``"pol+eng"``.
        config: Tesseract CLI config string.  Defaults to ``--psm 6 --oem 3``.

    Returns:
        Raw OCR text string (may be empty if no text found).
    """
    try:
        import pytesseract  # lazy import: not available in all environments
    except ImportError:
        logger.error("pytesseract not installed — cannot run OCR")
        return ""

    cleaned = extract_text_image(image)
    return pytesseract.image_to_string(cleaned, lang=lang, config=config)


def staff_line_fraction(gray_or_bgr: np.ndarray) -> float:
    """Return the fraction of image pixels that are classified as staff lines.

    Useful as a quick diagnostic: values near 0 mean no (or very few) staff
    lines were found; values > 0.05 suggest genuine music notation.

    Args:
        gray_or_bgr: Raw page image (grayscale or BGR numpy uint8 array).

    Returns:
        Float in [0, 1].
    """
    if gray_or_bgr.ndim == 3:
        gray = cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = gray_or_bgr.copy()
    binary = _to_binary_ink_on_black(gray)
    mask = _build_staff_mask(binary)
    total = binary.size
    return float(np.count_nonzero(mask)) / total if total > 0 else 0.0
