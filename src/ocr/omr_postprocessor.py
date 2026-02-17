"""OMR Post-Processor — correct common homr errors after per-staff OMR.

Applies a series of corrections to raw homr MusicXML output before
the ScoreBuilder assembles the final multi-part score:

1. Voice separation — split chords into separate voices (stem up/down)
2. Phantom note removal — remove spurious whole notes / long rests
3. Time signature normalization — prefer 4/4 over 2/4, majority voting
4. Key signature consistency — enforce same key across staves in a system
5. Beat count normalization — truncate/pad to expected beats per measure
"""

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from music21 import (
    chord, clef, converter, key, meter, note,
    stream, duration as m21duration
)

logger = logging.getLogger(__name__)


# Standard time signatures ranked by commonality in church music
_TIME_SIG_PREFERENCE = {
    (4, 4): 10,
    (3, 4): 9,
    (2, 4): 3,
    (6, 8): 7,
    (2, 2): 4,
    (3, 8): 5,
    (4, 2): 2,
}

# Pitch midpoints for staff assignment (MIDI note numbers)
_TREBLE_MIDPOINT = 67  # G4 — midpoint of treble clef
_BASS_MIDPOINT = 50    # D3 — midpoint of bass clef


@dataclass
class PostProcessingReport:
    """Report of changes made during post-processing."""
    chords_split: int = 0
    phantom_notes_removed: int = 0
    phantom_rests_removed: int = 0
    time_sig_corrected: bool = False
    key_sig_corrected: bool = False
    beats_normalized: int = 0  # measures where beats were fixed
    original_time_sig: Optional[str] = None
    corrected_time_sig: Optional[str] = None
    original_key_sig: Optional[str] = None
    corrected_key_sig: Optional[str] = None
    voices_created: int = 0


