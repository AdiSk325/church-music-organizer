"""Reference score matcher for nearest-score retrieval.

The reference matcher supports the pipeline stage where a partially-recognised
ScoreGraph is compared against a corpus of known reference scores.  The closest
match(es) can then be used as additional constraints or as a prior for LLM
repair.

Similarity is computed as a combination of:
- Pitch-class histogram overlap
- Time-signature match
- Key-signature match
- Measure count proximity

This is an approximate, lightweight matcher intended for reference-assisted
constraint propagation, not for exact music identification.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .score_graph import ScoreGraph

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """A single result from :meth:`ReferenceMatcher.find_nearest`.

    Attributes:
        score:      The reference :class:`~src.omr.score_graph.ScoreGraph`.
        similarity: Similarity score in ``[0, 1]`` (higher is more similar).
    """

    score: ScoreGraph
    similarity: float


class ReferenceMatcher:
    """Maintains a corpus of reference scores and retrieves nearest matches.

    Usage::

        matcher = ReferenceMatcher()
        matcher.load_from_musicxml("reference_scores/ave_maria.xml")
        results = matcher.find_nearest(omr_output, top_k=3)
        for r in results:
            print(r.score.title, r.similarity)
    """

    def __init__(self) -> None:
        self._references: List[ScoreGraph] = []

    # -----------------------------------------------------------------------
    # Loading references
    # -----------------------------------------------------------------------

    def add_reference(self, score: ScoreGraph) -> None:
        """Add a ScoreGraph to the reference corpus."""
        self._references.append(score)

    def load_from_musicxml(self, musicxml_path: str) -> Optional[ScoreGraph]:
        """Parse a MusicXML file, convert it to a ScoreGraph, add to corpus.

        Returns the parsed ScoreGraph, or ``None`` if parsing fails.
        """
        from .pipeline import OMRPipeline  # local import to avoid circular deps

        try:
            pipeline = OMRPipeline()
            score = pipeline.musicxml_to_score_graph(musicxml_path)
            if score is not None:
                self.add_reference(score)
                logger.info("Loaded reference: '%s'", score.title)
            return score
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load reference '%s': %s", musicxml_path, exc)
            return None

    def load_directory(self, directory: str, pattern: str = "**/*.xml") -> int:
        """Recursively load all MusicXML files in *directory*.

        Args:
            directory: Root directory to search.
            pattern:   Glob pattern for file discovery.

        Returns:
            Number of successfully loaded references.
        """
        loaded = 0
        for path in Path(directory).glob(pattern):
            if self.load_from_musicxml(str(path)) is not None:
                loaded += 1
        return loaded

    # -----------------------------------------------------------------------
    # Retrieval
    # -----------------------------------------------------------------------

    def find_nearest(
        self,
        query: ScoreGraph,
        top_k: int = 3,
    ) -> List[MatchResult]:
        """Return the *top_k* most similar reference scores.

        Args:
            query:  The ScoreGraph to compare against the corpus.
            top_k:  Maximum number of results to return.

        Returns:
            Sorted list of :class:`MatchResult` (highest similarity first).
        """
        if not self._references:
            return []

        scored = [
            MatchResult(score=ref, similarity=self._compute_similarity(query, ref))
            for ref in self._references
        ]
        scored.sort(key=lambda r: r.similarity, reverse=True)
        return scored[:top_k]

    # -----------------------------------------------------------------------
    # Similarity computation
    # -----------------------------------------------------------------------

    def _compute_similarity(self, a: ScoreGraph, b: ScoreGraph) -> float:
        """Compute a similarity score in ``[0, 1]`` between two ScoreGraphs.

        The metric is a weighted average of four components:
        - **time_sig**: 1.0 if identical, 0.0 otherwise (weight 0.2)
        - **key_sig**: 1.0 if identical, 0.0 otherwise (weight 0.2)
        - **length**: normalised measure-count proximity (weight 0.2)
        - **pitch_hist**: cosine similarity of pitch-class histograms (weight 0.4)
        """
        time_sim = 1.0 if a.time_signature == b.time_signature else 0.0
        key_sim = 1.0 if a.key_signature == b.key_signature else 0.0
        length_sim = self._length_similarity(a, b)
        pitch_sim = self._pitch_histogram_similarity(a, b)

        return (
            0.2 * time_sim
            + 0.2 * key_sim
            + 0.2 * length_sim
            + 0.4 * pitch_sim
        )

    @staticmethod
    def _length_similarity(a: ScoreGraph, b: ScoreGraph) -> float:
        """Return a similarity in ``[0, 1]`` based on measure-count proximity."""
        na, nb = a.total_measures(), b.total_measures()
        if na == 0 and nb == 0:
            return 1.0
        if na == 0 or nb == 0:
            return 0.0
        return 1.0 - abs(na - nb) / max(na, nb)

    @staticmethod
    def _pitch_class_histogram(score: ScoreGraph) -> List[float]:
        """Return a 12-element pitch-class frequency histogram (normalised)."""
        counts = [0] * 12
        total = 0
        for note in score.all_notes():
            if note.is_rest or note.midi is None:
                continue
            counts[note.midi % 12] += 1
            total += 1
        if total == 0:
            return counts
        return [c / total for c in counts]

    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def _pitch_histogram_similarity(self, a: ScoreGraph, b: ScoreGraph) -> float:
        h1 = self._pitch_class_histogram(a)
        h2 = self._pitch_class_histogram(b)
        return self._cosine_similarity(h1, h2)
