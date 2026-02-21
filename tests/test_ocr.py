"""Tests for OCR module: MusicXMLConverter."""

import os

import pytest

from src.database.models import FileType
from src.ocr import MusicXMLConverter


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
