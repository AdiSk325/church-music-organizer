"""Pitch Corrector — detect and fix systematic pitch shifts in OMR output.

homr sometimes produces notes that are systematically shifted by an
interval (e.g., minor 3rd down in Boże mój). This module detects
the shift by comparing note distribution to the expected key signature
and corrects it by transposing all notes.

Strategy:
1. Analyze the distribution of note names in the OMR output
2. Compare to the expected key signature (from peer voting or text)
3. If >50% of notes are accidentals NOT in the key, suspect a shift
4. Try common shifts (m2, M2, m3, M3) and pick the one that best
   aligns with the expected key
5. Transpose all notes by the detected interval
"""

import logging
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from music21 import (
    converter, interval, key, note, pitch, stream
)

logger = logging.getLogger(__name__)

# Common systematic shifts homr produces (in semitones)
_CANDIDATE_SHIFTS = [
    -3,  # minor 3rd down  (most common in Boże mój)
    -2,  # major 2nd down
    -1,  # minor 2nd down
    +1,  # minor 2nd up
    +2,  # major 2nd up
    +3,  # minor 3rd up
    -4,  # major 3rd down
    +4,  # major 3rd up
    -5,  # perfect 4th down
    +5,  # perfect 4th up
]

# Notes in each key signature (by fifths value)
# fifths → set of pitch classes ("C", "D", etc.) that are natural in key
_KEY_SCALE_NOTES: Dict[int, List[str]] = {}


def _build_key_scales():
    """Pre-build scale note sets for common key signatures."""
    for fifths in range(-7, 8):
        try:
            k = key.Key(key.KeySignature(fifths).asKey('major').tonic.name)
            scale_pitches = k.getScale('major').getPitches()
            note_names = set()
            for p in scale_pitches:
                note_names.add(p.name)  # e.g., "F#", "Bb"
            _KEY_SCALE_NOTES[fifths] = list(note_names)
        except Exception:
            pass


_build_key_scales()


def detect_pitch_shift(
    musicxml_path: str,
    expected_fifths: int,
    min_notes: int = 10,
    confidence_threshold: float = 0.4,
) -> Optional[int]:
    """Detect systematic pitch shift in an OMR result.

    Args:
        musicxml_path: Path to MusicXML file
        expected_fifths: Expected key signature as fifths value
        min_notes: Minimum notes required for reliable detection
        confidence_threshold: Required improvement ratio to confirm shift

    Returns:
        Semitone shift to apply (negative = down), or None if no shift
    """
    try:
        score = converter.parse(musicxml_path)
    except Exception as e:
        logger.warning(f"Could not parse {musicxml_path}: {e}")
        return None

    if not score.parts:
        return None

    part = score.parts[0]
    all_notes = list(part.flatten().notes)

    if len(all_notes) < min_notes:
        return None

    # Count pitch classes
    pitch_counts = Counter()
    for n in all_notes:
        if hasattr(n, 'pitch'):
            pitch_counts[n.pitch.name] += 1
        elif hasattr(n, 'pitches'):
            for p in n.pitches:
                pitch_counts[p.name] += 1

    if not pitch_counts:
        return None

    total = sum(pitch_counts.values())

    # Score the current notes against the expected key
    current_score = _key_fitness(pitch_counts, total, expected_fifths)

    # Try each candidate shift
    best_shift = 0
    best_score = current_score

    for shift in _CANDIDATE_SHIFTS:
        shifted_counts = _shift_pitches(pitch_counts, shift)
        score_val = _key_fitness(shifted_counts, total, expected_fifths)
        if score_val > best_score:
            best_score = score_val
            best_shift = shift

    # Check if the improvement is significant
    if best_shift != 0:
        improvement = best_score - current_score
        if improvement >= confidence_threshold:
            logger.info(
                f"Detected pitch shift: {best_shift} semitones "
                f"(fitness {current_score:.2f} → {best_score:.2f})"
            )
            return best_shift

    return None


def apply_pitch_correction(
    musicxml_path: str,
    semitone_shift: int,
    output_path: Optional[str] = None,
) -> str:
    """Apply a pitch correction to all notes in a MusicXML file.

    Args:
        musicxml_path: Path to MusicXML
        semitone_shift: Semitones to transpose (negative = down)
        output_path: Where to save (default: overwrite input)

    Returns:
        Path to corrected file
    """
    try:
        score = converter.parse(musicxml_path)
    except Exception as e:
        logger.error(f"Could not parse {musicxml_path}: {e}")
        return musicxml_path

    if not score.parts:
        return musicxml_path

    # Create the transposition interval
    ivl = interval.Interval(semitone_shift)

    # Transpose the entire score
    score.transpose(ivl, inPlace=True)

    out = output_path or musicxml_path
    try:
        score.write("musicxml", fp=out)
    except Exception as e:
        logger.warning(f"Failed to write corrected pitch: {e}")

    logger.info(f"Applied pitch correction: {semitone_shift} semitones")
    return out


def auto_correct_pitch(
    musicxml_path: str,
    expected_fifths: int,
    output_path: Optional[str] = None,
) -> Tuple[str, Optional[int]]:
    """Detect and automatically correct pitch shift.

    Args:
        musicxml_path: Path to MusicXML
        expected_fifths: Expected key signature (fifths)
        output_path: Where to save (or overwrite)

    Returns:
        Tuple of (output_path, shift_applied or None)
    """
    shift = detect_pitch_shift(musicxml_path, expected_fifths)
    if shift is not None and shift != 0:
        out = apply_pitch_correction(
            musicxml_path, shift, output_path
        )
        return out, shift
    return musicxml_path, None


def _key_fitness(
    pitch_counts: Counter,
    total: int,
    fifths: int,
) -> float:
    """Score how well a set of pitch classes fits a key.

    Returns fraction of notes (0-1) that are diatonic to the key.
    """
    if fifths not in _KEY_SCALE_NOTES or total == 0:
        return 0.0

    key_notes = _KEY_SCALE_NOTES[fifths]
    in_key = 0
    for pname, count in pitch_counts.items():
        # Normalize pitch name for comparison
        if pname in key_notes:
            in_key += count
        else:
            # Try enharmonic equivalents
            try:
                p = pitch.Pitch(pname)
                enharmonic = p.getEnharmonic()
                if enharmonic.name in key_notes:
                    in_key += count
            except Exception:
                pass

    return in_key / total


def _shift_pitches(
    pitch_counts: Counter,
    semitones: int,
) -> Counter:
    """Shift all pitch classes by a number of semitones."""
    shifted = Counter()
    for pname, count in pitch_counts.items():
        try:
            p = pitch.Pitch(pname)
            p = p.transpose(semitones)
            shifted[p.name] += count
        except Exception:
            shifted[pname] += count
    return shifted
