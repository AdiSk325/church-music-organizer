"""Tests for OCR module: MusicXMLConverter, SheetMusicOCR, and ScanProcessor."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.database.models import FileType
from src.ocr import MusicXMLConverter, ScanProcessor, ScanProcessingResult, SheetMusicOCR


# ---------------------------------------------------------------------------
# MusicXMLConverter tests
# ---------------------------------------------------------------------------


class TestMusicXMLConverter:
    """Tests for MusicXMLConverter."""

    @pytest.fixture
    def converter(self, tmp_path):
        return MusicXMLConverter(output_dir=str(tmp_path))

    def test_create_from_metadata_basic(self, converter):
        """Test creating a score from basic metadata."""
        score = converter.create_from_metadata(title="Ave Maria")
        assert score.metadata.title == "Ave Maria"

    def test_create_from_metadata_with_composer(self, converter):
        """Test creating a score with composer."""
        score = converter.create_from_metadata(title="Ave Maria", composer="Schubert")
        assert score.metadata.composer == "Schubert"

    def test_create_from_metadata_with_key_and_time(self, converter):
        """Test creating a score with key and time signatures."""
        score = converter.create_from_metadata(
            title="Test", key="C major", time_sig="3/4"
        )
        assert score.metadata.title == "Test"
        # The score should have a part with a measure
        parts = list(score.parts)
        assert len(parts) == 1

    def test_create_score_with_lyrics(self, converter):
        """Test creating a score with lyrics produces notes with lyric text."""
        score = converter.create_score_with_lyrics(
            title="Psalm 23",
            composer="Bach",
            lyrics="Pan jest pasterzem moim",
        )
        assert score.metadata.title == "Psalm 23"
        assert score.metadata.composer == "Bach"

        # The score should contain notes with lyrics
        parts = list(score.parts)
        assert len(parts) == 1
        notes = list(parts[0].flatten().notes)
        assert len(notes) == 4  # Four words in lyrics
        assert notes[0].lyric == "Pan"
        assert notes[1].lyric == "jest"
        assert notes[2].lyric == "pasterzem"
        assert notes[3].lyric == "moim"

    def test_create_score_with_empty_lyrics(self, converter):
        """Test creating a score with empty lyrics produces a rest."""
        score = converter.create_score_with_lyrics(title="Empty", lyrics="")
        parts = list(score.parts)
        assert len(parts) == 1
        # Should contain at least one rest
        rests = list(parts[0].flatten().notesAndRests)
        assert len(rests) >= 1

    def test_create_score_with_no_lyrics(self, converter):
        """Test creating a score with no lyrics argument."""
        score = converter.create_score_with_lyrics(title="No Lyrics")
        parts = list(score.parts)
        assert len(parts) == 1

    def test_save_as_musicxml(self, converter, tmp_path):
        """Test saving a score as MusicXML."""
        score = converter.create_score_with_lyrics(title="Test Save", lyrics="Hello world")
        output_path = str(tmp_path / "test.musicxml")
        result = converter.save_as_musicxml(score, output_path)
        assert result is True
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0

    def test_validate_musicxml(self, converter, tmp_path):
        """Test validating a MusicXML file."""
        score = converter.create_score_with_lyrics(title="Validation Test", lyrics="test")
        output_path = str(tmp_path / "valid.musicxml")
        converter.save_as_musicxml(score, output_path)
        assert converter.validate_musicxml(output_path) is True

    def test_validate_invalid_musicxml(self, converter, tmp_path):
        """Test validation fails for non-MusicXML content."""
        bad_path = str(tmp_path / "bad.musicxml")
        with open(bad_path, "w") as f:
            f.write("this is not valid musicxml")
        assert converter.validate_musicxml(bad_path) is False

    def test_convert_to_musescore_not_installed(self, converter, tmp_path):
        """Test convert_to_musescore returns False when MuseScore is not installed."""
        score = converter.create_score_with_lyrics(title="Test", lyrics="test")
        musicxml_path = str(tmp_path / "test.musicxml")
        converter.save_as_musicxml(score, musicxml_path)
        output_path = str(tmp_path / "test.mscz")
        result = converter.convert_to_musescore(musicxml_path, output_path)
        assert result is False

    def test_create_score_lyrics_with_key_and_time(self, converter):
        """Test score with lyrics, key, and time signature."""
        score = converter.create_score_with_lyrics(
            title="Full Test",
            composer="Composer",
            lyrics="Do Re Mi Fa Sol La Ti",
            key_sig="G major",
            time_sig="3/4",
        )
        parts = list(score.parts)
        notes = list(parts[0].flatten().notes)
        # 7 words spread across measures of 3 beats
        assert len(notes) == 7


# ---------------------------------------------------------------------------
# SheetMusicOCR tests
# ---------------------------------------------------------------------------


class TestSheetMusicOCR:
    """Tests for SheetMusicOCR (unit-level, no Tesseract required)."""

    @pytest.fixture
    def ocr(self, tmp_path):
        return SheetMusicOCR(output_dir=str(tmp_path))

    def test_init_creates_output_dir(self, tmp_path):
        """Test that the output directory is created on init."""
        out = tmp_path / "ocr_output"
        ocr = SheetMusicOCR(output_dir=str(out))
        assert out.exists()

    def test_calculate_average_confidence_empty(self, ocr):
        """Test confidence calculation with empty data."""
        assert ocr._calculate_average_confidence({"conf": []}) == 0.0

    def test_calculate_average_confidence(self, ocr):
        """Test confidence calculation with valid data."""
        data = {"conf": [80, 90, -1, 70]}
        result = ocr._calculate_average_confidence(data)
        assert result == pytest.approx(80.0)

    def test_extract_text_blocks_empty(self, ocr):
        """Test extracting blocks from empty data."""
        result = ocr._extract_text_blocks({"text": [], "conf": []})
        assert result == []

    def test_extract_text_blocks(self, ocr):
        """Test extracting text blocks from OCR data."""
        data = {
            "text": ["Hello", "World"],
            "conf": [90, 5],
            "left": [10, 100],
            "top": [20, 30],
            "width": [50, 60],
            "height": [15, 15],
        }
        blocks = ocr._extract_text_blocks(data)
        assert len(blocks) == 2
        assert blocks[0]["text"] == "Hello"
        assert blocks[0]["confidence"] == 90

    def test_preprocess_image_with_valid_file(self, ocr, tmp_path):
        """Test preprocessing a real image file."""
        # Create a simple test image
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        img[30:40, :] = 255  # White horizontal line
        import cv2

        img_path = str(tmp_path / "test.png")
        cv2.imwrite(img_path, img)

        result = ocr.preprocess_image(img_path)
        assert isinstance(result, np.ndarray)
        assert len(result.shape) == 2  # Grayscale

    def test_preprocess_image_missing_file(self, ocr):
        """Test preprocessing fails gracefully for missing file."""
        with pytest.raises(FileNotFoundError):
            ocr.preprocess_image("/nonexistent/image.png")

    def test_detect_staff_regions_empty_image(self, ocr, tmp_path):
        """Test staff detection on a blank image."""
        import cv2

        blank = np.ones((200, 400), dtype=np.uint8) * 255
        path = str(tmp_path / "blank.png")
        cv2.imwrite(path, blank)
        regions = ocr.detect_staff_regions(path)
        assert isinstance(regions, list)

    def test_detect_staff_regions_with_lines(self, ocr, tmp_path):
        """Test staff detection finds horizontal line regions."""
        import cv2

        # Create image with thick horizontal black lines (simulating a staff)
        img = np.ones((300, 600), dtype=np.uint8) * 255
        for y in range(100, 150, 10):
            img[y : y + 3, 20:580] = 0  # black line, 3px thick across most of width
        path = str(tmp_path / "staff.png")
        cv2.imwrite(path, img)
        regions = ocr.detect_staff_regions(path)
        assert isinstance(regions, list)

    def test_detect_music_notation_missing_file(self, ocr):
        """Test music detection returns False for missing file."""
        assert ocr.detect_music_notation("/nonexistent.png") is False


# ---------------------------------------------------------------------------
# ScanProcessor tests
# ---------------------------------------------------------------------------


class TestScanProcessor:
    """Tests for ScanProcessor."""

    @pytest.fixture
    def processor(self, tmp_path):
        return ScanProcessor(output_dir=str(tmp_path))

    def test_init_creates_output_dir(self, tmp_path):
        """Test processor creates output directory."""
        out = tmp_path / "scan_output"
        proc = ScanProcessor(output_dir=str(out))
        assert out.exists()

    def test_process_pdf_missing_file(self, processor):
        """Test process_pdf with non-existent file returns error."""
        result = processor.process_pdf("/nonexistent/file.pdf")
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_process_image_missing_file(self, processor):
        """Test process_image with non-existent file returns error."""
        result = processor.process_image("/nonexistent/image.png")
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_scan_processing_result_defaults(self):
        """Test ScanProcessingResult has correct defaults."""
        result = ScanProcessingResult()
        assert result.source_path == ""
        assert result.lyrics == ""
        assert result.text_blocks == []
        assert result.text_confidence == 0.0
        assert result.music_detected is False
        assert result.musicxml_path is None
        assert result.omr_backend is None
        assert result.page_results == []
        assert result.errors == []

    def test_create_skeleton_musicxml(self, processor, tmp_path):
        """Test skeleton MusicXML creation."""
        path = processor._create_skeleton_musicxml(
            title="Test Piece", composer="Composer", lyrics="Pan jest pasterzem"
        )
        assert path is not None
        assert os.path.exists(path)
        assert path.endswith(".musicxml")

    def test_run_audiveris_not_installed(self, processor, tmp_path):
        """Test that _run_audiveris returns None when Audiveris is not on PATH."""
        result = processor._run_audiveris("/some/file.pdf")
        assert result is None

    def test_run_omr_fallback_to_skeleton(self, processor, tmp_path):
        """Test that _run_omr falls back to skeleton when Audiveris is not available."""
        result = processor._run_omr("/some/input.pdf", title="Fallback Test")
        assert result is not None
        assert os.path.exists(result)


# ---------------------------------------------------------------------------
# FileType enum tests
# ---------------------------------------------------------------------------


class TestFileTypeMusicXML:
    """Test that MUSICXML file type is available."""

    def test_musicxml_filetype_exists(self):
        """Test that FileType.MUSICXML is defined."""
        assert FileType.MUSICXML.value == "musicxml"

    def test_all_filetypes(self):
        """Test that expected file types including MUSICXML exist."""
        expected_subset = {"scan", "pdf", "musescore", "xml", "musicxml", "text", "other"}
        actual = {ft.value for ft in FileType}
        assert expected_subset.issubset(actual)
