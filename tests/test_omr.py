"""Tests for the OMR module (ScoreGraph IR, constraints, benchmarking)."""

import pytest

from src.omr.score_graph import (
    Measure,
    Note,
    ScoreGraph,
    Voice,
    VoiceType,
    pitch_to_midi,
)
from src.omr.constraints import ConstraintEngine, ConstraintViolation
from src.omr.benchmarking import OMRBenchmark, BenchmarkResult, _align_notes
from src.omr.llm_repair import LLMRepairTool, _midi_to_pitch_string
from src.omr.reference_matcher import ReferenceMatcher


# ---------------------------------------------------------------------------
# ScoreGraph / data model tests
# ---------------------------------------------------------------------------

class TestNote:
    def test_is_rest_for_rest_note(self):
        n = Note(pitch="R", duration=1.0, onset=0.0)
        assert n.is_rest is True

    def test_is_rest_lowercase(self):
        n = Note(pitch="r", duration=1.0, onset=0.0)
        assert n.is_rest is True

    def test_is_not_rest_for_pitched_note(self):
        n = Note(pitch="C4", duration=1.0, onset=0.0)
        assert n.is_rest is False

    def test_midi_for_c4(self):
        n = Note(pitch="C4", duration=1.0, onset=0.0)
        assert n.midi == 60

    def test_midi_for_a4(self):
        n = Note(pitch="A4", duration=1.0, onset=0.0)
        assert n.midi == 69

    def test_midi_for_sharp(self):
        n = Note(pitch="C#4", duration=1.0, onset=0.0)
        assert n.midi == 61

    def test_midi_none_for_rest(self):
        n = Note(pitch="R", duration=1.0, onset=0.0)
        assert n.midi is None


class TestPitchToMidi:
    def test_c4(self):
        assert pitch_to_midi("C4") == 60

    def test_d5(self):
        assert pitch_to_midi("D5") == 74

    def test_flat(self):
        assert pitch_to_midi("Bb4") == 70

    def test_rest_returns_none(self):
        assert pitch_to_midi("R") is None

    def test_invalid_returns_none(self):
        assert pitch_to_midi("?") is None


class TestVoice:
    def test_total_duration(self):
        notes = [
            Note(pitch="C4", duration=1.0, onset=0.0),
            Note(pitch="D4", duration=1.0, onset=1.0),
        ]
        voice = Voice(voice_id=0, notes=notes)
        assert voice.total_duration() == 2.0

    def test_empty_voice_duration(self):
        voice = Voice(voice_id=0)
        assert voice.total_duration() == 0.0


class TestMeasure:
    def test_expected_duration_4_4(self):
        m = Measure(number=1, time_signature="4/4")
        assert m.expected_duration() == 4.0

    def test_expected_duration_3_4(self):
        m = Measure(number=1, time_signature="3/4")
        assert m.expected_duration() == 3.0

    def test_expected_duration_6_8(self):
        m = Measure(number=1, time_signature="6/8")
        assert m.expected_duration() == pytest.approx(3.0)

    def test_all_notes_aggregates_voices(self):
        notes_a = [Note(pitch="C4", duration=1.0, onset=0.0)]
        notes_b = [Note(pitch="G3", duration=1.0, onset=0.0)]
        m = Measure(
            number=1,
            voices=[
                Voice(voice_id=0, notes=notes_a),
                Voice(voice_id=1, notes=notes_b),
            ],
        )
        assert len(m.all_notes()) == 2


class TestScoreGraph:
    def test_total_measures(self):
        sg = ScoreGraph(measures=[Measure(number=1), Measure(number=2)])
        assert sg.total_measures() == 2

    def test_all_notes_flat(self):
        notes = [Note(pitch="C4", duration=1.0, onset=0.0)]
        sg = ScoreGraph(
            measures=[
                Measure(number=1, voices=[Voice(voice_id=0, notes=notes)]),
            ]
        )
        assert len(sg.all_notes()) == 1

    def test_voice_ids(self):
        sg = ScoreGraph(
            measures=[
                Measure(
                    number=1,
                    voices=[
                        Voice(voice_id=0),
                        Voice(voice_id=2),
                    ],
                ),
            ]
        )
        assert sg.voice_ids() == [0, 2]


