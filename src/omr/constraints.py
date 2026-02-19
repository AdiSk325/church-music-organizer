"""Constraint engine for music-theory validation of ScoreGraph objects.

The constraint engine enforces hard rules that every well-formed score must
satisfy.  It is the core difference between this approach and a naive LLM
approach: *constraints reconstruct* while LLMs only *guess*.

Rules implemented
-----------------
1. ``validate_time_signature`` – sum of note durations per voice must equal the
   expected duration derived from the time signature.
2. ``validate_satb_voice_ranges`` – each note must fall within the standard
   SATB pitch range for its assigned voice type.
3. ``validate_voice_crossing`` – SATB voices must not cross (Soprano ≥ Alto ≥
   Tenor ≥ Bass at each onset position).
4. ``validate_all`` – run all rules and collect all violations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .score_graph import Measure, Note, ScoreGraph, Voice, VoiceType, VOICE_RANGES

logger = logging.getLogger(__name__)

# Ordering used for voice-crossing checks (highest → lowest).
_SATB_ORDER = [VoiceType.SOPRANO, VoiceType.ALTO, VoiceType.TENOR, VoiceType.BASS]


@dataclass
class ConstraintViolation:
    """A single constraint violation found in a ScoreGraph.

    Attributes:
        measure_number: 1-indexed measure where the violation occurred.
        voice_id:       Voice identifier, or ``None`` for score-level issues.
        description:    Human-readable description of the violation.
        severity:       ``'error'`` for structural problems, ``'warning'`` for
                        style issues.
    """

    measure_number: int
    description: str
    voice_id: Optional[int] = None
    severity: str = "error"


class ConstraintEngine:
    """Validates a :class:`~src.omr.score_graph.ScoreGraph` against music-theory
    constraints and collects all violations.

    Usage::

        engine = ConstraintEngine()
        violations = engine.validate_all(score_graph)
        if violations:
            for v in violations:
                print(v.severity, v.description)
    """

    # Tolerance for floating-point duration comparisons (in quarter notes).
    DURATION_TOLERANCE: float = 0.01

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def validate_all(self, score: ScoreGraph) -> List[ConstraintViolation]:
        """Run all registered constraint checks and return every violation."""
        violations: List[ConstraintViolation] = []
        for measure in score.measures:
            violations.extend(self.validate_time_signature(measure))
            violations.extend(self.validate_satb_voice_ranges(measure))
            violations.extend(self.validate_voice_crossing(measure))
        return violations

    # -----------------------------------------------------------------------
    # Individual checks
    # -----------------------------------------------------------------------

    def validate_time_signature(self, measure: Measure) -> List[ConstraintViolation]:
        """Check that note durations per voice sum to the time-signature value."""
        expected = measure.expected_duration()
        violations: List[ConstraintViolation] = []

        for voice in measure.voices:
            total = voice.total_duration()
            if abs(total - expected) > self.DURATION_TOLERANCE:
                violations.append(
                    ConstraintViolation(
                        measure_number=measure.number,
                        voice_id=voice.voice_id,
                        description=(
                            f"Voice {voice.voice_id} in measure {measure.number}: "
                            f"duration {total:.3f} ≠ expected {expected:.3f} "
                            f"(time sig {measure.time_signature})"
                        ),
                        severity="error",
                    )
                )

        return violations

    def validate_satb_voice_ranges(self, measure: Measure) -> List[ConstraintViolation]:
        """Check that notes in typed SATB voices lie within standard pitch ranges."""
        violations: List[ConstraintViolation] = []

        for voice in measure.voices:
            if voice.voice_type == VoiceType.UNASSIGNED:
                continue

            low, high = VOICE_RANGES.get(voice.voice_type, (0, 127))

            for note in voice.notes:
                if note.is_rest:
                    continue
                midi = note.midi
                if midi is None:
                    continue
                if not (low <= midi <= high):
                    violations.append(
                        ConstraintViolation(
                            measure_number=measure.number,
                            voice_id=voice.voice_id,
                            description=(
                                f"Measure {measure.number}, voice {voice.voice_id} "
                                f"({voice.voice_type.value}): pitch '{note.pitch}' "
                                f"(MIDI {midi}) is outside range "
                                f"[{low}, {high}]"
                            ),
                            severity="warning",
                        )
                    )

        return violations

    def validate_voice_crossing(self, measure: Measure) -> List[ConstraintViolation]:
        """Check that SATB voices do not cross each other at any onset position.

        A crossing occurs when a lower voice (e.g. Alto) sounds higher than an
        upper voice (e.g. Soprano) at the same onset point.
        """
        violations: List[ConstraintViolation] = []

        # Build mapping: voice_type → voice
        typed_voices = {
            v.voice_type: v
            for v in measure.voices
            if v.voice_type in _SATB_ORDER
        }

        if len(typed_voices) < 2:
            return violations

        # Collect onsets present in any typed voice
        onsets = sorted(
            {note.onset for vt, voice in typed_voices.items() for note in voice.notes}
        )

        for onset in onsets:
            # Get the highest-pitched note at this onset per voice type.
            pitches_at_onset: Dict[VoiceType, Optional[int]] = {}
            for vt in _SATB_ORDER:
                if vt not in typed_voices:
                    continue
                notes_at = [
                    n for n in typed_voices[vt].notes
                    if abs(n.onset - onset) < 0.01 and not n.is_rest
                ]
                if notes_at:
                    midis = [n.midi for n in notes_at if n.midi is not None]
                    pitches_at_onset[vt] = max(midis) if midis else None
                else:
                    pitches_at_onset[vt] = None

            # Check ordering for all pairs (not just adjacent) so that e.g.
            # Bass crossing Soprano is also detected.
            for i, upper_vt in enumerate(_SATB_ORDER[:-1]):
                for lower_vt in _SATB_ORDER[i + 1:]:
                    if upper_vt not in pitches_at_onset or lower_vt not in pitches_at_onset:
                        continue
                    upper_midi = pitches_at_onset[upper_vt]
                    lower_midi = pitches_at_onset[lower_vt]
                    if upper_midi is None or lower_midi is None:
                        continue
                    if lower_midi > upper_midi:
                        upper_voice = typed_voices[upper_vt]
                        lower_voice = typed_voices[lower_vt]
                        violations.append(
                            ConstraintViolation(
                                measure_number=measure.number,
                                voice_id=lower_voice.voice_id,
                                description=(
                                    f"Measure {measure.number}, onset {onset}: voice "
                                    f"crossing – {lower_vt.value} (MIDI {lower_midi}) "
                                    f"above {upper_vt.value} (MIDI {upper_midi})"
                                ),
                                severity="warning",
                            )
                        )

        return violations
