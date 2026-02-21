"""OMR module for church music organizer.

This module implements a compiler-style Optical Music Recognition (OMR)
pipeline based on constraint satisfaction and graph reconstruction:

    Image/MusicXML → ScoreGraph (IR) → Constraints → LLM Repair → MusicXML

Main components
---------------
- :class:`~src.omr.score_graph.ScoreGraph` – Intermediate Representation (IR)
- :class:`~src.omr.constraints.ConstraintEngine` – music-theory validation
- :class:`~src.omr.pipeline.OMRPipeline` – end-to-end compilation pipeline
- :class:`~src.omr.llm_repair.LLMRepairTool` – localised LLM-based repairs
- :class:`~src.omr.reference_matcher.ReferenceMatcher` – nearest-score retrieval
- :class:`~src.omr.benchmarking.OMRBenchmark` – semantic accuracy metrics
"""

from .benchmarking import BenchmarkResult, OMRBenchmark
from .constraints import ConstraintEngine, ConstraintViolation
from .llm_repair import LLMRepairTool
from .pipeline import OMRPipeline
from .reference_matcher import MatchResult, ReferenceMatcher
from .score_graph import (
    Measure,
    Note,
    ScoreGraph,
    Voice,
    VoiceType,
    VOICE_RANGES,
    pitch_to_midi,
)

__all__ = [
    # Score graph IR
    "ScoreGraph",
    "Measure",
    "Voice",
    "Note",
    "VoiceType",
    "VOICE_RANGES",
    "pitch_to_midi",
    # Constraint engine
    "ConstraintEngine",
    "ConstraintViolation",
    # Pipeline
    "OMRPipeline",
    # LLM repair
    "LLMRepairTool",
    # Reference matching
    "ReferenceMatcher",
    "MatchResult",
    # Benchmarking
    "OMRBenchmark",
    "BenchmarkResult",
]