# ---------------------------------------------------------------------------
# Constraint engine tests
# ---------------------------------------------------------------------------

class TestConstraintEngine:
    def _make_valid_measure(self, time_sig="4/4") -> Measure:
        """Create a measure that satisfies all constraints."""
        notes = [
            Note(pitch="E5", duration=1.0, onset=0.0, voice_id=0),  # Soprano
            Note(pitch="E5", duration=1.0, onset=1.0, voice_id=0),
            Note(pitch="E5", duration=1.0, onset=2.0, voice_id=0),
            Note(pitch="E5", duration=1.0, onset=3.0, voice_id=0),
        ]
        return Measure(
            number=1,
            time_signature=time_sig,
            voices=[Voice(voice_id=0, voice_type=VoiceType.SOPRANO, notes=notes)],
        )

    def test_no_violations_for_valid_measure(self):
        engine = ConstraintEngine()
        measure = self._make_valid_measure()
        violations = engine.validate_time_signature(measure)
        assert violations == []

    def test_time_signature_violation_detected(self):
        engine = ConstraintEngine()
        # Only 3 beats in a 4/4 measure
        notes = [
            Note(pitch="C4", duration=1.0, onset=0.0, voice_id=0),
            Note(pitch="D4", duration=1.0, onset=1.0, voice_id=0),
            Note(pitch="E4", duration=1.0, onset=2.0, voice_id=0),
        ]
        measure = Measure(
            number=1,
            time_signature="4/4",
            voices=[Voice(voice_id=0, notes=notes)],
        )
        violations = engine.validate_time_signature(measure)
        assert len(violations) == 1
        assert violations[0].severity == "error"

    def test_satb_range_violation_soprano_too_low(self):
        engine = ConstraintEngine()
        # Soprano singing E2 is out of range
        notes = [Note(pitch="E2", duration=4.0, onset=0.0, voice_id=0)]
        measure = Measure(
            number=1,
            voices=[Voice(voice_id=0, voice_type=VoiceType.SOPRANO, notes=notes)],
        )
        violations = engine.validate_satb_voice_ranges(measure)
        assert len(violations) == 1
        assert "soprano" in violations[0].description.lower()

    def test_satb_unassigned_voices_skipped(self):
        engine = ConstraintEngine()
        notes = [Note(pitch="E2", duration=4.0, onset=0.0, voice_id=0)]
        measure = Measure(
            number=1,
            voices=[Voice(voice_id=0, voice_type=VoiceType.UNASSIGNED, notes=notes)],
        )
        violations = engine.validate_satb_voice_ranges(measure)
        assert violations == []

    def test_voice_crossing_detected(self):
        engine = ConstraintEngine()
        # Bass singing higher than Soprano at same onset
        soprano_notes = [Note(pitch="C4", duration=4.0, onset=0.0, voice_id=0)]  # MIDI 60
        bass_notes = [Note(pitch="G4", duration=4.0, onset=0.0, voice_id=1)]     # MIDI 67
        measure = Measure(
            number=1,
            voices=[
                Voice(voice_id=0, voice_type=VoiceType.SOPRANO, notes=soprano_notes),
                Voice(voice_id=1, voice_type=VoiceType.BASS, notes=bass_notes),
            ],
        )
        violations = engine.validate_voice_crossing(measure)
        assert len(violations) >= 1

    def test_validate_all_collects_all_violations(self):
        engine = ConstraintEngine()
        # Duration violation
        notes = [Note(pitch="C4", duration=1.0, onset=0.0, voice_id=0)]
        measure = Measure(
            number=1,
            time_signature="4/4",
            voices=[Voice(voice_id=0, notes=notes)],
        )
        score = ScoreGraph(measures=[measure])
        violations = engine.validate_all(score)
        assert any(isinstance(v, ConstraintViolation) for v in violations)

    def test_no_violations_for_valid_score(self):
        engine = ConstraintEngine()
        notes = [
            Note(pitch="E5", duration=1.0, onset=i * 1.0, voice_id=0)
            for i in range(4)
        ]
        measure = Measure(
            number=1,
            time_signature="4/4",
            voices=[Voice(voice_id=0, voice_type=VoiceType.SOPRANO, notes=notes)],
        )
        score = ScoreGraph(measures=[measure])
        assert engine.validate_all(score) == []