class OMRPostProcessor:
    """Post-process raw homr OMR output to fix common errors."""

    def process(
        self,
        musicxml_path: str,
        expected_time_sig: Optional[Tuple[int, int]] = None,
        expected_key_fifths: Optional[int] = None,
        clef_type: str = "G",
        peer_time_sigs: Optional[List[Tuple[int, int]]] = None,
        peer_key_fifths: Optional[List[int]] = None,
    ) -> Tuple[str, PostProcessingReport]:
        """Post-process a raw OMR MusicXML file.

        Args:
            musicxml_path: Path to raw homr-produced MusicXML
            expected_time_sig: Expected (beats, beat_type) if known
            expected_key_fifths: Expected key as fifths (-1=F, 0=C, +1=G)
            clef_type: "G" or "F" — affects voice separation pitch threshold
            peer_time_sigs: Time signatures from peer staves (for voting)
            peer_key_fifths: Key signatures from peer staves (for consistency)

        Returns:
            Tuple of (output_path, report)
        """
        report = PostProcessingReport()

        try:
            score = converter.parse(musicxml_path)
        except Exception as e:
            logger.error(f"Failed to parse {musicxml_path}: {e}")
            return musicxml_path, report

        if not score.parts:
            return musicxml_path, report

        part = score.parts[0]

        # Step 1: Fix time signature
        corrected_ts = self._fix_time_signature(
            part, expected_time_sig, peer_time_sigs
        )
        if corrected_ts:
            report.time_sig_corrected = True
            report.corrected_time_sig = f"{corrected_ts[0]}/{corrected_ts[1]}"

        # Step 2: Fix key signature
        corrected_ks = self._fix_key_signature(
            part, expected_key_fifths, peer_key_fifths
        )
        if corrected_ks is not None:
            report.key_sig_corrected = True
            report.corrected_key_sig = str(corrected_ks)

        # Step 3: Get expected beats per measure
        ts = part.flatten().getElementsByClass("TimeSignature")
        if ts:
            expected_beats = ts[0].barDuration.quarterLength
        elif corrected_ts:
            expected_beats = corrected_ts[0] * (4.0 / corrected_ts[1])
        else:
            expected_beats = 4.0

        # Step 4: Process each measure
        measures = list(part.getElementsByClass("Measure"))
        midpoint = _TREBLE_MIDPOINT if clef_type == "G" else _BASS_MIDPOINT

        for m in measures:
            # 4a: Remove phantom rests
            removed = self._remove_phantom_rests(m, expected_beats)
            report.phantom_rests_removed += removed

            # 4b: Remove phantom whole notes
            removed = self._remove_phantom_notes(m, expected_beats)
            report.phantom_notes_removed += removed

            # 4c: Voice separation (chord splitting)
            voices_added = self._separate_voices(m, midpoint, expected_beats)
            if voices_added:
                report.chords_split += voices_added
                report.voices_created += 1

            # 4d: Normalize beat count
            normalized = self._normalize_beats(m, expected_beats)
            if normalized:
                report.beats_normalized += 1

        # Save corrected output
        output_path = musicxml_path  # overwrite in place
        try:
            score.write("musicxml", fp=output_path)
        except Exception as e:
            logger.warning(f"Failed to write corrected MusicXML: {e}")

        logger.info(
            f"PostProcessor: split {report.chords_split} chords, "
            f"removed {report.phantom_notes_removed} phantom notes, "
            f"removed {report.phantom_rests_removed} phantom rests, "
            f"normalized {report.beats_normalized} measures"
        )
        return output_path, report

    # ------------------------------------------------------------------
    # Time signature correction
    # ------------------------------------------------------------------

    def _fix_time_signature(
        self,
        part: stream.Part,
        expected: Optional[Tuple[int, int]],
        peers: Optional[List[Tuple[int, int]]],
    ) -> Optional[Tuple[int, int]]:
        """Fix time signature using expected value or peer voting.

        homr commonly misdetects:
        - 2/4 instead of 4/4
        - 2/2 instead of 4/4
        - 3/4 instead of 4/4 (or vice versa)

        Strategy:
        1. If expected is provided and differs from detected, use expected
        2. If peers are provided, use majority vote (weighted by preference)
        3. If detected is 2/4 and measure note durations suggest 4/4, upgrade
        """
        time_sigs = list(part.flatten().getElementsByClass("TimeSignature"))
        if not time_sigs:
            # No time sig detected — infer from expected or default
            if expected:
                ts = meter.TimeSignature(f"{expected[0]}/{expected[1]}")
                measures = list(part.getElementsByClass("Measure"))
                if measures:
                    measures[0].insert(0, ts)
                return expected
            return None

        current = time_sigs[0]
        current_tuple = (current.numerator, current.denominator)

        # Check if current is likely wrong
        target = None

        if expected and current_tuple != expected:
            target = expected
        elif peers:
            # Majority vote
            vote_counts: Dict[Tuple[int, int], int] = {}
            all_ts = [current_tuple] + peers
            for ts_tuple in all_ts:
                pref = _TIME_SIG_PREFERENCE.get(ts_tuple, 1)
                vote_counts[ts_tuple] = vote_counts.get(ts_tuple, 0) + pref
            winner = max(vote_counts, key=vote_counts.get)
            if winner != current_tuple:
                target = winner
        else:
            # Heuristic: 2/4 → 4/4 upgrade if measure content suggests it
            if current_tuple == (2, 4):
                measures = list(part.getElementsByClass("Measure"))
                if measures:
                    avg_content = self._avg_measure_content(measures)
                    if avg_content > 3.0:
                        target = (4, 4)
            elif current_tuple == (2, 2):
                target = (4, 4)

        if target:
            logger.info(
                f"Correcting time sig: {current_tuple} → {target}"
            )
            # Replace the time signature
            new_ts = meter.TimeSignature(f"{target[0]}/{target[1]}")
            measures = list(part.getElementsByClass("Measure"))
            if measures:
                for el in list(measures[0]):
                    if isinstance(el, meter.TimeSignature):
                        measures[0].remove(el)
                measures[0].insert(0, new_ts)
            return target

        return None

    def _avg_measure_content(self, measures: list) -> float:
        """Average total note duration per measure."""
        total = 0.0
        count = 0
        for m in measures:
            notes = list(m.flatten().notesAndRests)
            dur = sum(n.quarterLength for n in notes)
            total += dur
            count += 1
        return total / count if count > 0 else 0.0

    # ------------------------------------------------------------------
    # Key signature correction
    # ------------------------------------------------------------------

    def _fix_key_signature(
        self,
        part: stream.Part,
        expected_fifths: Optional[int],
        peer_fifths: Optional[List[int]],
    ) -> Optional[int]:
        """Fix key signature using expected value or peer consensus.

        homr sometimes detects wrong key on bass clef (e.g., +2 sharps
        instead of -1 flat in Boże mój).
        """
        key_sigs = list(part.flatten().getElementsByClass("KeySignature"))
        if not key_sigs:
            if expected_fifths is not None:
                ks = key.KeySignature(expected_fifths)
                measures = list(part.getElementsByClass("Measure"))
                if measures:
                    measures[0].insert(0, ks)
                return expected_fifths
            return None

        current = key_sigs[0]
        current_fifths = current.sharps

        target = None

        if expected_fifths is not None and current_fifths != expected_fifths:
            target = expected_fifths
        elif peer_fifths:
            # Majority vote
            from collections import Counter
            all_fifths = [current_fifths] + peer_fifths
            most_common = Counter(all_fifths).most_common(1)[0][0]
            if most_common != current_fifths:
                target = most_common

        if target is not None:
            logger.info(
                f"Correcting key sig: {current_fifths} fifths → {target} fifths"
            )
            new_ks = key.KeySignature(target)
            measures = list(part.getElementsByClass("Measure"))
            if measures:
                for el in list(measures[0]):
                    if isinstance(el, key.KeySignature):
                        measures[0].remove(el)
                measures[0].insert(0, new_ks)

            # Transpose notes to match new key if the shift is from wrong key detection
            # (e.g., homr detected +2 sharps, should be -1 flat: need to flatten F# → F, C# → C)
            self._retranspone_for_key_change(part, current_fifths, target)
            return target

        return None

    def _retranspone_for_key_change(
        self, part: stream.Part, old_fifths: int, new_fifths: int
    ):
        """Fix accidentals when key signature was wrong.

        If homr detected +2 sharps but correct key is -1 flat:
        - F# notes should be F (remove sharp)
        - C# notes should be C (remove sharp)
        This isn't a transposition — it's an accidental correction.
        """
        # Notes that should change:
        # Old sharps that aren't in the new key → remove sharp
        # New flats that weren't in old key → add flat

        # Sharps order: F C G D A E B
        sharp_order = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
        # Flats order: B E A D G C F
        flat_order = ['B', 'E', 'A', 'D', 'G', 'C', 'F']

        # Determine which notes need correction
        old_altered = set()
        new_altered = set()

        if old_fifths > 0:
            for i in range(min(old_fifths, 7)):
                old_altered.add((sharp_order[i], 1))  # (step, alter)
        elif old_fifths < 0:
            for i in range(min(-old_fifths, 7)):
                old_altered.add((flat_order[i], -1))

        if new_fifths > 0:
            for i in range(min(new_fifths, 7)):
                new_altered.add((sharp_order[i], 1))
        elif new_fifths < 0:
            for i in range(min(-new_fifths, 7)):
                new_altered.add((flat_order[i], -1))

        # Notes to fix: in old key but not in new key
        to_fix = old_altered - new_altered

        if not to_fix:
            return

        for n in part.flatten().notes:
            pitches = n.pitches if hasattr(n, 'pitches') else [n.pitch]
            for p in pitches:
                for fix_step, fix_alter in to_fix:
                    if p.step == fix_step:
                        if p.accidental and p.accidental.alter == fix_alter:
                            # Remove the accidental (it was from wrong key)
                            p.accidental = None
                        elif not p.accidental:
                            # Note has no accidental but was written in
                            # wrong key context — might need counter-accidental
                            pass

        # Now add accidentals for new key that weren't in old key
        new_only = new_altered - old_altered
        for n in part.flatten().notes:
            pitches = n.pitches if hasattr(n, 'pitches') else [n.pitch]
            for p in pitches:
                for fix_step, fix_alter in new_only:
                    if p.step == fix_step and not p.accidental:
                        from music21.pitch import Accidental
                        p.accidental = Accidental(fix_alter)

    # ------------------------------------------------------------------
    # Phantom note removal
    # ------------------------------------------------------------------

    def _remove_phantom_notes(
        self, measure: stream.Measure, expected_beats: float
    ) -> int:
        """Remove phantom whole notes that cause beat overflow.

        homr sometimes inserts 4.0q whole notes where tied notes or
        recto tono passages should be. These cause massive beat overflow.

        Detection heuristic:
        - A note with duration 4.0q in a 3/4 or 4/4 measure
        - Where removing it brings beat count closer to expected
        - Especially if surrounded by shorter notes
        """
        all_notes = list(measure.flatten().notesAndRests)
        if not all_notes:
            return 0

        total_beats = sum(n.quarterLength for n in all_notes)
        if total_beats <= expected_beats * 1.2:
            # Not overfull — no need to remove
            return 0

        removed = 0
        # Find candidate phantom notes (very long relative to expected)
        for n in list(measure.flatten().notes):
            if n.quarterLength >= expected_beats and total_beats > expected_beats * 1.3:
                # This note is as long as the entire measure — likely phantom
                # Check if removing it brings us closer to expected
                new_total = total_beats - n.quarterLength
                if abs(new_total - expected_beats) < abs(total_beats - expected_beats):
                    measure.remove(n)
                    total_beats = new_total
                    removed += 1
                    logger.debug(
                        f"Removed phantom note: {n} "
                        f"(dur={n.quarterLength}, beats was {total_beats + n.quarterLength})"
                    )

        # Second pass: look for very long rests that might be phantom
        for r in list(measure.flatten().getElementsByClass("Rest")):
            if r.quarterLength >= expected_beats and total_beats > expected_beats * 1.3:
                new_total = total_beats - r.quarterLength
                if abs(new_total - expected_beats) < abs(total_beats - expected_beats):
                    measure.remove(r)
                    total_beats = new_total
                    removed += 1

        return removed

    def _remove_phantom_rests(
        self, measure: stream.Measure, expected_beats: float
    ) -> int:
        """Remove phantom rests that coexist with notes.

        homr inserts whole rests and half rests as artifacts.
        If a rest exists in a measure that already has notes filling
        the beats, the rest is likely phantom.
        """
        notes = list(measure.flatten().notes)
        rests = list(measure.flatten().getElementsByClass("Rest"))

        if not notes or not rests:
            return 0

        note_beats = sum(n.quarterLength for n in notes)
        rest_beats = sum(r.quarterLength for r in rests)
        total = note_beats + rest_beats

        if total <= expected_beats * 1.1:
            return 0

        removed = 0
        # Remove rests that cause overflow, starting with the largest
        rests_sorted = sorted(rests, key=lambda r: -r.quarterLength)
        for r in rests_sorted:
            if note_beats >= expected_beats * 0.8:
                # Notes alone fill most of the measure — rest is phantom
                measure.remove(r)
                removed += 1
                total -= r.quarterLength
            elif total > expected_beats * 1.2:
                measure.remove(r)
                removed += 1
                total -= r.quarterLength

            if total <= expected_beats * 1.1:
                break

        return removed

    # ------------------------------------------------------------------
    # Voice separation
    # ------------------------------------------------------------------

    def _separate_voices(
        self,
        measure: stream.Measure,
        pitch_midpoint: int,
        expected_beats: float,
    ) -> int:
        """Separate mixed voices in a measure.

        Strategy:
        1. Find all chords — split top pitch to voice 1, bottom to voice 2
        2. For non-chord notes, assign by pitch relative to midpoint
        3. Create proper music21 Voice objects if 2+ voices needed

        Returns number of chords split.
        """
        all_notes = list(measure.flatten().notes)
        if not all_notes:
            return 0

        # Check if there are chords to split
        chords_found = [n for n in all_notes if isinstance(n, chord.Chord)]
        if not chords_found:
            # No chords — check if beat overflow suggests mixed voices
            total_beats = sum(n.quarterLength for n in all_notes)
            if total_beats <= expected_beats * 1.4:
                return 0
            # Try pitch-based separation even without chords
            return self._pitch_based_separation(
                measure, all_notes, pitch_midpoint, expected_beats
            )

        # Split chords and assign to voices
        voice1_notes = []  # (offset, duration, pitch_or_rest)
        voice2_notes = []
        split_count = 0

        for elem in measure.flatten().notesAndRests:
            offset = float(elem.offset)
            dur = float(elem.quarterLength)

            if isinstance(elem, chord.Chord) and len(elem.pitches) >= 2:
                # Split chord: highest pitch → voice 1, lowest → voice 2
                sorted_pitches = sorted(elem.pitches, key=lambda p: p.midi, reverse=True)
                top_pitch = sorted_pitches[0]
                bottom_pitch = sorted_pitches[-1]

                voice1_notes.append((offset, dur, top_pitch))
                voice2_notes.append((offset, dur, bottom_pitch))

                # If chord has 3+ pitches, distribute remaining
                for p in sorted_pitches[1:-1]:
                    if p.midi >= pitch_midpoint:
                        voice1_notes.append((offset, dur, p))
                    else:
                        voice2_notes.append((offset, dur, p))

                split_count += 1

            elif isinstance(elem, note.Note):
                if elem.pitch.midi >= pitch_midpoint:
                    voice1_notes.append((offset, dur, elem.pitch))
                else:
                    voice2_notes.append((offset, dur, elem.pitch))

            elif isinstance(elem, note.Rest):
                # Don't duplicate rests — let them belong to voice 1
                voice1_notes.append((offset, dur, "rest"))

        if split_count == 0 or not voice2_notes:
            return 0

        # Reconstruct measure with 2 voices
        self._write_voices_to_measure(
            measure, voice1_notes, voice2_notes
        )

        return split_count

    def _pitch_based_separation(
        self,
        measure: stream.Measure,
        notes: list,
        pitch_midpoint: int,
        expected_beats: float,
    ) -> int:
        """Separate notes into voiced based purely on pitch.

        Used when there are no chords but beat count suggests mixed voices.
        """
        voice1_notes = []
        voice2_notes = []

        for elem in measure.flatten().notesAndRests:
            offset = float(elem.offset)
            dur = float(elem.quarterLength)

            if isinstance(elem, note.Note):
                if elem.pitch.midi >= pitch_midpoint:
                    voice1_notes.append((offset, dur, elem.pitch))
                else:
                    voice2_notes.append((offset, dur, elem.pitch))
            elif isinstance(elem, note.Rest):
                voice1_notes.append((offset, dur, "rest"))

        if not voice1_notes or not voice2_notes:
            return 0

        # Check if separation improves beat count
        v1_beats = sum(dur for _, dur, _ in voice1_notes if _ != "rest")
        v2_beats = sum(dur for _, dur, _ in voice2_notes)

        # If both voices have reasonable beat counts, proceed
        if (v1_beats <= expected_beats * 1.3 and
                v2_beats <= expected_beats * 1.3):
            self._write_voices_to_measure(
                measure, voice1_notes, voice2_notes
            )
            return len(voice2_notes)

        return 0

    def _write_voices_to_measure(
        self,
        measure: stream.Measure,
        voice1_notes: List[Tuple],
        voice2_notes: List[Tuple],
    ):
        """Replace measure content with 2 proper voices.

        Args:
            measure: The measure to modify
            voice1_notes: List of (offset, duration, pitch_or_rest)
            voice2_notes: List of (offset, duration, pitch_or_rest)
        """
        # Preserve non-note elements (clefs, key sigs, time sigs, barlines)
        preserved = []
        for elem in list(measure):
            if isinstance(elem, (clef.Clef, key.KeySignature,
                                 meter.TimeSignature)):
                preserved.append((float(elem.offset), elem))

        # Clear the measure
        measure.clear()

        # Re-add preserved elements
        for offset, elem in preserved:
            measure.insert(offset, elem)

        # Create voice 1
        v1 = stream.Voice(id='1')
        for offset, dur, pitch_data in sorted(voice1_notes, key=lambda x: x[0]):
            if pitch_data == "rest":
                r = note.Rest(quarterLength=dur)
                v1.insert(offset, r)
            else:
                n = note.Note(pitch_data, quarterLength=dur)
                v1.insert(offset, n)

        # Create voice 2
        v2 = stream.Voice(id='2')
        for offset, dur, pitch_data in sorted(voice2_notes, key=lambda x: x[0]):
            if pitch_data == "rest":
                r = note.Rest(quarterLength=dur)
                v2.insert(offset, r)
            else:
                n = note.Note(pitch_data, quarterLength=dur)
                v2.insert(offset, n)

        measure.insert(0, v1)
        measure.insert(0, v2)

    # ------------------------------------------------------------------
    # Beat count normalization
    # ------------------------------------------------------------------

    def _normalize_beats(
        self, measure: stream.Measure, expected_beats: float
    ) -> bool:
        """Normalize beat count in a measure.

        If the measure is still overfull after phantom removal and voice
        separation, try to truncate excess notes. If underfull, add rests.
        """
        all_elements = list(measure.flatten().notesAndRests)
        if not all_elements:
            return False

        total_beats = sum(e.quarterLength for e in all_elements)

        if abs(total_beats - expected_beats) < 0.1:
            return False  # Already correct

        if total_beats > expected_beats * 1.5:
            # Still massively overfull — try removing last notes
            # Sort by offset (descending), remove from end
            notes_by_offset = sorted(
                [(float(n.offset), n) for n in all_elements],
                key=lambda x: -x[0]
            )
            current = total_beats
            for off, n in notes_by_offset:
                if current <= expected_beats * 1.1:
                    break
                if off >= expected_beats:
                    # This note starts after the expected measure end
                    try:
                        measure.remove(n)
                        current -= n.quarterLength
                    except Exception:
                        pass

            return current != total_beats

        return False


def collect_peer_metadata(
    staff_results: List[dict],
) -> Dict[str, List]:
    """Collect time/key signature info from all staves for cross-voting.

    Args:
        staff_results: List of {"path": str, "staff_indices": [int], ...}

    Returns:
        Dict with "time_sigs" and "key_fifths" lists
    """
    time_sigs = []
    key_fifths = []

    for sr in staff_results:
        path = sr.get("path", "")
        if not path or not Path(path).exists():
            continue
        try:
            score = converter.parse(path)
            if score.parts:
                part = score.parts[0]
                ts = list(part.flatten().getElementsByClass("TimeSignature"))
                ks = list(part.flatten().getElementsByClass("KeySignature"))
                if ts:
                    time_sigs.append((ts[0].numerator, ts[0].denominator))
                if ks:
                    key_fifths.append(ks[0].sharps)
        except Exception:
            pass

    return {
        "time_sigs": time_sigs,
        "key_fifths": key_fifths,
    }
