"""Data classes representing the result of a score analysis."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VoiceRange:
    name: str
    lowest_pitch: str  # scientific notation, e.g. "C4"
    highest_pitch: str
    range_semitones: int
    tessitura_center: str  # approximate center pitch


@dataclass
class ScoreDescriptor:
    # --- Metadata ---
    title: Optional[str] = None
    composer: Optional[str] = None
    lyricist: Optional[str] = None
    source_file: Optional[str] = None

    # --- Basic structure ---
    voice_count: int = 0
    voice_names: List[str] = field(default_factory=list)
    measure_count: int = 0
    time_signatures: List[str] = field(default_factory=list)
    tempo_marking: Optional[str] = None
    has_pickup_measure: bool = False
    total_duration_beats: float = 0.0

    # --- Key and harmony ---
    detected_key: Optional[str] = None
    key_confidence: float = 0.0
    mode: Optional[str] = None  # "major" | "minor" | "modal" | "chromatic"
    modulations: List[str] = field(default_factory=list)
    harmony_epoch: Optional[str] = (
        None  # "medieval" | "renaissance" | "baroque" | "classical" | "romantic" | "contemporary"
    )
    chromatic_complexity: float = 0.0  # 0.0–1.0
    harmonic_rhythm: Optional[str] = None  # "slow" | "moderate" | "fast"
    chord_vocabulary: List[str] = field(default_factory=list)

    # --- Texture ---
    texture_type: Optional[str] = (
        None  # "monophonic" | "homophonic_chorale" | "homophonic_melody" | "polyphonic_imitative" | "polyphonic_free"
    )
    rhythmic_variance: float = 0.0
    onset_simultaneity: float = 0.0  # 0.0–1.0 (1.0 = all voices always together)
    voice_independence: float = 0.0  # 0.0 (homorhythmic) – 1.0 (fully independent)

    # --- Form ---
    form_type: Optional[str] = (
        None  # "strophic" | "through_composed" | "binary" | "ternary" | "canon" | "fugue" | etc.
    )
    has_repetition: bool = False
    section_count: int = 1
    has_imitation: bool = False
    is_canon: bool = False
    canon_interval: Optional[str] = None

    # --- Voice ranges ---
    voice_ranges: List[VoiceRange] = field(default_factory=list)
    parallel_fifths_count: int = 0
    parallel_octaves_count: int = 0
    voice_crossings_count: int = 0
    contrary_motion_ratio: float = 0.0

    # --- Lyrics ---
    has_lyrics: bool = False
    lyrics_language: Optional[str] = None  # ISO 639-1: "la", "pl", "de", "en", etc.
    language_confidence: float = 0.0
    text_setting_type: Optional[str] = None  # "syllabic" | "neumatic" | "melismatic"
    notes_per_syllable_avg: float = 0.0
    has_word_painting: Optional[bool] = None

    # --- Difficulty ---
    estimated_grade: int = 0  # 1–6 NYSSMA-style
    grade_label: Optional[str] = None  # "elementary" | "intermediate" | "advanced"
    difficulty_factors: List[str] = field(default_factory=list)

    # --- Human-readable summary ---
    narrative_description: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a plain dict for JSON serialisation / DB storage."""
        result = {}
        for f_name in self.__dataclass_fields__:
            value = getattr(self, f_name)
            if isinstance(value, list):
                result[f_name] = [v.__dict__ if isinstance(v, VoiceRange) else v for v in value]
            else:
                result[f_name] = value
        return result