# ---------------------------------------------------------------------------
# LLM repair heuristics tests
# ---------------------------------------------------------------------------

class TestLLMRepairHeuristics:
    def test_heuristic_trims_overflow(self):
        tool = LLMRepairTool()
        notes = [
            Note(pitch="C4", duration=3.0, onset=0.0, voice_id=0),
            Note(pitch="D4", duration=3.0, onset=3.0, voice_id=0),  # overflow
        ]
        measure = Measure(
            number=1,
            time_signature="4/4",
            voices=[Voice(voice_id=0, notes=notes)],
        )
        from src.omr.constraints import ConstraintViolation
        violations = [
            ConstraintViolation(measure_number=1, voice_id=0, description="overflow")
        ]
        repaired = tool._heuristic_repair(measure, violations)
        voice = repaired.voices[0]
        total = voice.total_duration()
        assert abs(total - 4.0) < 0.01

    def test_heuristic_pads_underflow(self):
        tool = LLMRepairTool()
        notes = [Note(pitch="C4", duration=2.0, onset=0.0, voice_id=0)]
        measure = Measure(
            number=1,
            time_signature="4/4",
            voices=[Voice(voice_id=0, notes=notes)],
        )
        from src.omr.constraints import ConstraintViolation
        violations = [
            ConstraintViolation(measure_number=1, voice_id=0, description="underflow")
        ]
        repaired = tool._heuristic_repair(measure, violations)
        voice = repaired.voices[0]
        total = voice.total_duration()
        assert abs(total - 4.0) < 0.01
        # Last note should be a rest
        assert repaired.voices[0].notes[-1].is_rest

    def test_heuristic_clamps_out_of_range_pitch(self):
        tool = LLMRepairTool()
        # Soprano note way below range: MIDI 20 (G#0)
        notes = [Note(pitch="G#0", duration=4.0, onset=0.0, voice_id=0)]
        measure = Measure(
            number=1,
            time_signature="4/4",
            voices=[Voice(voice_id=0, voice_type=VoiceType.SOPRANO, notes=notes)],
        )
        from src.omr.constraints import ConstraintViolation
        violations = [
            ConstraintViolation(measure_number=1, voice_id=0, description="out of range")
        ]
        repaired = tool._heuristic_repair(measure, violations)
        voice = repaired.voices[0]
        repaired_note = voice.notes[0]
        midi = repaired_note.midi
        low, high = 60, 79  # Soprano range
        assert midi is not None
        assert low <= midi <= high

    def test_midi_to_pitch_string(self):
        assert _midi_to_pitch_string(60) == "C4"
        assert _midi_to_pitch_string(69) == "A4"
        assert _midi_to_pitch_string(71) == "B4"


# ---------------------------------------------------------------------------
# Benchmarking tests
# ---------------------------------------------------------------------------

