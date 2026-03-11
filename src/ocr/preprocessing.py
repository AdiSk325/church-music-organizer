"""Image preprocessing pipeline for OMR.

Handles PDF-to-image conversion, deskewing, binarization,
denoising, and other image preparation steps for optimal
OMR recognition quality.
"""

import logging
import tempfile
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class ImagePreprocessor:
    """Preprocess images for optimal OMR recognition."""

    def __init__(self, output_dir: str = "data/processed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._temp_dir = self.output_dir / "temp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def pdf_to_images(self, pdf_path: str, dpi: int = 300) -> List[str]:
        """Convert PDF pages to high-resolution images using PyMuPDF.

        Args:
            pdf_path: Path to the PDF file
            dpi: Resolution in DPI (300 recommended for OMR)

        Returns:
            List of paths to generated PNG images
        """
        import fitz  # PyMuPDF

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logger.error(f"PDF not found: {pdf_path}")
            return []

        try:
            doc = fitz.open(str(pdf_path))
            image_paths = []
            zoom = dpi / 72.0  # PDF default is 72 DPI
            matrix = fitz.Matrix(zoom, zoom)

            for page_num in range(doc.page_count):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=matrix)

                output_name = f"{pdf_path.stem}_page_{page_num + 1}.png"
                output_path = self._temp_dir / output_name
                pix.save(str(output_path))
                image_paths.append(str(output_path))

                logger.debug(
                    f"Page {page_num + 1}: {pix.width}x{pix.height}px at {dpi} DPI"
                )

            doc.close()
            logger.info(f"Extracted {len(image_paths)} pages from {pdf_path.name}")
            return image_paths

        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            return []

    def preprocess_for_omr(self, input_path: str, dpi: int = 300) -> List[str]:
        """Full preprocessing pipeline: PDF/image → clean images ready for OMR.

        Args:
            input_path: Path to PDF or image file
            dpi: Target DPI for PDF conversion

        Returns:
            List of preprocessed image paths
        """
        input_path = Path(input_path)

        # Step 1: Get images
        if input_path.suffix.lower() == '.pdf':
            image_paths = self.pdf_to_images(str(input_path), dpi=dpi)
        else:
            image_paths = [str(input_path)]

        if not image_paths:
            return []

        # Step 2: Preprocess each image
        processed_paths = []
        for i, img_path in enumerate(image_paths):
            try:
                processed = self._preprocess_single(img_path, page_num=i + 1)
                processed_paths.append(processed)
            except Exception as e:
                logger.warning(f"Preprocessing failed for {img_path}: {e}")
                # Use original image as fallback
                processed_paths.append(img_path)

        return processed_paths

    def _preprocess_single(self, image_path: str, page_num: int = 1) -> str:
        """Preprocess a single image for OMR.

        Steps: grayscale → denoise → binarize → deskew → crop

        Args:
            image_path: Path to the image
            page_num: Page number for output naming

        Returns:
            Path to preprocessed image
        """
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")

        # Convert to grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # Denoise (gentle, preserve thin lines like staff lines)
        denoised = cv2.fastNlMeansDenoising(gray, None, h=5, templateWindowSize=7, searchWindowSize=21)

        # Adaptive binarization (Otsu's method works well for printed music)
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Deskew
        deskewed = self._deskew(binary)

        # Crop to content
        cropped = self._crop_to_content(deskewed)

        # Save result
        stem = Path(image_path).stem
        output_path = self._temp_dir / f"{stem}_preprocessed.png"
        cv2.imwrite(str(output_path), cropped)

        logger.debug(f"Preprocessed page {page_num}: {output_path.name}")
        return str(output_path)

    def _deskew(self, image: np.ndarray, max_angle: float = 5.0) -> np.ndarray:
        """Deskew an image by detecting staff line angles.

        Args:
            image: Binary image (black on white)
            max_angle: Maximum correction angle in degrees

        Returns:
            Deskewed image
        """
        # Invert for line detection (white lines on black)
        inverted = cv2.bitwise_not(image)

        # Detect long horizontal lines (staff lines)
        edges = cv2.Canny(inverted, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, threshold=200,
            minLineLength=image.shape[1] // 4,
            maxLineGap=20
        )

        if lines is None or len(lines) == 0:
            return image

        # Calculate average angle of detected lines
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 != 0:
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                if abs(angle) < max_angle:
                    angles.append(angle)

        if not angles:
            return image

        median_angle = np.median(angles)
        if abs(median_angle) < 0.1:
            return image

        # Rotate to correct
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(
            image, rotation_matrix, (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255  # White background
        )

        logger.debug(f"Deskewed by {median_angle:.2f}°")
        return rotated

    def _crop_to_content(self, image: np.ndarray, margin: int = 20) -> np.ndarray:
        """Crop image to content area with margin.

        Args:
            image: Binary image
            margin: Pixels of margin around content

        Returns:
            Cropped image
        """
        # Find content (non-white pixels)
        inverted = cv2.bitwise_not(image)
        coords = cv2.findNonZero(inverted)

        if coords is None:
            return image

        x, y, w, h = cv2.boundingRect(coords)

        # Add margin
        y_start = max(0, y - margin)
        y_end = min(image.shape[0], y + h + margin)
        x_start = max(0, x - margin)
        x_end = min(image.shape[1], x + w + margin)

        return image[y_start:y_end, x_start:x_end]

    def cleanup_temp(self):
        """Remove temporary preprocessing files."""
        if self._temp_dir.exists():
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir.mkdir(parents=True, exist_ok=True)
