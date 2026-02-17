"""End-to-end processor for scanned sheet music PDFs.

DEPRECATED: This module is deprecated in favor of the modular OMR pipeline v2.
Use convert_pdf_to_musicxml.py with the new pipeline components instead.

Orchestrates the full pipeline:
  PDF scan → image preprocessing → text/lyrics extraction → OMR analysis → MusicXML output.

The OMR step supports two backends:
  1. Audiveris (external CLI tool) – highest quality, requires Java and Audiveris installed.
  2. Built-in heuristic analysis using OpenCV + music21 – works without external tools,
     produces a skeleton MusicXML suitable for import and further editing in MuseScore.
"""

import warnings
warnings.warn(
    "ScanProcessor is deprecated. Use the modular OMR pipeline v2 instead.",
    DeprecationWarning,
    stacklevel=2
)

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .musicxml_converter import MusicXMLConverter
from .sheet_music_ocr import SheetMusicOCR

logger = logging.getLogger(__name__)


@dataclass
class ScanProcessingResult:
    """Result of processing a scanned sheet music file."""

    source_path: str = ""
    lyrics: str = ""
    text_blocks: List[Dict] = field(default_factory=list)
    text_confidence: float = 0.0
    music_detected: bool = False
    musicxml_path: Optional[str] = None
    omr_backend: Optional[str] = None
    page_results: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ScanProcessor:
    """End-to-end processor for scanned sheet music.

    Usage::

        processor = ScanProcessor(output_dir="data/processed")
        result = processor.process_pdf("scans/ave_maria.pdf", title="Ave Maria")

        # result.lyrics          – extracted text/lyrics
        # result.musicxml_path   – path to generated MusicXML file (or None)
        # result.music_detected  – whether music notation was found
    """

    def __init__(self, output_dir: str = "data/processed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ocr = SheetMusicOCR(output_dir=output_dir)
        self.converter = MusicXMLConverter(output_dir=output_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_pdf(
        self,
        pdf_path: str,
        title: str = "Untitled",
        composer: Optional[str] = None,
    ) -> ScanProcessingResult:
        """Process a scanned PDF and produce lyrics + MusicXML.

        Args:
            pdf_path: Path to the scanned PDF file.
            title: Title of the piece (used in MusicXML metadata).
            composer: Optional composer name.

        Returns:
            ScanProcessingResult with extracted data and file paths.
        """
        result = ScanProcessingResult(source_path=pdf_path)

        pdf = Path(pdf_path)
        if not pdf.exists():
            result.errors.append(f"File not found: {pdf_path}")
            return result

        # Step 1 – Convert PDF pages to images and extract text
        page_results = self.ocr.process_pdf(pdf_path)
        result.page_results = page_results

        # Aggregate lyrics from all pages
        all_text_parts: List[str] = []
        all_blocks: List[Dict] = []
        total_confidence = 0.0

        for pr in page_results:
            text = pr.get("text", "").strip()
            if text:
                all_text_parts.append(text)
            all_blocks.extend(pr.get("blocks", []))
            total_confidence += pr.get("confidence", 0.0)

        result.lyrics = "\n\n".join(all_text_parts)
        result.text_blocks = all_blocks
        result.text_confidence = total_confidence / len(page_results) if page_results else 0.0

        # Step 2 – Detect music notation on first page image
        result.music_detected = self._check_music_in_pdf(pdf_path)

        # Step 3 – Run OMR to produce MusicXML
        if result.music_detected:
            musicxml_path = self._run_omr(pdf_path, title=title, composer=composer)
            if musicxml_path:
                result.musicxml_path = musicxml_path
        else:
            # Even without detected music, create a skeleton MusicXML with lyrics
            musicxml_path = self._create_skeleton_musicxml(
                title=title, composer=composer, lyrics=result.lyrics
            )
            if musicxml_path:
                result.musicxml_path = musicxml_path

        return result

    def process_image(
        self,
        image_path: str,
        title: str = "Untitled",
        composer: Optional[str] = None,
    ) -> ScanProcessingResult:
        """Process a single scanned image (PNG, JPG, TIFF, etc.).

        Args:
            image_path: Path to the image file.
            title: Title of the piece.
            composer: Optional composer name.

        Returns:
            ScanProcessingResult with extracted data.
        """
        result = ScanProcessingResult(source_path=image_path)

        img = Path(image_path)
        if not img.exists():
            result.errors.append(f"File not found: {image_path}")
            return result

        # Extract text
        text_data = self.ocr.extract_text(image_path)
        result.lyrics = text_data.get("text", "").strip()
        result.text_blocks = text_data.get("blocks", [])
        result.text_confidence = text_data.get("confidence", 0.0)

        # Detect music
        result.music_detected = self.ocr.detect_music_notation(image_path)

        # OMR
        if result.music_detected:
            musicxml_path = self._run_omr(image_path, title=title, composer=composer)
            if musicxml_path:
                result.musicxml_path = musicxml_path
        else:
            musicxml_path = self._create_skeleton_musicxml(
                title=title, composer=composer, lyrics=result.lyrics
            )
            if musicxml_path:
                result.musicxml_path = musicxml_path

        return result

    # ------------------------------------------------------------------
    # OMR backends
    # ------------------------------------------------------------------

    def _run_omr(
        self, input_path: str, title: str = "Untitled", composer: Optional[str] = None
    ) -> Optional[str]:
        """Attempt OMR using available backends.

        Tries Audiveris first; falls back to built-in skeleton creation.
        """
        # Try Audiveris
        audiveris_result = self._run_audiveris(input_path)
        if audiveris_result:
            return audiveris_result

        # Fallback: skeleton MusicXML with metadata
        logger.info("Audiveris not available – creating skeleton MusicXML for MuseScore editing.")
        return self._create_skeleton_musicxml(title=title, composer=composer, lyrics="")

    def _run_audiveris(self, input_path: str) -> Optional[str]:
        """Run Audiveris CLI for optical music recognition.

        Audiveris (https://github.com/Audiveris/audiveris) is an open-source OMR engine.
        It must be installed and available on PATH as ``audiveris``.

        Returns:
            Path to the generated MusicXML file, or None if Audiveris is unavailable.
        """
        if not shutil.which("audiveris"):
            logger.info("Audiveris CLI not found on PATH.")
            return None

        stem = Path(input_path).stem
        output_musicxml = str(self.output_dir / f"{stem}_omr.musicxml")

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                cmd = [
                    "audiveris",
                    "-batch",
                    "-export",
                    "-output",
                    tmpdir,
                    input_path,
                ]
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if proc.returncode != 0:
                    logger.warning("Audiveris failed: %s", proc.stderr)
                    return None

                # Audiveris writes .mxl or .musicxml in the output directory
                generated = list(Path(tmpdir).rglob("*.mxl")) + list(
                    Path(tmpdir).rglob("*.musicxml")
                )
                if not generated:
                    logger.warning("Audiveris produced no MusicXML output.")
                    return None

                # Copy the first result to our output dir
                shutil.copy2(str(generated[0]), output_musicxml)
                logger.info("Audiveris OMR result saved to %s", output_musicxml)
                return output_musicxml

            except FileNotFoundError:
                logger.info("Audiveris not found.")
                return None
            except subprocess.TimeoutExpired:
                logger.warning("Audiveris timed out after 300 s.")
                return None
            except Exception as exc:
                logger.error("Audiveris error: %s", exc)
                return None

    def _create_skeleton_musicxml(
        self,
        title: str = "Untitled",
        composer: Optional[str] = None,
        lyrics: Optional[str] = None,
    ) -> Optional[str]:
        """Create a skeleton MusicXML file for manual editing in MuseScore.

        The skeleton contains metadata and an empty part that can be filled in
        by the user in MuseScore.
        """
        stem = title.replace(" ", "_").replace("/", "_")[:50]
        output_path = str(self.output_dir / f"{stem}.musicxml")

        score = self.converter.create_score_with_lyrics(
            title=title, composer=composer, lyrics=lyrics
        )
        if self.converter.save_as_musicxml(score, output_path):
            return output_path
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_music_in_pdf(self, pdf_path: str) -> bool:
        """Check if any page in the PDF contains music notation."""
        try:
            from pdf2image import convert_from_path

            images = convert_from_path(pdf_path, first_page=1, last_page=1)
            if not images:
                return False

            temp_path = self.output_dir / "_detect_temp.png"
            images[0].save(temp_path)
            detected = self.ocr.detect_music_notation(str(temp_path))
            temp_path.unlink(missing_ok=True)
            return detected
        except Exception as exc:
            logger.error("Error checking PDF for music: %s", exc)
            return False
