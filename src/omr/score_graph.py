"""ScoreGraph: Intermediate Representation (IR) for music scores.

This module defines the core data structures used as the AST (Abstract Syntax
Tree) of a music score.  The ScoreGraph is the central data structure in the
OMR pipeline:

    Image → Symbols → ScoreGraph → Constraints → MusicXML

By working through a well-defined IR we can decouple symbol extraction (noisy,
probabilistic) from semantic reconstruction (rule-based, deterministic) and
export (format-specific).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Voice types
# ---------------------------------------------------------------------------

class VoiceType(Enum):
    """SATB voice designations plus an unassigned placeholder."""

    SOPRANO = "soprano"
    ALTO = "alto"
    TENOR = "tenor"
    BASS = "bass"
    UNASSIGNED = "unassigned"


# Typical MIDI pitch ranges per SATB voice.
# Each entry: (min_midi, max_midi) inclusive.
VOICE_RANGES: Dict[VoiceType, tuple] = {
    VoiceType.SOPRANO: (60, 79),   # C4 – G5
    VoiceType.ALTO:    (55, 72),   # G3 – C5
    VoiceType.TENOR:   (48, 67),   # C3 – G4
    VoiceType.BASS:    (40, 60),   # E2 – C4
}


# ---------------------------------------------------------------------------
# Pitch utilities
# ---------------------------------------------------------------------------

_PITCH_CLASS_MAP = {
    "C": 0, "D": 2, "E": 4, "F": 5,
    "G": 7, "A": 9, "B": 11,
}

_ACCIDENTAL_MAP = {"#": 1, "b": -1, "": 0}


def pitch_to_midi(pitch: str) -> Optional[int]:
    """Convert a pitch string such as ``'C4'`` or ``'D#5'`` to a MIDI number.

    Returns ``None`` for rests (any string starting with ``'R'`` or ``'r'``).
    """
    if not pitch or pitch[0].upper() == "R":
        return None

    note_name = pitch[0].upper()
    if note_name not in _PITCH_CLASS_MAP:
        return None

    remainder = pitch[1:]
    accidental = ""
    if remainder and remainder[0] in ("#", "b"):
        accidental = remainder[0]
        remainder = remainder[1:]

    try:
        octave = int(remainder)
    except ValueError:
        return None

    midi = 12 * (octave + 1) + _PITCH_CLASS_MAP[note_name] + _ACCIDENTAL_MAP[accidental]
    return midi


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass
class Note:
    """A single note or rest in the score.

    Attributes:
        pitch:    Pitch string, e.g. ``'C4'``, ``'D#5'``, or ``'R'`` for rest.
        duration: Duration in quarter-note units (1.0 = quarter, 0.5 = eighth).
        onset:    Beat position within the measure (0-indexed quarter-note units).
        voice_id: Identifier of the voice this note belongs to (``None`` = unassigned).
    """

    pitch: str
    duration: float
    onset: float
    voice_id: Optional[int] = None

    @property
    def is_rest(self) -> bool:
        """Return ``True`` if this note represents a rest."""
        return not self.pitch or self.pitch[0].upper() == "R"

    @property
    def midi(self) -> Optional[int]:
        """MIDI pitch number, or ``None`` for rests."""
        return pitch_to_midi(self.pitch)


@dataclass
class Voice:
    """A single voice (part of a polyphonic texture) within a measure.

    Attributes:
        voice_id:   Numeric identifier.
        voice_type: SATB designation or ``VoiceType.UNASSIGNED``.
        notes:      Ordered list of notes in this voice.
    """

    voice_id: int
    voice_type: VoiceType = VoiceType.UNASSIGNED
    notes: List[Note] = field(default_factory=list)

    def total_duration(self) -> float:
        """Sum of all note durations in this voice."""
        return sum(n.duration for n in self.notes)


@dataclass
class Measure:
    """A single measure (bar) in the score.

    Attributes:
        number:         1-indexed measure number.
        time_signature: Time signature string, e.g. ``'4/4'``.
        voices:         List of voices contained in this measure.
    """

    number: int
    time_signature: str = "4/4"
    voices: List[Voice] = field(default_factory=list)

    def expected_duration(self) -> float:
        """Expected total duration (in quarter notes) derived from time signature."""
        try:
            numerator, denominator = self.time_signature.split("/")
            return int(numerator) * (4.0 / int(denominator))
        except (ValueError, ZeroDivisionError):
            return 4.0

    def all_notes(self) -> List[Note]:
        """Flat list of all notes across all voices in this measure."""
        return [note for voice in self.voices for note in voice.notes]


@dataclass
class ScoreGraph:
    """Top-level Intermediate Representation of a music score.

    This is the "AST" used throughout the OMR pipeline.  All stages –
    symbol extraction, constraint solving, LLM repair, reference matching,
    and export – operate on ``ScoreGraph`` objects.

    Attributes:
        title:          Human-readable title of the piece.
        composer:       Composer name.
        key_signature:  Key signature string, e.g. ``'C'``, ``'G'``, ``'Bb'``.
        time_signature: Global time signature; individual measures may override.
        measures:       Ordered list of measures.
        metadata:       Arbitrary key/value metadata (e.g. tempo, language).
    """

    title: str = ""
    composer: str = ""
    key_signature: str = "C"
    time_signature: str = "4/4"
    measures: List[Measure] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)

    def total_measures(self) -> int:
        """Number of measures in the score."""
        return len(self.measures)

    def all_notes(self) -> List[Note]:
        """Flat list of all notes across the entire score."""
        return [note for measure in self.measures for note in measure.all_notes()]

    def voice_ids(self) -> List[int]:
        """Sorted list of unique voice IDs present in the score."""
        ids = {
            voice.voice_id
            for measure in self.measures
            for voice in measure.voices
        }
        return sorted(ids)
