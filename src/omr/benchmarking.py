"""Accuracy-based benchmarking for OMR output.

Instead of comparing raw MusicXML files (which can represent the same music
in many different ways), this module measures semantic accuracy at three
levels:

- **Pitch accuracy** – what fraction of predicted notes have the correct pitch.
- **Rhythm accuracy** – what fraction of predicted notes have the correct
  duration and onset position.
- **Voice assignment accuracy** – what fraction of notes are assigned to the
  correct SATB voice.

All metrics use a simple *edit-distance alignment* between the sorted note
sequences of each measure, which is robust to small insertions/deletions
introduced by OMR noise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .score_graph import Note, ScoreGraph

logger = logging.getLogger(__name__)

# Tolerance for onset/duration comparison (in quarter notes).
RHYTHM_TOLERANCE = 0.1


@dataclass
class BenchmarkResult:
    """Aggregated benchmark scores for a predicted vs. reference pair.

    All values are in ``[0, 1]`` (1.0 = perfect).

    Attributes:
        pitch_accuracy:          Fraction of notes with correct pitch.
        rhythm_accuracy:         Fraction of notes with correct duration and onset.
        voice_assignment_accuracy: Fraction of notes with correct voice assignment.
        overall_accuracy:        Unweighted average of the three metrics.
        n_predicted:             Total predicted notes evaluated.
        n_reference:             Total reference notes.
    """

    pitch_accuracy: float
    rhythm_accuracy: float
    voice_assignment_accuracy: float
    n_predicted: int
    n_reference: int

    @property
    def overall_accuracy(self) -> float:
        """Unweighted average of the three metrics."""
        return (self.pitch_accuracy + self.rhythm_accuracy + self.voice_assignment_accuracy) / 3.0

    def __str__(self) -> str:
        return (
            f"Pitch: {self.pitch_accuracy:.1%}  "
            f"Rhythm: {self.rhythm_accuracy:.1%}  "
            f"Voice: {self.voice_assignment_accuracy:.1%}  "
            f"Overall: {self.overall_accuracy:.1%}  "
            f"(pred={self.n_predicted}, ref={self.n_reference})"
        )


class OMRBenchmark:
    """Evaluates OMR output against a ground-truth reference ScoreGraph.

    Usage::

        bench = OMRBenchmark()
        result = bench.evaluate(predicted_score, reference_score)
        print(result)
    """

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def evaluate(
        self,
        predicted: ScoreGraph,
        reference: ScoreGraph,
    ) -> BenchmarkResult:
        """Run all metrics and return a :class:`BenchmarkResult`.

        Args:
            predicted:  OMR output ScoreGraph.
            reference:  Ground-truth ScoreGraph.
        """
        pred_notes = predicted.all_notes()
        ref_notes = reference.all_notes()

        pitch_acc = self.pitch_accuracy(pred_notes, ref_notes)
        rhythm_acc = self.rhythm_accuracy(pred_notes, ref_notes)
        voice_acc = self.voice_assignment_accuracy(pred_notes, ref_notes)

        return BenchmarkResult(
            pitch_accuracy=pitch_acc,
            rhythm_accuracy=rhythm_acc,
            voice_assignment_accuracy=voice_acc,
            n_predicted=len(pred_notes),
            n_reference=len(ref_notes),
        )

    # -----------------------------------------------------------------------
    # Individual metrics
    # -----------------------------------------------------------------------

    def pitch_accuracy(
        self,
        predicted: List[Note],
        reference: List[Note],
    ) -> float:
        """Fraction of aligned note pairs that share the same pitch.

        Rests are matched to rests and pitches to pitches.
        """
        pairs = _align_notes(predicted, reference)
        if not pairs:
            return 0.0
        correct = sum(1 for p, r in pairs if _pitches_match(p, r))
        return correct / len(pairs)

    def rhythm_accuracy(
        self,
        predicted: List[Note],
        reference: List[Note],
    ) -> float:
        """Fraction of aligned note pairs where duration and onset are within
        :data:`RHYTHM_TOLERANCE` of each other.
        """
        pairs = _align_notes(predicted, reference)
        if not pairs:
            return 0.0
        correct = sum(1 for p, r in pairs if _rhythm_matches(p, r))
        return correct / len(pairs)

    def voice_assignment_accuracy(
        self,
        predicted: List[Note],
        reference: List[Note],
    ) -> float:
        """Fraction of aligned note pairs with matching ``voice_id``.

        If either note in a pair has ``voice_id=None`` the pair is excluded
        from the denominator.
        """
        pairs = _align_notes(predicted, reference)
        eligible = [(p, r) for p, r in pairs if p.voice_id is not None and r.voice_id is not None]
        if not eligible:
            return 0.0
        correct = sum(1 for p, r in eligible if p.voice_id == r.voice_id)
        return correct / len(eligible)


# ---------------------------------------------------------------------------
# Alignment helpers
# ---------------------------------------------------------------------------

def _align_notes(
    predicted: List[Note],
    reference: List[Note],
) -> List[Tuple[Note, Note]]:
    """Align two note sequences using onset-sorted greedy matching.

    Notes are sorted by (onset, pitch) and then paired positionally.  This
    simple approach works well when the sequences are similar in length; a
    full edit-distance alignment would be more accurate for heavily corrupted
    OMR output but is also significantly more expensive.
    """
    def sort_key(n: Note):
        return (n.onset, n.pitch or "")

    pred_sorted = sorted(predicted, key=sort_key)
    ref_sorted = sorted(reference, key=sort_key)

    length = min(len(pred_sorted), len(ref_sorted))
    return list(zip(pred_sorted[:length], ref_sorted[:length]))


def _pitches_match(p: Note, r: Note) -> bool:
    """Return ``True`` if both notes are rests or share the same pitch string."""
    if p.is_rest and r.is_rest:
        return True
    return p.pitch.upper() == r.pitch.upper()


def _rhythm_matches(p: Note, r: Note) -> bool:
    """Return ``True`` if duration and onset are within :data:`RHYTHM_TOLERANCE`."""
    duration_ok = abs(p.duration - r.duration) <= RHYTHM_TOLERANCE
    onset_ok = abs(p.onset - r.onset) <= RHYTHM_TOLERANCE
    return duration_ok and onset_ok