class TestOMRBenchmark:
    def _make_score(self, pitches, durations=None, onsets=None, voice_id=0):
        if durations is None:
            durations = [1.0] * len(pitches)
        if onsets is None:
            onsets = list(range(len(pitches)))
        notes = [
            Note(pitch=p, duration=d, onset=o, voice_id=voice_id)
            for p, d, o in zip(pitches, durations, onsets)
        ]
        return ScoreGraph(
            measures=[Measure(number=1, voices=[Voice(voice_id=voice_id, notes=notes)])]
        )

    def test_perfect_pitch_accuracy(self):
        bench = OMRBenchmark()
        score = self._make_score(["C4", "D4", "E4"])
        result = bench.evaluate(score, score)
        assert result.pitch_accuracy == pytest.approx(1.0)

    def test_zero_pitch_accuracy(self):
        bench = OMRBenchmark()
        pred = self._make_score(["C4", "D4", "E4"])
        ref = self._make_score(["G4", "A4", "B4"])
        result = bench.evaluate(pred, ref)
        assert result.pitch_accuracy == pytest.approx(0.0)

    def test_partial_pitch_accuracy(self):
        bench = OMRBenchmark()
        pred = self._make_score(["C4", "D4", "E4"])
        ref = self._make_score(["C4", "A4", "B4"])
        result = bench.evaluate(pred, ref)
        assert result.pitch_accuracy == pytest.approx(1 / 3)

    def test_perfect_rhythm_accuracy(self):
        bench = OMRBenchmark()
        score = self._make_score(["C4", "D4"], [1.0, 1.0], [0.0, 1.0])
        result = bench.evaluate(score, score)
        assert result.rhythm_accuracy == pytest.approx(1.0)

    def test_voice_assignment_accuracy(self):
        bench = OMRBenchmark()
        pred = self._make_score(["C4", "D4"], voice_id=0)
        ref = self._make_score(["C4", "D4"], voice_id=1)
        result = bench.evaluate(pred, ref)
        assert result.voice_assignment_accuracy == pytest.approx(0.0)

    def test_overall_accuracy_average(self):
        bench = OMRBenchmark()
        score = self._make_score(["C4", "D4"])
        result = bench.evaluate(score, score)
        assert result.overall_accuracy == pytest.approx(
            (result.pitch_accuracy + result.rhythm_accuracy + result.voice_assignment_accuracy) / 3
        )

    def test_benchmark_result_str(self):
        result = BenchmarkResult(
            pitch_accuracy=0.9,
            rhythm_accuracy=0.8,
            voice_assignment_accuracy=0.7,
            n_predicted=10,
            n_reference=10,
        )
        text = str(result)
        assert "90.0%" in text
        assert "80.0%" in text


# ---------------------------------------------------------------------------
# Reference matcher tests
# ---------------------------------------------------------------------------

class TestReferenceMatcher:
    def _make_score(self, key, time_sig, pitches, title="test") -> ScoreGraph:
        notes = [Note(pitch=p, duration=1.0, onset=float(i)) for i, p in enumerate(pitches)]
        return ScoreGraph(
            title=title,
            key_signature=key,
            time_signature=time_sig,
            measures=[Measure(number=1, voices=[Voice(voice_id=0, notes=notes)])],
        )

    def test_empty_corpus_returns_no_results(self):
        matcher = ReferenceMatcher()
        query = self._make_score("C", "4/4", ["C4", "D4"])
        assert matcher.find_nearest(query) == []

    def test_identical_score_is_top_match(self):
        matcher = ReferenceMatcher()
        score_a = self._make_score("C", "4/4", ["C4", "D4", "E4"], "A")
        score_b = self._make_score("G", "3/4", ["G3", "A3", "B3"], "B")
        matcher.add_reference(score_a)
        matcher.add_reference(score_b)

        results = matcher.find_nearest(score_a, top_k=2)
        assert results[0].score.title == "A"
        assert results[0].similarity == pytest.approx(1.0)

    def test_similarity_bounds(self):
        matcher = ReferenceMatcher()
        ref = self._make_score("C", "4/4", ["C4", "D4"])
        matcher.add_reference(ref)

        query = self._make_score("G", "3/4", ["G3", "A3"])
        results = matcher.find_nearest(query, top_k=1)
        assert 0.0 <= results[0].similarity <= 1.0

    def test_top_k_limits_results(self):
        matcher = ReferenceMatcher()
        for i in range(5):
            matcher.add_reference(self._make_score("C", "4/4", ["C4"], title=f"score_{i}"))
        results = matcher.find_nearest(self._make_score("C", "4/4", ["C4"]), top_k=2)
        assert len(results) == 2
