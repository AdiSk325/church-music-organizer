"""OCR module for sheet music processing.

Provides a comprehensive OMR (Optical Music Recognition) pipeline:
  - Multiple OMR engines (homr, oemer, Audiveris)
  - Image preprocessing (deskew, denoise, binarize)
  - Part definition and score assembly
  - MusicXML validation and auto-fix
  - Lyrics alignment from PDF text layer
"""

# Legacy modules — optional, kept for backward compatibility
try:
    from .musicxml_converter import MusicXMLConverter
except ImportError:
    MusicXMLConverter = None

try:
    from .pdf_text_extractor import PDFTextExtractor, LyricsData
except ImportError:
    PDFTextExtractor = None
    LyricsData = None

# Core pipeline modules
from .omr_engine import OMREngine, OMRResult, OMREngineType, get_engine, get_best_available_engine
from .preprocessing import ImagePreprocessor
from .musicxml_validator import MusicXMLValidator, ValidationReport
from .lyrics_aligner import LyricsAligner
from .text_classifier import TextClassifier, ClassifiedText
from .staff_detector import StaffDetector, StaffLayout
from .staff_splitter import StaffSplitter
from .part_definition import PartDefinition
from .score_builder import ScoreBuilder
from .omr_postprocessor import OMRPostProcessor, PostProcessingReport
from .ingestion import Ingester, IngestionReport, PageResult, detect_text_layer, measure_page

__all__ = [
    # Legacy (kept for backward compat)
    'MusicXMLConverter',
    'PDFTextExtractor',
    'LyricsData',
    # OMR engines
    'OMREngine',
    'OMRResult',
    'OMREngineType',
    'get_engine',
    'get_best_available_engine',
    # Preprocessing
    'ImagePreprocessor',
    # Validation
    'MusicXMLValidator',
    'ValidationReport',
    # Lyrics
    'LyricsAligner',
    # Pipeline modules
    'TextClassifier',
    'ClassifiedText',
    'StaffDetector',
    'StaffLayout',
    'StaffSplitter',
    'PartDefinition',
    'ScoreBuilder',
    # Post-processing
    'OMRPostProcessor',
    'PostProcessingReport',
    # Ingestion
    'Ingester',
    'IngestionReport',
    'PageResult',
    'detect_text_layer',
    'measure_page',
]
