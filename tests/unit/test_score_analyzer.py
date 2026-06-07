"""Unit tests for ScoreAnalyzer and PdfToMusicXml."""

import pytest
from music21 import chord, clef, duration, instrument, key, meter, note, stream, tempo


def _make_satb_score(measures: int = 4, key_sig: str = "C", time_sig: str = "4/4") -> stream.Score:
    """Build a minimal 4-part SATB score for testing."""
    sc = stream.Score()

    satb_pitches = {
        "Soprano": ["E5", "D5", "C5", "E5"],
        "Alto": ["C5", "B4", "G4", "G4"],
        "Tenor": ["G4", "G4", "E4", "C4"],
        "Bass": ["C3", "G3", "C4", "C4"],
    }

    for voice_name, pitches in satb_pitches.items():
        part = stream.Part()
        part.partName = voice_name
        part.append(key.Key(key_sig))
        part.append(meter.TimeSignature(time_sig))

        for m_idx in range(measures):
            m = stream.Measure(number=m_idx + 1)
            for p in pitches:
                n = note.Note(p)
                n.duration = duration.Duration(1.0)
                m.append(n)
            part.append(m)

        sc.insert(0, part)

    return sc


def _make_unison_score() -> stream.Score:
    """Single-part score for monophony test."""
    sc = stream.Score()
    part = stream.Part()
    part.partName = "Soprano"
    m = stream.Measure(number=1)
    for p in ["C5", "D5", "E5", "F5"]:
        n = note.Note(p)
        n.duration = duration.Duration(1.0)
        m.append(n)
    part.append(m)
    sc.insert(0, part)
    return sc


# ---------------------------------------------------------------------------
# ScoreAnalyzer
# ---------------------------------------------------------------------------


