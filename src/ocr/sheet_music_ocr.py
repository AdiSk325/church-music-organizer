"""OCR module for processing scanned sheet music."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

# On Windows the tesseract binary is not on PATH by default. Allow the user to
# point at it via the TESSERACT_CMD env var; otherwise probe the usual install
# location so the app works out of the box after a standard install.
_TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
if not _TESSERACT_CMD and os.name == "nt":
    for _candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(_candidate).exists():
            _TESSERACT_CMD = _candidate
            break
if _TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD

# Extra language packs (e.g. Polish) often cannot be written into the system
# install dir without admin rights, so we ship them in a project-local
# ``data/tessdata`` folder and point Tesseract at it via TESSDATA_PREFIX. A
# value already set in the environment always wins.
if not os.environ.get("TESSDATA_PREFIX"):
    _LOCAL_TESSDATA = Path(__file__).resolve().parents[2] / "data" / "tessdata"
    if _LOCAL_TESSDATA.is_dir() and any(_LOCAL_TESSDATA.glob("*.traineddata")):
        os.environ["TESSDATA_PREFIX"] = str(_LOCAL_TESSDATA)


def tesseract_available() -> bool:
    """Return True if the Tesseract OCR binary can be invoked.

    Used by the UI/service layer to degrade gracefully (show a friendly
    message) instead of throwing when Tesseract is not installed.
    """
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # pytesseract.TesseractNotFoundError and friends
        return False


def available_languages() -> set:
    """Return the set of installed Tesseract language packs (empty if unknown)."""
    try:
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return set()


def resolve_languages(requested: str = "pol+eng") -> str:
    """Trim *requested* OCR languages down to those actually installed.

    Tesseract raises if asked for a language pack that is not present (e.g. ``pol``
    on a default Windows install), which would silently blank the OCR result.
    This keeps only installed languages, falling back to English (or any single
    installed pack) so OCR degrades gracefully. When the installed set cannot be
    introspected, the request is passed through unchanged.
    """
    installed = available_languages()
    if not installed:
        return requested
    wanted = [lang for lang in requested.split("+") if lang in installed]
    if wanted:
        return "+".join(wanted)
    if "eng" in installed:
        logger.warning("Requested OCR languages %r unavailable; falling back to 'eng'", requested)
        return "eng"
    fallback = next((lang for lang in sorted(installed) if lang != "osd"), None)
    return fallback or requested


# ---------------------------------------------------------------------------
# Quality helpers (used for staff-removal fallback decision)
# ---------------------------------------------------------------------------

# If the cleaned OCR result has fewer than this many alphabetic characters AND
# an alpha-ratio below _FALLBACK_ALPHA_THRESHOLD we consider it "clearly worse"
# and fall back to the original (non-cleaned) Tesseract pass.
_FALLBACK_ALPHA_THRESHOLD = 0.20
_FALLBACK_MIN_ALPHA_CHARS = 8

# Tesseract config applied when the staff-cleaned image is used.
_CLEAN_TESS_CONFIG = "--psm 6 --oem 3"


def _compute_alpha_ratio(text: str) -> float:
    """Fraction of non-space characters in *text* that are alphabetic.

    Returns 0.0 for empty or whitespace-only strings.  Used to decide
    whether the staff-removal pass produced a usable OCR result.
    """
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return 0.0
    return sum(1 for c in non_space if c.isalpha()) / len(non_space)


class SheetMusicOCR:
    """OCR processor for sheet music.

    Optionally removes horizontal staff lines from scans before Tesseract so
    that lyric text is extracted with less notation garbage.  The behaviour is
    controlled by the *remove_staff_lines* constructor argument (default: ``True``)
    which can be overridden by the ``OCR_REMOVE_STAFF_LINES`` environment variable
    (``"0"``/``"false"`` to disable, ``"1"``/``"true"`` to force-enable).

    A graceful fallback runs the original (un-cleaned) Tesseract pass when the
    staff-removal result appears clearly worse (very low alpha-ratio or near-empty
    text).  This ensures we never regress on scans where removal might hurt.
    """

    def __init__(self, output_dir: str = "data/processed", remove_staff_lines: bool = True):
        """Initialise the OCR processor.

        Args:
            output_dir: Directory to store processed files.
            remove_staff_lines: Enable staff-line removal pre-processing.
                Overridden by the ``OCR_REMOVE_STAFF_LINES`` env var.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Honour the environment variable override.
        env_val = os.environ.get("OCR_REMOVE_STAFF_LINES", "").strip().lower()
        if env_val in ("0", "false", "no", "off"):
            self._remove_staff_lines = False
        elif env_val in ("1", "true", "yes", "on"):
            self._remove_staff_lines = True
        else:
            self._remove_staff_lines = remove_staff_lines

    def preprocess_image(self, image_path: str) -> np.ndarray:
        """Preprocess image for better OCR results.

        Args:
            image_path: Path to the image file

        Returns:
            Preprocessed image as numpy array
        """
        # Read image
        img = cv2.imread(image_path)

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # Denoise
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)

        return denoised

    def extract_text(self, image_path: str, lang: str = "pol+eng") -> Dict[str, str]:
        """Extract text from a sheet music image.

        When *remove_staff_lines* is enabled (the default), the image is first
        processed by :mod:`src.ocr.text_region_extractor` to strip five-line
        staff notation before Tesseract runs.  If the cleaned result is clearly
        poor (alpha-ratio below threshold *and* very few alphabetic characters)
        the method falls back transparently to the standard un-cleaned path.

        Args:
            image_path: Path to the image file.
            lang: Tesseract language string (default: ``"pol+eng"``).

        Returns:
            Dict with keys ``text`` (str), ``confidence`` (float 0–100),
            ``blocks`` (list of block dicts).
        """
        try:
            # Trim requested languages down to those actually installed so we
            # never crash with a "language pack not found" error.
            lang = resolve_languages(lang)

            if self._remove_staff_lines:
                result = self._extract_text_with_staff_removal(image_path, lang)
                if result is not None:
                    return result
                # Fall through to standard path if staff removal raised an error.

            return self._extract_text_standard(image_path, lang)

        except Exception as e:
            logger.error("Error extracting text from %s: %s", image_path, str(e))
            return {"text": "", "confidence": 0, "blocks": []}

    # ------------------------------------------------------------------
    # Internal extraction helpers
    # ------------------------------------------------------------------

    def _extract_text_standard(self, image_path: str, lang: str) -> Dict[str, str]:
        """Run the original (no staff-removal) Tesseract path."""
        processed_img = self.preprocess_image(image_path)
        text = pytesseract.image_to_string(processed_img, lang=lang)
        data = pytesseract.image_to_data(
            processed_img, lang=lang, output_type=pytesseract.Output.DICT
        )
        return {
            "text": text,
            "confidence": self._calculate_average_confidence(data),
            "blocks": self._extract_text_blocks(data),
        }

    def _extract_text_with_staff_removal(
        self, image_path: str, lang: str
    ) -> Optional[Dict[str, str]]:
        """Run Tesseract on a staff-cleaned image; fall back to standard if needed.

        Returns None only if loading or extraction raises an unexpected exception
        (the caller will then use the standard path).

        Fallback condition: cleaned text has alpha-ratio below
        ``_FALLBACK_ALPHA_THRESHOLD`` AND fewer than ``_FALLBACK_MIN_ALPHA_CHARS``
        alphabetic characters.  In that case, the standard path is run and its
        result returned so we never return worse text than the original.
        """
        try:
            from src.ocr.text_region_extractor import extract_text_image  # lazy import
        except ImportError:
            logger.warning(
                "text_region_extractor unavailable; falling back to standard OCR path"
            )
            return None

        raw_bgr = cv2.imread(image_path)
        if raw_bgr is None:
            logger.warning("Staff-removal path: cv2.imread returned None for %s", image_path)
            return None

        try:
            cleaned_binary = extract_text_image(raw_bgr)
        except Exception:
            logger.exception("Staff-removal step failed for %s; falling back", image_path)
            return None

        # Run Tesseract on the cleaned image.
        cleaned_text = pytesseract.image_to_string(
            cleaned_binary, lang=lang, config=_CLEAN_TESS_CONFIG
        )
        cleaned_data = pytesseract.image_to_data(
            cleaned_binary, lang=lang, config=_CLEAN_TESS_CONFIG,
            output_type=pytesseract.Output.DICT,
        )
        cleaned_alpha = _compute_alpha_ratio(cleaned_text)
        cleaned_alpha_chars = sum(1 for c in cleaned_text if c.isalpha())

        # Quality check: is the cleaned result clearly bad?
        clearly_bad = (
            cleaned_alpha < _FALLBACK_ALPHA_THRESHOLD
            and cleaned_alpha_chars < _FALLBACK_MIN_ALPHA_CHARS
        )

        if clearly_bad:
            logger.debug(
                "Staff-removal: cleaned OCR poor (alpha=%.2f, alpha_chars=%d) for %s — "
                "running standard path as fallback",
                cleaned_alpha,
                cleaned_alpha_chars,
                image_path,
            )
            standard = self._extract_text_standard(image_path, lang)
            # Return whichever result has the higher alpha-ratio.
            if _compute_alpha_ratio(standard["text"]) >= cleaned_alpha:
                return standard
            # (rare: cleaned was already the better one despite low absolute alpha)
            logger.debug("Staff-removal: standard path also poor; keeping cleaned result")

        return {
            "text": cleaned_text,
            "confidence": self._calculate_average_confidence(cleaned_data),
            "blocks": self._extract_text_blocks(cleaned_data),
        }

    def _calculate_average_confidence(self, data: Dict) -> float:
        """Calculate average confidence from OCR data.

        Args:
            data: OCR data dictionary

        Returns:
            Average confidence score
        """
        confidences = [conf for conf in data.get("conf", []) if conf != -1]
        return sum(confidences) / len(confidences) if confidences else 0

    def _extract_text_blocks(self, data: Dict) -> List[Dict]:
        """Extract text blocks from OCR data.

        Args:
            data: OCR data dictionary

        Returns:
            List of text blocks with positions
        """
        blocks = []
        n_boxes = len(data.get("text", []))

        for i in range(n_boxes):
            if int(data["conf"][i]) > 0:
                block = {
                    "text": data["text"][i],
                    "confidence": data["conf"][i],
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "width": data["width"][i],
                    "height": data["height"][i],
                }
                blocks.append(block)

        return blocks

    def process_pdf(self, pdf_path: str) -> List[Dict[str, str]]:
        """Process PDF file and extract text from each page.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of dictionaries with extracted text per page
        """
        try:
            from pdf2image import convert_from_path

            # Convert PDF to images
            images = convert_from_path(pdf_path)

            results = []
            for i, image in enumerate(images):
                # Save temporary image
                temp_path = self.output_dir / f"temp_page_{i}.png"
                image.save(temp_path)

                # Extract text
                result = self.extract_text(str(temp_path))
                result["page"] = i + 1
                results.append(result)

                # Clean up temporary file
                temp_path.unlink()

            return results
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_path}: {str(e)}")
            return []

    def process_file(self, file_path: str) -> "Dict | List[Dict]":
        """Process an image or PDF file and return OCR results.

        For PDF files returns a list of per-page dicts; for images returns a single dict.
        Each dict contains keys: ``text``, ``confidence``, ``has_music_notation``.

        Args:
            file_path: Path to the file to process.

        Returns:
            For PDFs: list of dicts with keys text, confidence, has_music_notation, page.
            For images: dict with keys text, confidence, has_music_notation.
        """
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            pages = self.process_pdf(file_path)
            for page in pages:
                # process_pdf pages don't include has_music_notation yet — add placeholder
                page.setdefault("has_music_notation", False)
            return pages

        # Image path
        result = self.extract_text(file_path)
        has_notation = self.detect_music_notation(file_path)
        return {
            "text": result.get("text", ""),
            "confidence": result.get("confidence", 0),
            "has_music_notation": has_notation,
            "blocks": result.get("blocks", []),
        }

    def detect_music_notation(self, image_path: str) -> bool:
        """Detect if image contains music notation.

        Args:
            image_path: Path to the image file

        Returns:
            True if music notation detected, False otherwise
        """
        try:
            # Simple heuristic: check for horizontal lines (staff lines)
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            edges = cv2.Canny(img, 50, 150, apertureSize=3)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)

            if lines is not None:
                # Count horizontal lines
                horizontal_lines = sum(1 for line in lines if abs(line[0][1] - line[0][3]) < 5)
                return horizontal_lines >= 5  # At least 5 staff lines

            return False
        except Exception as e:
            logger.error(f"Error detecting music notation in {image_path}: {str(e)}")
            return False
