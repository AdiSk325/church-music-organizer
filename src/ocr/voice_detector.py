"""Voice detector for church music scores.

Detects SATB, Piano+Voice, Organ, and other voice configurations
typical in church music. Assigns voice names, splits merged staffs,
and provides voice-level analysis.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from music21 import converter, stream, note, chord, clef, interval

logger = logging.getLogger(__name__)


@dataclass
class VoiceInfo:
    """Detected voice information."""
    voice_id: int = 0
    name: str = ""                    # e.g. "Soprano", "Alto", "Tenor", "Bass"
    clef_type: str = ""               # "treble", "bass", etc.
    range_low: Optional[str] = None   # e.g. "C4"
    range_high: Optional[str] = None  # e.g. "G5"
    note_count: int = 0
    is_vocal: bool = True
    part_index: int = 0               # Which part this voice belongs to


@dataclass
class VoiceDetectionResult:
    """Result of voice detection analysis."""
    score_type: str = "unknown"       # "SATB", "SAB", "Piano+Voice", "Organ", etc.
    voices: List[VoiceInfo] = field(default_factory=list)
    total_parts: int = 0
    has_accompaniment: bool = False
    has_lyrics: bool = False
    suggested_layout: str = ""        # e.g. "SA on treble staff, TB on bass staff"


class VoiceDetector:
    """Detect and classify voices in church music scores."""

    # Standard vocal ranges (MIDI)
    VOCAL_RANGES = {
        'Soprano': {'low': 60, 'high': 81, 'center': 69},   # C4 - A5
        'Alto':    {'low': 53, 'high': 74, 'center': 62},    # F3 - D5
        'Tenor':   {'low': 48, 'high': 69, 'center': 57},    # C3 - A4
        'Bass':    {'low': 40, 'high': 62, 'center': 50},     # E2 - D4
    }

    def detect(self, score_or_path) -> VoiceDetectionResult:
        """Detect voice configuration of a score.

        Args:
            score_or_path: music21 Score object or path to MusicXML

        Returns:
            VoiceDetectionResult with detected voices and score type
        """
        if isinstance(score_or_path, str):
            score = converter.parse(score_or_path)
        else:
            score = score_or_path

        result = VoiceDetectionResult()
        result.total_parts = len(score.parts)

        # Determine if lyrics exist
        result.has_lyrics = self._has_lyrics(score)

        # Analyze each part
        part_analyses = []
        for i, part in enumerate(score.parts):
            analysis = self._analyze_part(part, i)
            part_analyses.append(analysis)

        # Determine score type and assign voice names
        result.score_type, result.voices = self._classify_score(
            score, part_analyses
        )

        # Determine layout
        result.suggested_layout = self._suggest_layout(result)

        return result

    def _has_lyrics(self, score: stream.Score) -> bool:
        """Check if any part has lyrics attached."""
        for part in score.parts:
            for n in part.flatten().notes:
                if n.lyrics:
                    return True
        return False

    def _analyze_part(self, part: stream.Part, index: int) -> Dict:
        """Analyze a single part for voice detection."""
        notes = part.flatten().notes
        pitches = []
        for n in notes:
            if isinstance(n, note.Note):
                pitches.append(n.pitch.midi)
            elif isinstance(n, chord.Chord):
                for p in n.pitches:
                    pitches.append(p.midi)

        # Get clef
        clefs = part.flatten().getElementsByClass('Clef')
        clef_type = 'treble'
        if clefs:
            c = clefs[0]
            if isinstance(c, clef.BassClef):
                clef_type = 'bass'
            elif isinstance(c, clef.TrebleClef):
                clef_type = 'treble'
            elif isinstance(c, clef.AltoClef):
                clef_type = 'alto'

        # Count distinct voices within the part
        voice_ids = set()
        for n in notes:
            if hasattr(n, 'voice') and n.voice is not None:
                voice_ids.add(n.voice)

        # Check for chords (indicates multiple voices might be merged)
        chord_count = sum(1 for n in notes if isinstance(n, chord.Chord))

        # Has lyrics?
        has_lyrics = any(n.lyrics for n in notes)

        return {
            'index': index,
            'name': part.partName or part.id or f"Part {index + 1}",
            'clef': clef_type,
            'note_count': len(notes),
            'pitch_low': min(pitches) if pitches else 0,
            'pitch_high': max(pitches) if pitches else 0,
            'pitch_center': sum(pitches) / len(pitches) if pitches else 0,
            'voice_count': max(len(voice_ids), 1),
            'chord_count': chord_count,
            'has_lyrics': has_lyrics,
        }

    def _classify_score(self, score: stream.Score, analyses: List[Dict]):
        """Classify the score type and map voices."""
        n_parts = len(analyses)

        if n_parts == 0:
            return "empty", []

        # Filter out empty parts
        non_empty = [a for a in analyses if a['note_count'] > 0]
        if not non_empty:
            return "empty", []

        n_non_empty = len(non_empty)

        # --- Classic SATB on 2 staves ---
        if n_non_empty == 2:
            treble_parts = [a for a in non_empty if a['clef'] == 'treble']
            bass_parts = [a for a in non_empty if a['clef'] == 'bass']

            if len(treble_parts) == 1 and len(bass_parts) == 1:
                tp = treble_parts[0]
                bp = bass_parts[0]

                # Both staves have chords → likely SATB (SA on treble, TB on bass)
                if tp['chord_count'] > 5 and bp['chord_count'] > 5:
                    voices = self._make_satb_from_two_staves(tp, bp)
                    return "SATB (closed score)", voices

                # Treble with lyrics + bass chords → Voice + Accompaniment
                if tp['has_lyrics'] and not bp['has_lyrics']:
                    voices = [
                        VoiceInfo(voice_id=1, name="Voice",
                                  clef_type='treble',
                                  note_count=tp['note_count'],
                                  is_vocal=True, part_index=tp['index']),
                        VoiceInfo(voice_id=2, name="Accompaniment",
                                  clef_type='bass',
                                  note_count=bp['note_count'],
                                  is_vocal=False, part_index=bp['index']),
                    ]
                    return "Voice + Accompaniment", voices

                # Simple piano/organ
                voices = [
                    VoiceInfo(voice_id=1, name="Right Hand",
                              clef_type='treble',
                              note_count=tp['note_count'],
                              is_vocal=False, part_index=tp['index']),
                    VoiceInfo(voice_id=2, name="Left Hand",
                              clef_type='bass',
                              note_count=bp['note_count'],
                              is_vocal=False, part_index=bp['index']),
                ]
                return "Piano/Organ", voices

        # --- 4 separate parts (SATB open score) ---
        if n_non_empty == 4:
            sorted_by_pitch = sorted(non_empty, key=lambda a: -a['pitch_center'])
            names = ['Soprano', 'Alto', 'Tenor', 'Bass']
            voices = []
            for i, (analysis, name) in enumerate(zip(sorted_by_pitch, names)):
                voices.append(VoiceInfo(
                    voice_id=i + 1,
                    name=name,
                    clef_type=analysis['clef'],
                    note_count=analysis['note_count'],
                    is_vocal=True,
                    part_index=analysis['index'],
                    range_low=self._midi_to_note(analysis['pitch_low']),
                    range_high=self._midi_to_note(analysis['pitch_high']),
                ))
            return "SATB (open score)", voices

        # --- 3 parts (SAB or Voice+Piano) ---
        if n_non_empty == 3:
            treble = [a for a in non_empty if a['clef'] == 'treble']
            bass = [a for a in non_empty if a['clef'] == 'bass']

            # One melody + two-staff accompaniment
            if len(treble) == 2 and len(bass) == 1:
                vocal_part = max(treble, key=lambda a: 1 if a['has_lyrics'] else 0)
                accomp_treble = [a for a in treble if a != vocal_part][0]
                voices = [
                    VoiceInfo(voice_id=1, name="Voice",
                              clef_type='treble',
                              note_count=vocal_part['note_count'],
                              is_vocal=True, part_index=vocal_part['index']),
                    VoiceInfo(voice_id=2, name="Piano RH",
                              clef_type='treble',
                              note_count=accomp_treble['note_count'],
                              is_vocal=False, part_index=accomp_treble['index']),
                    VoiceInfo(voice_id=3, name="Piano LH",
                              clef_type='bass',
                              note_count=bass[0]['note_count'],
                              is_vocal=False, part_index=bass[0]['index']),
                ]
                return "Voice + Piano", voices

            # SAB (3 voices sorted by pitch)
            sorted_by_pitch = sorted(non_empty, key=lambda a: -a['pitch_center'])
            names = ['Soprano', 'Alto', 'Bass']
            voices = [
                VoiceInfo(
                    voice_id=i + 1, name=name,
                    clef_type=a['clef'],
                    note_count=a['note_count'],
                    is_vocal=True, part_index=a['index'],
                )
                for i, (a, name) in enumerate(zip(sorted_by_pitch, names))
            ]
            return "SAB", voices

        # --- 1 part (solo) ---
        if n_non_empty == 1:
            a = non_empty[0]
            voices = [VoiceInfo(
                voice_id=1,
                name="Solo" if a['has_lyrics'] else "Instrument",
                clef_type=a['clef'],
                note_count=a['note_count'],
                is_vocal=a['has_lyrics'],
                part_index=a['index'],
            )]
            return "Solo", voices

        # --- Generic / many parts ---
        voices = []
        for i, a in enumerate(non_empty):
            voices.append(VoiceInfo(
                voice_id=i + 1,
                name=a['name'],
                clef_type=a['clef'],
                note_count=a['note_count'],
                is_vocal=a['has_lyrics'],
                part_index=a['index'],
            ))
        return f"Ensemble ({n_non_empty} parts)", voices

    def _make_satb_from_two_staves(self, treble: Dict, bass: Dict) -> List[VoiceInfo]:
        """Create SATB voice list from two-staff closed score."""
        return [
            VoiceInfo(voice_id=1, name="Soprano", clef_type='treble',
                      note_count=treble['note_count'],
                      is_vocal=True, part_index=treble['index']),
            VoiceInfo(voice_id=2, name="Alto", clef_type='treble',
                      note_count=treble['note_count'],
                      is_vocal=True, part_index=treble['index']),
            VoiceInfo(voice_id=3, name="Tenor", clef_type='bass',
                      note_count=bass['note_count'],
                      is_vocal=True, part_index=bass['index']),
            VoiceInfo(voice_id=4, name="Bass", clef_type='bass',
                      note_count=bass['note_count'],
                      is_vocal=True, part_index=bass['index']),
        ]

    def _midi_to_note(self, midi_num: int) -> str:
        """Convert MIDI number to note name."""
        if midi_num <= 0:
            return "?"
        try:
            from music21 import pitch
            p = pitch.Pitch(midi=midi_num)
            return p.nameWithOctave
        except Exception:
            return "?"

    def _suggest_layout(self, result: VoiceDetectionResult) -> str:
        """Suggest the intended layout for the score."""
        if result.score_type.startswith("SATB (closed"):
            return "SA on treble staff, TB on bass staff (closed/short score)"
        elif result.score_type.startswith("SATB (open"):
            return "One staff per voice (S, A, T, B from top)"
        elif result.score_type == "Voice + Piano":
            return "Voice on top staff, piano grand staff below"
        elif result.score_type == "Voice + Accompaniment":
            return "Vocal melody on treble, accompaniment on bass"
        elif result.score_type == "Piano/Organ":
            return "Grand staff: treble + bass"
        elif result.score_type == "Solo":
            return "Single staff"
        else:
            return f"{result.total_parts}-staff system"

    def get_summary(self, result: VoiceDetectionResult) -> str:
        """Format detection result as readable text."""
        lines = [
            f"Voice Detection Report",
            f"{'=' * 50}",
            f"  Score Type:    {result.score_type}",
            f"  Total Parts:   {result.total_parts}",
            f"  Has Lyrics:    {'Yes' if result.has_lyrics else 'No'}",
            f"  Layout:        {result.suggested_layout}",
            f"\n  Voices Detected:",
        ]
        for v in result.voices:
            vocal = "vocal" if v.is_vocal else "instrument"
            range_str = ""
            if v.range_low and v.range_high:
                range_str = f" ({v.range_low} – {v.range_high})"
            lines.append(
                f"    {v.voice_id}. {v.name} [{v.clef_type}] "
                f"— {v.note_count} notes, {vocal}{range_str}"
            )
        return '\n'.join(lines)
