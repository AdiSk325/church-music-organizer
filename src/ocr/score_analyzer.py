"""Score analyzer — extract musical structure from MusicXML using music21.

Analyzes key signatures, time signatures, voices, instruments,
clefs, note ranges, and other musical properties.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from music21 import converter, stream, key, meter, clef, note, chord, instrument

logger = logging.getLogger(__name__)


@dataclass
class PartInfo:
    """Information about a single part/instrument in the score."""
    part_id: str = ""
    part_name: str = ""
    abbreviation: str = ""
    clef_type: str = ""
    instrument_name: str = ""
    voice_count: int = 1
    note_count: int = 0
    lowest_note: str = ""
    highest_note: str = ""
    measure_count: int = 0


@dataclass
class KeySigInfo:
    """Key signature information at a specific point in the score."""
    key_name: str = ""            # e.g., "A major"
    sharps_or_flats: int = 0      # positive = sharps, negative = flats
    measure_number: int = 1       # where this key starts
    mode: str = "major"           # major or minor


@dataclass
class TimeSigInfo:
    """Time signature information."""
    time_sig: str = ""            # e.g., "4/4"
    numerator: int = 4
    denominator: int = 4
    measure_number: int = 1


@dataclass
class ScoreMetadata:
    """Complete metadata extracted from a score."""
    # Identity
    title: str = ""
    composer: str = ""
    lyricist: str = ""

    # Structure
    parts: List[PartInfo] = field(default_factory=list)
    measures_count: int = 0
    key_signatures: List[KeySigInfo] = field(default_factory=list)
    time_signatures: List[TimeSigInfo] = field(default_factory=list)
    tempo_markings: List[str] = field(default_factory=list)

    # Musical content
    clefs: Dict[str, str] = field(default_factory=dict)
    voices_per_part: Dict[str, int] = field(default_factory=dict)
    note_range: Dict[str, Tuple[str, str]] = field(default_factory=dict)

    # Quality indicators
    total_notes: int = 0
    total_rests: int = 0
    incomplete_measures: List[int] = field(default_factory=list)
    empty_measures: List[int] = field(default_factory=list)

    # Detected score type
    score_type: str = ""          # e.g., "SATB", "Piano+Voice", "Solo"


class ScoreAnalyzer:
    """Analyze MusicXML scores to extract detailed musical structure."""

    # Voice ranges for classification (MIDI numbers)
    VOICE_RANGES = {
        'Soprano': (60, 84),   # C4 - C6
        'Alto': (53, 77),      # F3 - F5
        'Tenor': (48, 72),     # C3 - C5
        'Bass': (40, 64),      # E2 - E4
    }

    def analyze(self, musicxml_path: str) -> ScoreMetadata:
        """Parse MusicXML and extract complete musical structure.

        Args:
            musicxml_path: Path to MusicXML file

        Returns:
            ScoreMetadata with all extracted information
        """
        meta = ScoreMetadata()

        try:
            score = converter.parse(musicxml_path)
        except Exception as e:
            logger.error(f"Could not parse MusicXML: {e}")
            return meta

        # Extract metadata
        self._extract_identity(score, meta)
        self._extract_parts(score, meta)
        self._extract_key_signatures(score, meta)
        self._extract_time_signatures(score, meta)
        self._extract_tempo(score, meta)
        self._check_measure_completeness(score, meta)
        self._detect_score_type(meta)

        logger.info(
            f"Analyzed '{meta.title}': {len(meta.parts)} parts, "
            f"{meta.measures_count} measures, type={meta.score_type}"
        )
        return meta

    def analyze_from_score(self, score: stream.Score) -> ScoreMetadata:
        """Analyze a music21 Score object directly.

        Args:
            score: music21 Score object

        Returns:
            ScoreMetadata
        """
        meta = ScoreMetadata()
        self._extract_identity(score, meta)
        self._extract_parts(score, meta)
        self._extract_key_signatures(score, meta)
        self._extract_time_signatures(score, meta)
        self._extract_tempo(score, meta)
        self._check_measure_completeness(score, meta)
        self._detect_score_type(meta)
        return meta

    def _extract_identity(self, score: stream.Score, meta: ScoreMetadata):
        """Extract title, composer, lyricist."""
        if score.metadata:
            meta.title = score.metadata.title or ""
            meta.composer = score.metadata.composer or ""
            # music21 stores lyricist in contributors
            try:
                contributors = score.metadata.contributors
                for c in contributors:
                    if hasattr(c, 'role') and c.role == 'lyricist':
                        meta.lyricist = str(c)
            except Exception:
                pass

    def _extract_parts(self, score: stream.Score, meta: ScoreMetadata):
        """Extract part/instrument details."""
        for part in score.parts:
            info = PartInfo()
            info.part_id = part.id if part.id else ""
            info.part_name = part.partName if part.partName else ""
            info.abbreviation = part.partAbbreviation if part.partAbbreviation else ""

            # Clef
            clefs_found = part.flatten().getElementsByClass('Clef')
            if clefs_found:
                info.clef_type = type(clefs_found[0]).__name__
                meta.clefs[info.part_id] = info.clef_type

            # Instrument
            instruments = part.flatten().getElementsByClass('Instrument')
            if instruments:
                info.instrument_name = instruments[0].instrumentName or ""

            # Measures
            measures = part.getElementsByClass('Measure')
            info.measure_count = len(measures)
            meta.measures_count = max(meta.measures_count, info.measure_count)

            # Notes and range
            all_notes = part.flatten().notes
            info.note_count = len(all_notes)
            meta.total_notes += info.note_count

            pitches = []
            for n in all_notes:
                if isinstance(n, note.Note):
                    pitches.append(n.pitch)
                elif isinstance(n, chord.Chord):
                    pitches.extend(n.pitches)

            if pitches:
                sorted_pitches = sorted(pitches, key=lambda p: p.midi)
                info.lowest_note = str(sorted_pitches[0])
                info.highest_note = str(sorted_pitches[-1])
                meta.note_range[info.part_id] = (info.lowest_note, info.highest_note)

            # Voices
            voice_ids = set()
            for m in measures:
                for v in m.voices:
                    voice_ids.add(v.id)
            info.voice_count = max(len(voice_ids), 1)
            meta.voices_per_part[info.part_id] = info.voice_count

            # Count rests
            rests = part.flatten().getElementsByClass('Rest')
            meta.total_rests += len(rests)

            meta.parts.append(info)

    def _extract_key_signatures(self, score: stream.Score, meta: ScoreMetadata):
        """Extract all key signatures in the score."""
        all_keys = score.flatten().getElementsByClass('KeySignature')
        seen_offsets = set()

        for ks in all_keys:
            offset = ks.offset
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)

            info = KeySigInfo()
            info.sharps_or_flats = ks.sharps

            # Try to determine the key name
            if hasattr(ks, 'asKey') and callable(ks.asKey):
                try:
                    k = ks.asKey()
                    info.key_name = str(k)
                    info.mode = k.mode
                except Exception:
                    info.key_name = f"{ks.sharps} sharps" if ks.sharps >= 0 else f"{abs(ks.sharps)} flats"
            else:
                info.key_name = f"{ks.sharps} sharps" if ks.sharps >= 0 else f"{abs(ks.sharps)} flats"

            # Get measure number
            m = ks.getContextByClass('Measure')
            info.measure_number = m.number if m else 1

            meta.key_signatures.append(info)

        # If no key signatures found, try to analyze
        if not meta.key_signatures:
            try:
                analyzed_key = score.analyze('key')
                info = KeySigInfo()
                info.key_name = str(analyzed_key)
                info.mode = analyzed_key.mode
                info.sharps_or_flats = analyzed_key.sharps
                meta.key_signatures.append(info)
            except Exception:
                pass

    def _extract_time_signatures(self, score: stream.Score, meta: ScoreMetadata):
        """Extract all time signatures."""
        all_ts = score.flatten().getElementsByClass('TimeSignature')
        seen_offsets = set()

        for ts in all_ts:
            offset = ts.offset
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)

            info = TimeSigInfo()
            info.time_sig = ts.ratioString
            info.numerator = ts.numerator
            info.denominator = ts.denominator

            m = ts.getContextByClass('Measure')
            info.measure_number = m.number if m else 1

            meta.time_signatures.append(info)

    def _extract_tempo(self, score: stream.Score, meta: ScoreMetadata):
        """Extract tempo markings."""
        from music21 import tempo as m21_tempo, expressions

        # MetronomeMark
        for tm in score.flatten().getElementsByClass(m21_tempo.MetronomeMark):
            meta.tempo_markings.append(str(tm))

        # TextExpressions that might be tempo-related
        tempo_words = {
            'allegro', 'andante', 'adagio', 'moderato', 'presto',
            'lento', 'largo', 'vivace', 'poco', 'dolce',
            'maestoso', 'cantabile', 'espressivo',
        }
        for te in score.flatten().getElementsByClass(expressions.TextExpression):
            text = te.content.lower() if te.content else ""
            if any(tw in text for tw in tempo_words):
                meta.tempo_markings.append(te.content)

    def _check_measure_completeness(self, score: stream.Score, meta: ScoreMetadata):
        """Check each measure has the correct number of beats."""
        for part in score.parts:
            measures = part.getElementsByClass('Measure')
            current_ts = meter.TimeSignature('4/4')

            for m in measures:
                # Update time signature if present
                ts_list = m.getElementsByClass('TimeSignature')
                if ts_list:
                    current_ts = ts_list[0]

                # Check if measure has any notes/rests
                notes_and_rests = m.flatten().notesAndRests
                if len(notes_and_rests) == 0:
                    if m.number not in meta.empty_measures:
                        meta.empty_measures.append(m.number)
                    continue

                # Calculate actual duration in the measure
                actual_duration = sum(nr.quarterLength for nr in notes_and_rests)
                expected_duration = current_ts.barDuration.quarterLength

                # Allow small tolerance for floating point
                if abs(actual_duration - expected_duration) > 0.01:
                    if m.number not in meta.incomplete_measures:
                        meta.incomplete_measures.append(m.number)

    def _detect_score_type(self, meta: ScoreMetadata):
        """Classify the score arrangement type based on parts and clefs."""
        num_parts = len(meta.parts)
        clef_types = [p.clef_type for p in meta.parts]

        if num_parts == 0:
            meta.score_type = "Unknown"
            return

        if num_parts == 1:
            meta.score_type = "Solo"
            return

        if num_parts == 2:
            has_treble = any('Treble' in c for c in clef_types)
            has_bass = any('Bass' in c for c in clef_types)
            if has_treble and has_bass:
                # Could be piano or voice+bass
                total_voices = sum(p.voice_count for p in meta.parts)
                if total_voices >= 4:
                    meta.score_type = "SATB (Grand Staff)"
                else:
                    meta.score_type = "Piano (Grand Staff)"
            elif all('Treble' in c for c in clef_types):
                meta.score_type = "Duet (Treble)"
            else:
                meta.score_type = "Duet"
            return

        if num_parts == 3:
            meta.score_type = "Piano + Voice" if any('Bass' in c for c in clef_types) else "Trio"
            return

        if num_parts == 4:
            # Check if SATB by ranges
            is_satb = True
            voice_names = ['Soprano', 'Alto', 'Tenor', 'Bass']
            for i, part in enumerate(meta.parts):
                if i < len(voice_names):
                    expected_range = self.VOICE_RANGES.get(voice_names[i])
                    if expected_range and part.lowest_note and part.highest_note:
                        # Just a rough check
                        pass
            meta.score_type = "SATB" if is_satb else "Quartet"
            return

        meta.score_type = f"Ensemble ({num_parts} parts)"

    def get_summary(self, meta: ScoreMetadata) -> str:
        """Get a human-readable summary of the analysis.

        Args:
            meta: ScoreMetadata from analyze()

        Returns:
            Formatted summary string
        """
        lines = [
            f"Score Analysis: {meta.title or 'Untitled'}",
            f"{'=' * 50}",
            f"  Composer:     {meta.composer or 'Unknown'}",
            f"  Score Type:   {meta.score_type}",
            f"  Parts:        {len(meta.parts)}",
            f"  Measures:     {meta.measures_count}",
            f"  Total Notes:  {meta.total_notes}",
            f"  Total Rests:  {meta.total_rests}",
        ]

        if meta.key_signatures:
            keys_str = ', '.join(ks.key_name for ks in meta.key_signatures)
            lines.append(f"  Key(s):       {keys_str}")

        if meta.time_signatures:
            ts_str = ', '.join(ts.time_sig for ts in meta.time_signatures)
            lines.append(f"  Time Sig(s):  {ts_str}")

        if meta.tempo_markings:
            lines.append(f"  Tempo:        {', '.join(meta.tempo_markings)}")

        lines.append(f"\n  Parts Detail:")
        for i, part in enumerate(meta.parts, 1):
            name = part.part_name or f"Part {i}"
            lines.append(
                f"    {i}. {name}: {part.clef_type}, "
                f"range {part.lowest_note}-{part.highest_note}, "
                f"{part.note_count} notes, {part.voice_count} voice(s)"
            )

        if meta.incomplete_measures:
            lines.append(f"\n  ⚠ Incomplete measures: {meta.incomplete_measures[:10]}")
        if meta.empty_measures:
            lines.append(f"  ⚠ Empty measures: {meta.empty_measures[:10]}")

        return '\n'.join(lines)
