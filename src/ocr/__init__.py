"""OCR module for sheet music processing.

Provides a comprehensive OMR (Optical Music Recognition) pipeline:
  - Multiple OMR engines (homr, oemer, Audiveris)
  - Image preprocessing (deskew, denoise, binarize)
  - Score analysis (parts, voices, clefs, key/time sigs)
  - MusicXML validation and auto-fix
  - Voice detection (SATB, Piano+Voice, etc.)
  - Lyrics alignment from PDF text layer
"""

from .sheet_music_ocr import SheetMusicOCR
from .musicxml_converter import MusicXMLConverter
from .pdf_text_extractor import PDFTextExtractor, LyricsData
from .omr_engine import OMREngine, OMRResult, OMREngineType, get_engine, get_best_available_engine
from .preprocessing import ImagePreprocessor
from .score_analyzer import ScoreAnalyzer, ScoreMetadata
from .musicxml_validator import MusicXMLValidator, ValidationReport
from .voice_detector import VoiceDetector, VoiceDetectionResult
from .lyrics_aligner import LyricsAligner
from .text_classifier import TextClassifier, ClassifiedText
from .staff_detector import StaffDetector, StaffLayout
from .staff_splitter import StaffSplitter
from .score_builder import ScoreBuilder

__all__ = [
    # Legacy
    'SheetMusicOCR',
    'MusicXMLConverter',
    # Text extraction
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
    # Analysis
    'ScoreAnalyzer',
    'ScoreMetadata',
    # Validation
    'MusicXMLValidator',
    'ValidationReport',
    # Voice detection
    'VoiceDetector',
    'VoiceDetectionResult',
    # Lyrics
    'LyricsAligner',
    # New pipeline modules
    'TextClassifier',
    'ClassifiedText',
    'StaffDetector',
    'StaffLayout',
    'StaffSplitter',
    'ScoreBuilder',
]
