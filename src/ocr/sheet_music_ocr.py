"""OCR module for processing scanned sheet music."""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


class SheetMusicOCR:
    """OCR processor for sheet music.

    Provides image preprocessing, text/lyrics extraction via Tesseract,
    and music notation (staff line) detection via OpenCV.
    """

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
        if img is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # Denoise
        denoised = cv2.fastNlMeansDenoising(thresh, None, 10, 7, 21)

        return denoised

    def extract_text(self, image_path: str, lang: str = "pol+eng") -> Dict[str, object]:
        """Extract text from sheet music image.

        Args:
            image_path: Path to the image file
            lang: Language for OCR (default: Polish + English)

        Returns:
            Dictionary with extracted text information
        """
        try:
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
            logger.error("Error extracting text from %s: %s", image_path, e)
            return {"text": "", "confidence": 0.0, "blocks": []}

    def extract_lyrics(self, image_path: str, lang: str = "pol+eng") -> str:
        """Extract only lyrics text from a sheet music image.

        Filters out very short tokens and low-confidence fragments that are
        typically misrecognised staff lines or note heads.

        Args:
            image_path: Path to the image file.
            lang: Tesseract language string.

        Returns:
            Cleaned lyrics string.
        """
        result = self.extract_text(image_path, lang=lang)
        blocks = result.get("blocks", [])

        # Keep only blocks with reasonable confidence and length
        words = [
            b["text"]
            for b in blocks
            if b.get("confidence", 0) > 40 and len(b.get("text", "").strip()) > 1
        ]
        return " ".join(words)

    def _calculate_average_confidence(self, data: Dict) -> float:
        """Calculate average confidence from OCR data.

        Args:
            data: OCR data dictionary

        Returns:
            Average confidence score
        """
        confidences = [conf for conf in data.get("conf", []) if conf != -1]
        return sum(confidences) / len(confidences) if confidences else 0.0

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

    def process_pdf(self, pdf_path: str) -> List[Dict[str, object]]:
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
                temp_path.unlink(missing_ok=True)

            return results
        except Exception as e:
            logger.error("Error processing PDF %s: %s", pdf_path, e)
            return []

    def detect_music_notation(self, image_path: str) -> bool:
        """Detect if image contains music notation by finding staff lines.

        Uses Hough line detection to find groups of evenly-spaced horizontal
        lines, which is the hallmark of a musical staff.

        Args:
            image_path: Path to the image file

        Returns:
            True if music notation detected, False otherwise
        """
        try:
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return False

            edges = cv2.Canny(img, 50, 150, apertureSize=3)
            lines = cv2.HoughLinesP(
                edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10
            )

            if lines is not None:
                # Count horizontal lines (small vertical delta)
                horizontal_lines = sum(
                    1 for line in lines if abs(line[0][1] - line[0][3]) < 5
                )
                return horizontal_lines >= 5  # At least 5 staff lines
            return False
        except Exception as e:
            logger.error("Error detecting music notation in %s: %s", image_path, e)
            return False

    def detect_staff_regions(self, image_path: str) -> List[Dict[str, int]]:
        """Detect bounding boxes of staff-line groups in the image.

        Returns a list of dictionaries with keys ``y_start`` and ``y_end``
        indicating the vertical extent of each detected staff system.

        Args:
            image_path: Path to the image file.

        Returns:
            List of staff region bounding boxes.
        """
        try:
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return []

            # Binarise
            _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            # Horizontal projection: count black pixels per row
            h_proj = np.sum(binary, axis=1) / 255

            # Threshold to find rows with significant content
            threshold = img.shape[1] * 0.15
            in_region = False
            regions: List[Dict[str, int]] = []
            start = 0

            for y, val in enumerate(h_proj):
                if val > threshold and not in_region:
                    in_region = True
                    start = y
                elif val <= threshold and in_region:
                    in_region = False
                    if y - start > 20:  # Ignore very thin bands
                        regions.append({"y_start": start, "y_end": y})

            if in_region and len(h_proj) - start > 20:
                regions.append({"y_start": start, "y_end": len(h_proj)})

            return regions
        except Exception as e:
            logger.error("Error detecting staff regions in %s: %s", image_path, e)
            return []
