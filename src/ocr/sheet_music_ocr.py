"""OCR module for processing scanned sheet music."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

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


class SheetMusicOCR:
    """OCR processor for sheet music."""

    def __init__(self, output_dir: str = "data/processed"):
        """Initialize OCR processor.

        Args:
            output_dir: Directory to store processed files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

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
        """Extract text from sheet music image.

        Args:
            image_path: Path to the image file
            lang: Language for OCR (default: Polish + English)

        Returns:
            Dictionary with extracted text information
        """
        try:
            # Use only installed language packs (avoids hard failure when, e.g.,
            # the Polish pack is missing on a default Windows Tesseract install).
            lang = resolve_languages(lang)

            # Preprocess image
            processed_img = self.preprocess_image(image_path)

            # Perform OCR
            text = pytesseract.image_to_string(processed_img, lang=lang)

            # Extract detailed information
            data = pytesseract.image_to_data(
                processed_img, lang=lang, output_type=pytesseract.Output.DICT
            )

            return {
                "text": text,
                "confidence": self._calculate_average_confidence(data),
                "blocks": self._extract_text_blocks(data),
            }
        except Exception as e:
            logger.error(f"Error extracting text from {image_path}: {str(e)}")
            return {"text": "", "confidence": 0, "blocks": []}

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
