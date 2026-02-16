"""HOMR engine wrapper — primary OMR engine.

Uses homr (https://github.com/liebharc/homr) which combines
oemer's segmentation with a Polyphonic-TrOMR transformer model.
"""

import logging
import shutil
import time
from pathlib import Path

from ..omr_engine import OMREngine, OMRResult

logger = logging.getLogger(__name__)


class HomrEngine(OMREngine):
    """OMR engine using homr (Homer's Optical Music Recognition)."""

    @property
    def engine_name(self) -> str:
        return "homr"

    def is_available(self) -> bool:
        try:
            from homr.main import process_image, download_weights
            return True
        except ImportError:
            return False

    def recognize(self, image_path: str, **kwargs) -> OMRResult:
        """Run homr OMR on a single image.

        Args:
            image_path: Path to image file (PNG/JPG)
            use_gpu: Whether to use GPU inference (default: False)

        Returns:
            OMRResult
        """
        start_time = time.time()
        image_path = str(Path(image_path).resolve())

        try:
            from homr.main import ProcessingConfig, process_image, download_weights
            from homr.music_xml_generator import XmlGeneratorArguments

            # Download weights if needed (first run)
            use_gpu = kwargs.get('use_gpu', False)
            logger.info("Checking/downloading homr model weights...")
            download_weights(use_gpu_inference=use_gpu)

            # Configure
            config = ProcessingConfig(
                enable_debug=kwargs.get('debug', False),
                enable_cache=False,
                write_staff_positions=False,
                read_staff_positions=False,
                selected_staff=-1,  # all staffs
                use_gpu_inference=use_gpu,
            )

            xml_args = XmlGeneratorArguments(
                large_page=None,
                metronome=None,
                tempo=None,
            )

            # homr writes output next to input file, so copy input to output dir
            input_path = Path(image_path)
            work_path = self.output_dir / input_path.name
            if work_path != input_path:
                shutil.copy2(image_path, work_path)

            logger.info(f"Running homr OMR on: {work_path}")
            process_image(str(work_path), config, xml_args)

            # Find output file (same name but .musicxml)
            output_path = work_path.with_suffix('.musicxml')

            if not output_path.exists():
                return OMRResult(
                    success=False,
                    error_message=f"homr did not produce output file at {output_path}",
                    engine_used=self.engine_name,
                    processing_time_seconds=time.time() - start_time,
                )

            # Read the MusicXML content
            raw_xml = output_path.read_text(encoding='utf-8')

            # Parse basic info from the XML
            result = self._parse_musicxml_info(raw_xml, str(output_path))
            result.success = True
            result.engine_used = self.engine_name
            result.processing_time_seconds = time.time() - start_time

            # Clean up copied input and teaser image
            if work_path != input_path:
                work_path.unlink(missing_ok=True)
            teaser = work_path.with_name(work_path.stem + '_teaser.png')
            teaser.unlink(missing_ok=True)

            logger.info(
                f"homr completed in {result.processing_time_seconds:.1f}s: "
                f"{result.staves_detected} staves, {result.measures_detected} measures"
            )
            return result

        except Exception as e:
            logger.error(f"homr recognition failed: {e}", exc_info=True)
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

            # Key signature
            keys = score.flatten().getElementsByClass('KeySignature')
            if keys:
                result.key_signature = str(keys[0])

            # Time signature
            time_sigs = score.flatten().getElementsByClass('TimeSignature')
            if time_sigs:
                result.time_signature = str(time_sigs[0])

            # Clefs
            for part in score.parts:
                clefs = part.flatten().getElementsByClass('Clef')
                if clefs:
                    result.clefs.append(type(clefs[0]).__name__)

            # Count voices
            voices_set = set()
            for part in score.parts:
                for measure in part.getElementsByClass('Measure'):
                    for voice in measure.voices:
                        voices_set.add(id(voice))
            result.voices = max(len(voices_set), len(score.parts))

        except Exception as e:
            result.warnings.append(f"Could not parse MusicXML for metadata: {e}")

        return result
