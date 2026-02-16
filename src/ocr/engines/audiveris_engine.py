"""Audiveris engine wrapper — most accurate OMR engine.

Uses Audiveris (https://github.com/Audiveris/audiveris) via CLI.
Requires Java runtime and Audiveris to be installed separately.
"""

import logging
import subprocess
import time
from pathlib import Path

from ..omr_engine import OMREngine, OMRResult

logger = logging.getLogger(__name__)


class AudiverisEngine(OMREngine):
    """OMR engine using Audiveris (Java-based CLI)."""

    # Common Audiveris executable names/paths
    AUDIVERIS_NAMES = [
        'audiveris',
        'Audiveris',
        'audiveris.bat',
        'Audiveris.bat',
    ]

    # Common installation directories on Windows
    AUDIVERIS_PATHS = [
        r'C:\Program Files\Audiveris\bin\Audiveris.bat',
        r'C:\Program Files (x86)\Audiveris\bin\Audiveris.bat',
    ]

    @property
    def engine_name(self) -> str:
        return "audiveris"

    def is_available(self) -> bool:
        """Check if Audiveris is installed and Java is available."""
        return self._find_audiveris() is not None

    def _find_audiveris(self) -> str | None:
        """Find the Audiveris executable."""
        # Check in PATH
        for name in self.AUDIVERIS_NAMES:
            try:
                result = subprocess.run(
                    [name, '-help'],
                    capture_output=True, text=True, timeout=10
                )
                return name
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        # Check common installation paths
        for path in self.AUDIVERIS_PATHS:
            if Path(path).exists():
                return path

        return None

    def recognize(self, image_path: str, **kwargs) -> OMRResult:
        """Run Audiveris OMR on an image file.

        Args:
            image_path: Path to image file (PNG/JPG/TIFF/PDF)

        Returns:
            OMRResult
        """
        start_time = time.time()
        image_path = str(Path(image_path).resolve())
        audiveris_cmd = self._find_audiveris()

        if not audiveris_cmd:
            return OMRResult(
                success=False,
                error_message=(
                    "Audiveris not found. Install from: "
                    "https://github.com/Audiveris/audiveris/releases"
                ),
                engine_used=self.engine_name,
                processing_time_seconds=time.time() - start_time,
            )

        try:
            input_name = Path(image_path).stem
            output_file = str(self.output_dir / f"{input_name}.musicxml")

            # Run Audiveris CLI: transcribe and export MusicXML
            cmd = [
                audiveris_cmd,
                '-batch',
                '-export',
                '-output', str(self.output_dir),
                image_path,
            ]

            logger.info(f"Running Audiveris on: {image_path}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=kwargs.get('timeout', 300),
            )

            if result.returncode != 0:
                return OMRResult(
                    success=False,
                    error_message=f"Audiveris failed: {result.stderr}",
                    engine_used=self.engine_name,
                    processing_time_seconds=time.time() - start_time,
                )

            # Find the output MusicXML file
            # Audiveris may create it in a subdirectory
            possible_outputs = list(self.output_dir.rglob(f"{input_name}*.musicxml"))
            possible_outputs += list(self.output_dir.rglob(f"{input_name}*.mxl"))
            possible_outputs += list(self.output_dir.rglob(f"{input_name}*.xml"))

            if not possible_outputs:
                return OMRResult(
                    success=False,
                    error_message="Audiveris did not produce MusicXML output",
                    engine_used=self.engine_name,
                    processing_time_seconds=time.time() - start_time,
                )

            output_path = str(possible_outputs[0])
            raw_xml = Path(output_path).read_text(encoding='utf-8')

            # Parse info
            omr_result = self._parse_musicxml_info(raw_xml, output_path)
            omr_result.success = True
            omr_result.engine_used = self.engine_name
            omr_result.processing_time_seconds = time.time() - start_time

            logger.info(f"Audiveris completed in {omr_result.processing_time_seconds:.1f}s")
            return omr_result

        except subprocess.TimeoutExpired:
            return OMRResult(
                success=False,
                error_message="Audiveris timed out",
                engine_used=self.engine_name,
                processing_time_seconds=time.time() - start_time,
            )
        except Exception as e:
            logger.error(f"Audiveris recognition failed: {e}", exc_info=True)
            return OMRResult(
                success=False,
                error_message=str(e),
                engine_used=self.engine_name,
                processing_time_seconds=time.time() - start_time,
            )

    def _parse_musicxml_info(self, xml_content: str, xml_path: str) -> OMRResult:
        """Extract structural info from MusicXML using music21."""
        result = OMRResult(musicxml_path=xml_path, raw_musicxml=xml_content)

        try:
            from music21 import converter

            score = converter.parse(xml_path)
            result.staves_detected = len(score.parts)
            result.measures_detected = len(score.parts[0].getElementsByClass('Measure')) if score.parts else 0

            keys = score.flatten().getElementsByClass('KeySignature')
            if keys:
                result.key_signature = str(keys[0])

            time_sigs = score.flatten().getElementsByClass('TimeSignature')
            if time_sigs:
                result.time_signature = str(time_sigs[0])

            for part in score.parts:
                clefs = part.flatten().getElementsByClass('Clef')
                if clefs:
                    result.clefs.append(type(clefs[0]).__name__)

            voices_set = set()
            for part in score.parts:
                for measure in part.getElementsByClass('Measure'):
                    for voice in measure.voices:
                        voices_set.add(id(voice))
            result.voices = max(len(voices_set), len(score.parts))

        except Exception as e:
            result.warnings.append(f"Could not parse MusicXML for metadata: {e}")

        return result