class TestScoreAnalyzer:
    def setup_method(self):
        from src.analysis.score_analyzer import ScoreAnalyzer

        self.analyzer = ScoreAnalyzer()

    def test_voice_count(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert d.voice_count == 4

    def test_voice_names(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert "Soprano" in d.voice_names
        assert "Bass" in d.voice_names

    def test_measure_count(self):
        sc = _make_satb_score(measures=8)
        d = self.analyzer.analyze(sc)
        assert d.measure_count == 8

    def test_time_signature(self):
        sc = _make_satb_score(time_sig="3/4")
        d = self.analyzer.analyze(sc)
        assert "3/4" in d.time_signatures

    def test_key_detected(self):
        sc = _make_satb_score(key_sig="G")
        d = self.analyzer.analyze(sc)
        # Key should be detected (may be G major or related key)
        assert d.detected_key is not None
        assert d.key_confidence > 0.0

    def test_texture_homophonic(self):
        # All voices move together → homophonic
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert d.texture_type in ("homophonic_chorale", "homophonic_melody")
        assert d.onset_simultaneity > 0.5

    def test_voice_ranges_populated(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert len(d.voice_ranges) == 4
        for vr in d.voice_ranges:
            assert vr.lowest_pitch != "?"
            assert vr.range_semitones >= 0

    def test_no_lyrics(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert d.has_lyrics is False
        assert d.text_setting_type == "instrumental"

    def test_lyrics_detection(self):
        sc = stream.Score()
        part = stream.Part()
        part.partName = "Soprano"
        m = stream.Measure(number=1)
        for pitch_str, syllable in [("E5", "Ky-"), ("D5", "-ri-"), ("C5", "-e"), ("G4", "e-")]:
            n = note.Note(pitch_str)
            n.duration = duration.Duration(1.0)
            from music21 import note as m21note

            lyr = m21note.Lyric(text=syllable)
            n.lyrics = [lyr]
            m.append(n)
        part.append(m)
        sc.insert(0, part)
        d = self.analyzer.analyze(sc)
        assert d.has_lyrics is True

    def test_difficulty_grade_range(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert 1 <= d.estimated_grade <= 6
        assert d.grade_label in ("elementary", "intermediate", "advanced")

    def test_narrative_not_empty(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert d.narrative_description
        assert len(d.narrative_description) > 50

    def test_monophonic_texture(self):
        sc = _make_unison_score()
        d = self.analyzer.analyze(sc)
        assert d.voice_count == 1
        assert d.texture_type == "monophonic"

    def test_chromatic_complexity_range(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        assert 0.0 <= d.chromatic_complexity <= 1.0

    def test_to_dict_serialisable(self):
        import json

        sc = _make_satb_score()
        d = self.analyzer.analyze(sc)
        raw = d.to_dict()
        # Should not raise
        json.dumps(raw)

    def test_source_file_stored(self):
        sc = _make_satb_score()
        d = self.analyzer.analyze(sc, source_file="/path/to/test.xml")
        assert d.source_file == "/path/to/test.xml"


# ---------------------------------------------------------------------------
# Language detector
# ---------------------------------------------------------------------------


class TestLanguageDetector:
    def setup_method(self):
        from src.analysis.score_analyzer import _detect_language

        self._detect = _detect_language

    def test_latin_detected(self):
        lang, conf = self._detect("Kyrie eleison Christe eleison Dominus")
        assert lang == "la"
        assert conf > 0.3

    def test_polish_detected(self):
        lang, conf = self._detect("Boże Panie Jezu Chryste Chwała niebo ziemia")
        assert lang == "pl"
        assert conf > 0.3

    def test_german_detected(self):
        lang, conf = self._detect("Herr Gott Heilig Ehre Halleluja Seele Liebe Gnade")
        assert lang == "de"
        assert conf > 0.3

    def test_english_detected(self):
        lang, conf = self._detect("Lord God Holy Glory Praise Alleluia Love Grace")
        assert lang == "en"
        assert conf > 0.3

    def test_empty_text(self):
        lang, conf = self._detect("")
        assert lang == "unknown"
        assert conf == 0.0


# ---------------------------------------------------------------------------
# PdfToMusicXml quality report
# ---------------------------------------------------------------------------


class TestQualityReport:
    def test_quality_report_same_file(self, tmp_path):
        """Quality report comparing a file with itself should score 1.0."""
        from music21 import converter

        from src.ocr.pdf_to_musicxml import PdfToMusicXml

        sc = _make_satb_score(measures=4)
        xml_path = str(tmp_path / "test.xml")
        sc.write("musicxml", fp=xml_path)

        conv = PdfToMusicXml()
        report = conv.conversion_quality_report(xml_path, xml_path)

        assert "error" not in report
        assert report["overall_score"] == pytest.approx(1.0, abs=0.01)
        assert report["key_match"] is True
        assert report["voice_count_match"] is True

    def test_quality_report_missing_file(self, tmp_path):
        from src.ocr.pdf_to_musicxml import PdfToMusicXml

        conv = PdfToMusicXml()
        report = conv.conversion_quality_report("/nonexistent.xml", "/also_nonexistent.xml")
        assert "error" in report

    def test_audiveris_unavailable(self):
        from src.ocr.pdf_to_musicxml import PdfToMusicXml

        conv = PdfToMusicXml(audiveris_path=None)
        # When Audiveris is not installed, is_available should reflect that
        # (in CI this will typically be False)
        assert isinstance(conv.is_available, bool)


# ---------------------------------------------------------------------------
# AnalysisService
# ---------------------------------------------------------------------------


class TestAnalysisService:
    def test_analyze_file_returns_descriptor(self, tmp_path):
        from src.services.analysis_service import AnalysisService

        sc = _make_satb_score(measures=4)
        xml_path = str(tmp_path / "piece.xml")
        sc.write("musicxml", fp=xml_path)

        svc = AnalysisService()
        d = svc.analyze_file(xml_path)

        assert d is not None
        assert d.voice_count == 4
        assert d.measure_count == 4

    def test_analyze_file_missing(self):
        from src.services.analysis_service import AnalysisService

        svc = AnalysisService()
        d = svc.analyze_file("/nonexistent/file.xml")
        assert d is None
