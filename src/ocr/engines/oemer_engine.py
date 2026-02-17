"""Oemer engine wrapper — fallback OMR engine.

Uses oemer (https://github.com/BreezeWhite/oemer) which provides
end-to-end OMR using UNet segmentation + SVM classifiers.
"""

import logging
import time
from argparse import Namespace
from pathlib import Path

from ..omr_engine import OMREngine, OMRResult

logger = logging.getLogger(__name__)


class OemerEngine(OMREngine):
    """OMR engine using oemer (End-to-end OMR)."""

    @property
    def engine_name(self) -> str:
        return "oemer"

    def is_available(self) -> bool:
        try:
            from oemer.ete import extract
            return True
        except ImportError:
            return False

    def recognize(self, image_path: str, **kwargs) -> OMRResult:
        """Run oemer OMR on a single image.

        Args:
            image_path: Path to image file (PNG/JPG)
            without_deskew: Skip deskewing step (default: False)

        Returns:
            OMRResult
        """
        start_time = time.time()
        image_path = str(Path(image_path).resolve())

        try:
            from oemer.ete import extract, clear_data

            # Clear any cached state from previous runs
            clear_data()

            # Build output path
            input_name = Path(image_path).stem
            output_file = str(self.output_dir / f"{input_name}.musicxml")

            args = Namespace(
                img_path=image_path,
                output_path=output_file,
                use_tf=False,
                save_cache=False,
                without_deskew=kwargs.get('without_deskew', False),
            )

            logger.info(f"Running oemer OMR on: {image_path}")
            mxl_path = extract(args)

            if not mxl_path or not Path(mxl_path).exists():
                return OMRResult(
                    success=False,
                    error_message=f"oemer did not produce output file",
                    engine_used=self.engine_name,
                    processing_time_seconds=time.time() - start_time,
                )

            # Read MusicXML content
            raw_xml = Path(mxl_path).read_text(encoding='utf-8')

            # Parse basic info
            result = self._parse_musicxml_info(raw_xml, str(mxl_path))
            result.success = True
            result.engine_used = self.engine_name
            result.processing_time_seconds = time.time() - start_time

            logger.info(
                f"oemer completed in {result.processing_time_seconds:.1f}s: "
                f"{result.staves_detected} staves, {result.measures_detected} measures"
            )
            return result

        except Exception as e:
            logger.error(f"oemer recognition failed: {e}", exc_info=True)
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
