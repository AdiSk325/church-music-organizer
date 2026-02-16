"""Abstract OMR engine interface and result types."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class OMREngineType(Enum):
    """Available OMR engine types."""
    HOMR = "homr"
    OEMER = "oemer"
    AUDIVERIS = "audiveris"


@dataclass
class OMRResult:
    """Result from an OMR engine run."""
    # Output
    musicxml_path: str = ""
    raw_musicxml: str = ""

    # Detected structure
    staves_detected: int = 0
    measures_detected: int = 0
    key_signature: str = ""
    time_signature: str = ""
    clefs: List[str] = field(default_factory=list)
    voices: int = 0

    # Quality
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    engine_used: str = ""
    success: bool = False
    error_message: str = ""

    # Processing info
    pages_processed: int = 0
    processing_time_seconds: float = 0.0


class OMREngine(ABC):
    """Abstract base class for OMR engines."""

    def __init__(self, output_dir: str = "data/processed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Return the engine name."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the engine is installed and ready to use."""
        pass

    @abstractmethod
    def recognize(self, image_path: str, **kwargs) -> OMRResult:
        """Run OMR on a single image file.

        Args:
            image_path: Path to the image (PNG/JPG)

        Returns:
            OMRResult with the recognition results
        """
        pass

    def recognize_pdf(self, pdf_path: str, **kwargs) -> OMRResult:
        """Run OMR on a PDF file by converting pages to images first.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Combined OMRResult for all pages
        """
        from .preprocessing import ImagePreprocessor

        preprocessor = ImagePreprocessor(output_dir=str(self.output_dir))
        image_paths = preprocessor.pdf_to_images(pdf_path)

        if not image_paths:
            return OMRResult(
                success=False,
                error_message=f"Could not extract images from PDF: {pdf_path}",
                engine_used=self.engine_name,
            )

        # Process each page
        results = []
        for img_path in image_paths:
            result = self.recognize(img_path, **kwargs)
            results.append(result)

        # Combine results
        combined = self._combine_results(results)
        combined.pages_processed = len(image_paths)

        # Clean up temp images
        for img_path in image_paths:
            try:
                Path(img_path).unlink(missing_ok=True)
            except Exception:
                pass

        return combined

    def _combine_results(self, results: List[OMRResult]) -> OMRResult:
        """Combine multiple page results into a single merged score.

        Uses music21 to append measures from subsequent pages to the
        first page's score, producing one continuous MusicXML file.
        """
        if not results:
            return OMRResult(success=False, error_message="No results to combine")

        # Find successful results
        successful = [r for r in results if r.success]
        if not successful:
            return OMRResult(
                success=False,
                error_message="All pages failed: " + "; ".join(
                    r.error_message for r in results if r.error_message
                ),
                engine_used=results[0].engine_used,
            )

        if len(successful) == 1:
            total_time = sum(r.processing_time_seconds for r in results)
            successful[0].processing_time_seconds = total_time
            return successful[0]

        # Merge multiple pages with music21
        try:
            combined = self._merge_pages(successful)
        except Exception as e:
            logger.warning(f"Multi-page merge failed ({e}), using page 1 only")
            combined = successful[0]
            combined.warnings.append(
                f"Multi-page merge failed: {e}. Only page 1 included."
            )

        total_time = sum(r.processing_time_seconds for r in results)
        combined.processing_time_seconds = total_time
        return combined

    def _merge_pages(self, results: List[OMRResult]) -> OMRResult:
        """Merge MusicXML files from multiple pages into one score."""
        from music21 import converter as m21converter, stream

        logger.info(f"Merging {len(results)} pages into a single score ...")

        # Parse the first page as base
        base_score = m21converter.parse(results[0].musicxml_path)
        base_parts = list(base_score.parts)

        total_measures = results[0].measures_detected
        total_staves = results[0].staves_detected

        # Append subsequent pages
        for i, result in enumerate(results[1:], start=2):
            try:
                page_score = m21converter.parse(result.musicxml_path)
                page_parts = list(page_score.parts)

                # Match parts by index (same number of staves expected)
                for p_idx in range(min(len(base_parts), len(page_parts))):
                    page_measures = page_parts[p_idx].getElementsByClass('Measure')
                    for m in page_measures:
                        if m.number == 0:
                            continue  # skip anacrusis duplicates
                        # Renumber measure to continue from last
                        base_measures = base_parts[p_idx].getElementsByClass('Measure')
                        if base_measures:
                            last_num = max(bm.number for bm in base_measures)
                            m.number = last_num + 1
                        base_parts[p_idx].append(m)

                total_measures += result.measures_detected
                total_staves = max(total_staves, result.staves_detected)
                logger.info(f"  Merged page {i}: +{result.measures_detected} measures")

            except Exception as e:
                logger.warning(f"  Failed to merge page {i}: {e}")

        # Save merged score
        merged_path = results[0].musicxml_path.replace(
            '_page_1.musicxml', '_merged.musicxml'
        )
        if merged_path == results[0].musicxml_path:
            merged_path = results[0].musicxml_path.replace(
                '.musicxml', '_merged.musicxml'
            )
        base_score.write('musicxml', fp=merged_path)
        logger.info(f"  Merged score saved to: {merged_path}")

        # Build combined result
        combined = OMRResult(
            success=True,
            musicxml_path=merged_path,
            staves_detected=total_staves,
            measures_detected=total_measures,
            confidence=sum(r.confidence for r in results) / len(results),
            engine_used=results[0].engine_used,
            pages_processed=len(results),
        )
        combined.warnings.extend(results[0].warnings)
        combined.warnings.append(
            f"Merged {len(results)} pages into single score"
        )
        return combined


def get_engine(engine_type: OMREngineType, output_dir: str = "data/processed") -> OMREngine:
    """Factory to get an OMR engine instance.

    Args:
        engine_type: Which engine to use
        output_dir: Output directory for results

    Returns:
        OMREngine instance
    """
    if engine_type == OMREngineType.HOMR:
        from .engines.homr_engine import HomrEngine
        return HomrEngine(output_dir=output_dir)
    elif engine_type == OMREngineType.OEMER:
        from .engines.oemer_engine import OemerEngine
        return OemerEngine(output_dir=output_dir)
    elif engine_type == OMREngineType.AUDIVERIS:
        from .engines.audiveris_engine import AudiverisEngine
        return AudiverisEngine(output_dir=output_dir)
    else:
        raise ValueError(f"Unknown engine type: {engine_type}")


def get_best_available_engine(output_dir: str = "data/processed") -> OMREngine:
    """Get the best available OMR engine, trying in priority order.

    Priority: homr > oemer > audiveris

    Returns:
        Best available OMREngine instance
    """
    for engine_type in [OMREngineType.HOMR, OMREngineType.OEMER, OMREngineType.AUDIVERIS]:
        try:
            engine = get_engine(engine_type, output_dir)
            if engine.is_available():
                logger.info(f"Using OMR engine: {engine.engine_name}")
                return engine
        except Exception as e:
            logger.debug(f"Engine {engine_type.value} not available: {e}")

    raise RuntimeError(
        "No OMR engine available. Install homr (pip install homr) "
        "or oemer (pip install oemer)."
    )
