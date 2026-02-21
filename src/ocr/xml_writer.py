"""XML writer — low-level MusicXML element construction.

Provides functions that build MusicXML XML elements (via ElementTree)
from music21 objects and PartDefinition metadata.  All functions are
stateless and operate on explicit parameters.

Constants:
    DIVISIONS — quarter-note subdivision used in all duration calculations.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from music21 import chord, clef, converter, key, meter, note

from .part_definition import PartDefinition
from .text_classifier import ClassifiedText
from .staff_detector import StaffLayout

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIVISIONS = 4  # duration units per quarter note


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

def ql_to_div(dur_ql: float) -> int:
    """Convert quarter-length to MusicXML duration units."""
    return max(1, int(round(dur_ql * DIVISIONS)))


def dur_type(dur_ql: float) -> str:
    """Map quarter-length to MusicXML type name."""
    _MAP = {
        0.25: "16th",
        0.5: "eighth",
        0.75: "eighth",
        1.0: "quarter",
        1.5: "quarter",
        2.0: "half",
        3.0: "half",
        4.0: "whole",
        6.0: "whole",
    }
    return _MAP.get(dur_ql, "quarter")


def elem_dur(elem) -> float:
    """Get quarter-note duration from a music21 element."""
    return float(elem.duration.quarterLength)


# ---------------------------------------------------------------------------
# Voice separation
# ---------------------------------------------------------------------------

def separate_into_voices(
    raw: List[Tuple[float, float, object]],
) -> List[List[Tuple[float, float, object]]]:
    """Separate overlapping notes into non-overlapping voices.

    Uses greedy interval scheduling: each note is placed into the
    first voice whose last note ended at or before this note's offset.
    Notes are processed in order of (offset, -duration) so longer
    notes are placed first.

    Args:
        raw: List of (offset, duration, music21_element) tuples.

    Returns:
        List of voices, each a list of (offset, dur, elem).
    """
    if not raw:
        return []

    raw.sort(key=lambda x: (x[0], -x[1]))

    voices: List[List[Tuple[float, float, object]]] = []
    voice_ends: List[float] = []

    for off, dur, elem in raw:
        placed = False
        for vi, end in enumerate(voice_ends):
            if off >= end - 0.001:
                voices[vi].append((off, dur, elem))
                voice_ends[vi] = off + dur
                placed = True
                break
        if not placed:
            voices.append([(off, dur, elem)])
            voice_ends.append(off + dur)

    return voices


# ---------------------------------------------------------------------------
# Note-level XML writers
# ---------------------------------------------------------------------------

def write_single_note(
    measure_el: ET.Element,
    n: note.Note,
    pdef: PartDefinition,
) -> None:
    """Write a single note to MusicXML (used for single-staff parts).

    Args:
        measure_el: Parent <measure> element.
        n: music21 Note object.
        pdef: Part definition for staff assignment.
    """
    note_el = ET.SubElement(measure_el, "note")

    pitch_el = ET.SubElement(note_el, "pitch")
    ET.SubElement(pitch_el, "step").text = n.pitch.step
    if n.pitch.accidental and n.pitch.accidental.alter != 0:
        ET.SubElement(pitch_el, "alter").text = str(
            int(n.pitch.accidental.alter)
        )
    ET.SubElement(pitch_el, "octave").text = str(n.pitch.octave)

    dur_ql = n.duration.quarterLength
    ET.SubElement(note_el, "duration").text = str(ql_to_div(dur_ql))
    ET.SubElement(note_el, "type").text = dur_type(dur_ql)

    # Dotted note
    if dur_ql in (1.5, 3.0):
        ET.SubElement(note_el, "dot")

    # Staff assignment for grand staff parts
    if pdef.num_staves > 1:
        staff_num = 1 if n.pitch.midi >= 60 else 2
        ET.SubElement(note_el, "staff").text = str(staff_num)

    # Lyrics
    if n.lyrics:
        for lyric in n.lyrics:
            lyric_el = ET.SubElement(note_el, "lyric", number="1")
            if lyric.syllabic:
                ET.SubElement(lyric_el, "syllabic").text = lyric.syllabic
            ET.SubElement(lyric_el, "text").text = lyric.text or ""


def write_chord(
    measure_el: ET.Element,
    ch: chord.Chord,
    pdef: PartDefinition,
) -> None:
    """Write a chord to MusicXML.

    Args:
        measure_el: Parent <measure> element.
        ch: music21 Chord object.
        pdef: Part definition (unused but kept for API consistency).
    """
    dur_ql = ch.duration.quarterLength
    for ci, p in enumerate(ch.pitches):
        note_el = ET.SubElement(measure_el, "note")
        if ci > 0:
            ET.SubElement(note_el, "chord")
        pitch_el = ET.SubElement(note_el, "pitch")
        ET.SubElement(pitch_el, "step").text = p.step
        if p.accidental and p.accidental.alter != 0:
            ET.SubElement(pitch_el, "alter").text = str(
                int(p.accidental.alter)
            )
        ET.SubElement(pitch_el, "octave").text = str(p.octave)
        ET.SubElement(note_el, "duration").text = str(ql_to_div(dur_ql))
        ET.SubElement(note_el, "type").text = dur_type(dur_ql)
        if dur_ql in (1.5, 3.0):
            ET.SubElement(note_el, "dot")


# ---------------------------------------------------------------------------
# Measure-level XML writers
# ---------------------------------------------------------------------------

def write_voice_notes(
    measure_el: ET.Element,
    notes: List[Tuple[float, float, object]],
    voice: int,
    staff_num: int,
) -> float:
    """Write a sequence of non-overlapping notes for one voice.

    Adds <forward> for gaps.

    Args:
        measure_el: Parent <measure> element.
        notes: List of (offset, duration, music21_element) tuples.
        voice: Voice number.
        staff_num: Staff number (1 or 2).

    Returns:
        Final cursor position (quarter-length).
    """
    cursor = 0.0
    for off, dur, elem in notes:
        # Insert forward for gaps
        if off > cursor + 0.001:
            gap = off - cursor
            fwd = ET.SubElement(measure_el, "forward")
            ET.SubElement(fwd, "duration").text = str(ql_to_div(gap))
            ET.SubElement(fwd, "voice").text = str(voice)
            ET.SubElement(fwd, "staff").text = str(staff_num)
            cursor = off

        if isinstance(elem, note.Rest):
            note_el = ET.SubElement(measure_el, "note")
            ET.SubElement(note_el, "rest")
            ET.SubElement(note_el, "duration").text = str(ql_to_div(dur))
            ET.SubElement(note_el, "voice").text = str(voice)
            ET.SubElement(note_el, "type").text = dur_type(dur)
            if dur in (1.5, 3.0):
                ET.SubElement(note_el, "dot")
            ET.SubElement(note_el, "staff").text = str(staff_num)
            cursor += dur

        elif isinstance(elem, note.Note):
            note_el = ET.SubElement(measure_el, "note")
            pitch_el = ET.SubElement(note_el, "pitch")
            ET.SubElement(pitch_el, "step").text = elem.pitch.step
            if (elem.pitch.accidental
                    and elem.pitch.accidental.alter != 0):
                ET.SubElement(pitch_el, "alter").text = str(
                    int(elem.pitch.accidental.alter))
            ET.SubElement(pitch_el, "octave").text = str(
                elem.pitch.octave)
            ET.SubElement(note_el, "duration").text = str(ql_to_div(dur))
            ET.SubElement(note_el, "voice").text = str(voice)
            ET.SubElement(note_el, "type").text = dur_type(dur)
            if dur in (1.5, 3.0):
                ET.SubElement(note_el, "dot")
            ET.SubElement(note_el, "staff").text = str(staff_num)
            cursor += dur

        elif isinstance(elem, chord.Chord):
            for ci, p in enumerate(elem.pitches):
                note_el = ET.SubElement(measure_el, "note")
                if ci > 0:
                    ET.SubElement(note_el, "chord")
                pitch_el = ET.SubElement(note_el, "pitch")
                ET.SubElement(pitch_el, "step").text = p.step
                if p.accidental and p.accidental.alter != 0:
                    ET.SubElement(pitch_el, "alter").text = str(
                        int(p.accidental.alter))
                ET.SubElement(pitch_el, "octave").text = str(p.octave)
                ET.SubElement(note_el, "duration").text = str(
                    ql_to_div(dur))
                ET.SubElement(note_el, "voice").text = str(voice)
                ET.SubElement(note_el, "type").text = dur_type(dur)
                if dur in (1.5, 3.0):
                    ET.SubElement(note_el, "dot")
                ET.SubElement(note_el, "staff").text = str(staff_num)
            cursor += dur

    return cursor


def write_single_staff_measure(
    measure_el: ET.Element,
    m21_measure,
    pdef: PartDefinition,
) -> None:
    """Write notes for a single-staff part sequentially.

    Args:
        measure_el: Parent <measure> element.
        m21_measure: music21 Measure object.
        pdef: Part definition.
    """
    for elem in m21_measure.flatten().notesAndRests:
        if isinstance(elem, note.Rest):
            note_el = ET.SubElement(measure_el, "note")
            ET.SubElement(note_el, "rest")
            dur_ql = elem.duration.quarterLength
            ET.SubElement(note_el, "duration").text = str(ql_to_div(dur_ql))
            ET.SubElement(note_el, "type").text = dur_type(dur_ql)
            if dur_ql in (1.5, 3.0):
                ET.SubElement(note_el, "dot")
        elif isinstance(elem, note.Note):
            write_single_note(measure_el, elem, pdef)
        elif isinstance(elem, chord.Chord):
            write_chord(measure_el, elem, pdef)


def write_grand_staff_measure(
    measure_el: ET.Element,
    m21_measure,
    pdef: PartDefinition,
) -> None:
    """Write notes for a grand-staff part using backup elements.

    1. Classify every note/chord into staff 1 (treble) or staff 2 (bass).
    2. Within each staff, separate overlapping notes into voices.
    3. Write each voice sequentially with backup between them.

    Args:
        measure_el: Parent <measure> element.
        m21_measure: music21 Measure object.
        pdef: Part definition.
    """
    elements = list(m21_measure.flatten().notesAndRests)

    # ---- classify into staves ----
    staff1_raw: List[Tuple[float, float, object]] = []
    staff2_raw: List[Tuple[float, float, object]] = []

    for elem in elements:
        off = float(elem.offset)
        dur = float(elem.duration.quarterLength)
        if isinstance(elem, note.Rest):
            staff1_raw.append((off, dur, elem))
        elif isinstance(elem, note.Note):
            bucket = staff1_raw if elem.pitch.midi >= 60 else staff2_raw
            bucket.append((off, dur, elem))
        elif isinstance(elem, chord.Chord):
            avg = sum(p.midi for p in elem.pitches) / len(elem.pitches)
            bucket = staff1_raw if avg >= 60 else staff2_raw
            bucket.append((off, dur, elem))

    # Skip pure-rest staves when the other has real notes
    s1_real = any(
        not isinstance(e, note.Rest) for _, _, e in staff1_raw
    )
    s2_real = any(
        not isinstance(e, note.Rest) for _, _, e in staff2_raw
    )
    if not s1_real and s2_real:
        staff1_raw = []
    if not s2_real and s1_real:
        staff2_raw = []

    # ---- separate voices within each staff ----
    staff1_voices = separate_into_voices(staff1_raw)
    staff2_voices = separate_into_voices(staff2_raw)

    # ---- write all voices ----
    cursor = 0.0
    first_voice = True

    # Staff 1 voices: 1, 2, 3, ...
    for vi, voice_notes in enumerate(staff1_voices):
        voice_num = vi + 1
        if not first_voice:
            bk = ET.SubElement(measure_el, "backup")
            ET.SubElement(bk, "duration").text = str(ql_to_div(cursor))
        end = write_voice_notes(measure_el, voice_notes, voice_num, 1)
        cursor = end
        first_voice = False

    # Staff 2 voices: 5, 6, 7, ...
    for vi, voice_notes in enumerate(staff2_voices):
        voice_num = vi + 5
        if not first_voice:
            bk = ET.SubElement(measure_el, "backup")
            ET.SubElement(bk, "duration").text = str(ql_to_div(cursor))
        end = write_voice_notes(measure_el, voice_notes, voice_num, 2)
        cursor = end
        first_voice = False


def write_measure_notes(
    measure_el: ET.Element,
    m21_measure,
    pdef: PartDefinition,
) -> None:
    """Write notes from a music21 measure to MusicXML elements.

    For grand staff parts (num_staves > 1), uses offset-based layout
    with <backup> elements between staves so that beats aren't doubled.

    Args:
        measure_el: Parent <measure> element.
        m21_measure: music21 Measure.
        pdef: Part definition.
    """
    if pdef.num_staves > 1:
        write_grand_staff_measure(measure_el, m21_measure, pdef)
    else:
        write_single_staff_measure(measure_el, m21_measure, pdef)


# ---------------------------------------------------------------------------
# Part-level XML writers
# ---------------------------------------------------------------------------

def fill_empty_part(
    part_el: ET.Element,
    pdef: PartDefinition,
    text_info: ClassifiedText,
) -> None:
    """Fill a part with empty measures when no OMR data is available.

    Args:
        part_el: Parent <part> element.
        pdef: Part definition.
        text_info: Classified text (unused but kept for API consistency).
    """
    measure = ET.SubElement(part_el, "measure", number="1")

    attr_el = ET.SubElement(measure, "attributes")
    ET.SubElement(attr_el, "divisions").text = str(DIVISIONS)

    key_el = ET.SubElement(attr_el, "key")
    ET.SubElement(key_el, "fifths").text = "0"

    time_el = ET.SubElement(attr_el, "time")
    ET.SubElement(time_el, "beats").text = "4"
    ET.SubElement(time_el, "beat-type").text = "4"

    if pdef.num_staves > 1:
        ET.SubElement(attr_el, "staves").text = str(pdef.num_staves)

    for ci, clef_type in enumerate(pdef.clefs):
        clef_el = ET.SubElement(attr_el, "clef")
        if pdef.num_staves > 1:
            clef_el.set("number", str(ci + 1))
        if clef_type == "G":
            ET.SubElement(clef_el, "sign").text = "G"
            ET.SubElement(clef_el, "line").text = "2"
        elif clef_type == "F":
            ET.SubElement(clef_el, "sign").text = "F"
            ET.SubElement(clef_el, "line").text = "4"

    # Add a whole rest
    note_el = ET.SubElement(measure, "note")
    ET.SubElement(note_el, "rest", measure="yes")
    ET.SubElement(note_el, "duration").text = str(ql_to_div(4.0))
    ET.SubElement(note_el, "type").text = "whole"


def fill_part_from_omr(
    part_el: ET.Element,
    pdef: PartDefinition,
    omr_score,
    text_info: ClassifiedText,
) -> None:
    """Fill a part element with notes from OMR result.

    Args:
        part_el: Parent <part> element.
        pdef: Part definition.
        omr_score: Parsed music21 Score from OMR.
        text_info: Classified text for tempo markings.
    """
    omr_part = list(omr_score.parts)[0]
    measures = list(omr_part.getElementsByClass("Measure"))

    if not measures:
        fill_empty_part(part_el, pdef, text_info)
        return

    # Detect anacrusis
    first_measure_dur = measures[0].duration.quarterLength

    time_sigs = omr_part.flatten().getElementsByClass("TimeSignature")
    expected_beats = 4.0
    if time_sigs:
        expected_beats = time_sigs[0].barDuration.quarterLength

    is_anacrusis = first_measure_dur < expected_beats * 0.9

    for m_idx, m21_measure in enumerate(measures):
        m_num = m_idx + 1
        attrs = {"number": str(m_num)}

        if m_idx == 0 and is_anacrusis:
            attrs["number"] = "0"
            attrs["implicit"] = "yes"

        measure_el = ET.SubElement(part_el, "measure", **attrs)

        # Attributes on first measure
        if m_idx == 0:
            attr_el = ET.SubElement(measure_el, "attributes")
            ET.SubElement(attr_el, "divisions").text = str(DIVISIONS)

            # Key signature
            key_el = ET.SubElement(attr_el, "key")
            keys = omr_part.flatten().getElementsByClass("KeySignature")
            fifths = 0
            if keys:
                fifths = keys[0].sharps
            ET.SubElement(key_el, "fifths").text = str(fifths)

            # Time signature
            time_el = ET.SubElement(attr_el, "time")
            if time_sigs:
                ts = time_sigs[0]
                ET.SubElement(time_el, "beats").text = str(ts.numerator)
                ET.SubElement(time_el, "beat-type").text = str(
                    ts.denominator
                )
            else:
                ET.SubElement(time_el, "beats").text = "4"
                ET.SubElement(time_el, "beat-type").text = "4"

            # Staves
            if pdef.num_staves > 1:
                ET.SubElement(attr_el, "staves").text = str(
                    pdef.num_staves
                )

            # Clefs
            for ci, clef_type in enumerate(pdef.clefs):
                clef_el = ET.SubElement(attr_el, "clef")
                if pdef.num_staves > 1:
                    clef_el.set("number", str(ci + 1))
                if clef_type == "G":
                    ET.SubElement(clef_el, "sign").text = "G"
                    ET.SubElement(clef_el, "line").text = "2"
                elif clef_type == "F":
                    ET.SubElement(clef_el, "sign").text = "F"
                    ET.SubElement(clef_el, "line").text = "4"

            # Tempo from text info
            if text_info.tempo_markings:
                tempo_text = text_info.tempo_markings[0]["text"]
                tempo_match = re.search(r"(\d+)", tempo_text)
                if tempo_match:
                    bpm = tempo_match.group(1)
                    direction = ET.SubElement(
                        measure_el, "direction", placement="above"
                    )
                    dir_type = ET.SubElement(direction, "direction-type")
                    metro = ET.SubElement(dir_type, "metronome")
                    ET.SubElement(metro, "beat-unit").text = "quarter"
                    ET.SubElement(metro, "per-minute").text = bpm
                    ET.SubElement(direction, "sound", tempo=bpm)

        # Write notes from OMR
        write_measure_notes(measure_el, m21_measure, pdef)


# ---------------------------------------------------------------------------
# Score-level XML builders
# ---------------------------------------------------------------------------

def build_musicxml(
    parts_def: List[PartDefinition],
    parsed_parts: Dict[tuple, object],
    text_info: ClassifiedText,
    layout: StaffLayout,
) -> ET.Element:
    """Build complete MusicXML XML tree (simple, non-assembled version).

    For each part, looks up the matching OMR result by staff indices
    and fills the part from OMR data.

    Args:
        parts_def: List of part definitions.
        parsed_parts: Map of staff index tuple → parsed music21 Score.
        text_info: Classified text (title, composer, etc.).
        layout: Staff layout.

    Returns:
        Root <score-partwise> ElementTree element.
    """
    root = ET.Element("score-partwise", version="4.0")

    # --- Work/movement titles ---
    if text_info.title:
        work = ET.SubElement(root, "work")
        ET.SubElement(work, "work-title").text = text_info.title

    # --- Identification ---
    ident = ET.SubElement(root, "identification")
    if text_info.composer:
        ET.SubElement(ident, "creator", type="composer").text = (
            text_info.composer
        )
    if text_info.arranger:
        ET.SubElement(ident, "creator", type="arranger").text = (
            text_info.arranger
        )
    encoding = ET.SubElement(ident, "encoding")
    ET.SubElement(encoding, "software").text = "Church Music Organizer OMR"
    ET.SubElement(encoding, "encoding-date").text = "2025-07-26"

    # --- Part list ---
    part_list = ET.SubElement(root, "part-list")

    # Determine bracket groups
    vocal_parts = [
        p for p in parts_def if p.is_vocal and p.group_number > 0
    ]
    if vocal_parts:
        group_num = vocal_parts[0].group_number
        pg_start = ET.SubElement(
            part_list, "part-group",
            type="start", number=str(group_num),
        )
        ET.SubElement(pg_start, "group-symbol").text = "bracket"
        ET.SubElement(pg_start, "group-barline").text = "yes"

    for i, pdef in enumerate(parts_def):
        sp = ET.SubElement(part_list, "score-part", id=pdef.part_id)
        ET.SubElement(sp, "part-name").text = pdef.part_name
        if pdef.abbreviation:
            ET.SubElement(sp, "part-abbreviation").text = pdef.abbreviation

        # Score instrument
        inst_id = f"{pdef.part_id}-I1"
        si = ET.SubElement(sp, "score-instrument", id=inst_id)
        ET.SubElement(si, "instrument-name").text = pdef.instrument_name
        if pdef.instrument_sound:
            ET.SubElement(si, "instrument-sound").text = (
                pdef.instrument_sound
            )

        # MIDI
        midi_el = ET.SubElement(sp, "midi-instrument", id=inst_id)
        ET.SubElement(midi_el, "midi-channel").text = str(i + 1)
        ET.SubElement(midi_el, "midi-program").text = str(pdef.midi_program)

        # Close bracket group after last vocal part
        if (pdef.is_vocal and pdef.group_number > 0
                and pdef == vocal_parts[-1]):
            ET.SubElement(
                part_list, "part-group",
                type="stop", number=str(pdef.group_number),
            )

    # --- Parts with measures ---
    for pdef in parts_def:
        part_el = ET.SubElement(root, "part", id=pdef.part_id)

        # Try to find matching OMR result
        omr_key = tuple(pdef.staff_indices)
        omr_score = parsed_parts.get(omr_key)

        if omr_score and list(omr_score.parts):
            fill_part_from_omr(part_el, pdef, omr_score, text_info)
        else:
            fill_empty_part(part_el, pdef, text_info)

    return root


# ---------------------------------------------------------------------------
# Pitch-range split builder (for build_from_single_omr)
# ---------------------------------------------------------------------------

def get_pitch_range_for_part(
    pdef: PartDefinition,
    all_parts: List[PartDefinition],
) -> Tuple[int, int]:
    """Get the MIDI pitch range for note assignment to this part.

    Args:
        pdef: Part definition.
        all_parts: All part definitions (for context).

    Returns:
        (low_midi, high_midi) tuple.
    """
    name_lower = pdef.part_name.lower().replace("\n", " ")

    if "s" in name_lower and "a" in name_lower:
        return (55, 90)    # SA: G3 to F#6
    elif "t" in name_lower and "b" in name_lower:
        return (36, 62)    # TB: C2 to D4
    elif "org" in name_lower or "piano" in name_lower:
        return (24, 96)    # Full range
    elif "s" in name_lower:
        return (60, 84)    # S: C4-C6
    elif "a" in name_lower:
        return (53, 77)    # A: F3-F5
    elif "t" in name_lower:
        return (48, 72)    # T: C3-C5
    elif "b" in name_lower:
        return (40, 64)    # B: E2-E4

    # Default: use clef
    if "F" in pdef.clefs:
        return (36, 62)
    return (55, 90)


def write_first_measure_attrs(
    measure_el: ET.Element,
    pdef: PartDefinition,
    omr_part,
    text_info: ClassifiedText,
) -> None:
    """Write first-measure attributes for a part.

    Args:
        measure_el: <measure> element.
        pdef: Part definition.
        omr_part: music21 Part from OMR.
        text_info: Classified text for tempo markings.
    """
    attr_el = ET.SubElement(measure_el, "attributes")
    ET.SubElement(attr_el, "divisions").text = str(DIVISIONS)

    key_el = ET.SubElement(attr_el, "key")
    keys = omr_part.flatten().getElementsByClass("KeySignature")
    fifths = keys[0].sharps if keys else 0
    ET.SubElement(key_el, "fifths").text = str(fifths)

    time_el = ET.SubElement(attr_el, "time")
    time_sigs = omr_part.flatten().getElementsByClass("TimeSignature")
    if time_sigs:
        ET.SubElement(time_el, "beats").text = str(time_sigs[0].numerator)
        ET.SubElement(time_el, "beat-type").text = str(
            time_sigs[0].denominator
        )
    else:
        ET.SubElement(time_el, "beats").text = "4"
        ET.SubElement(time_el, "beat-type").text = "4"

    if pdef.num_staves > 1:
        ET.SubElement(attr_el, "staves").text = str(pdef.num_staves)

    for ci, clef_type in enumerate(pdef.clefs):
        clef_el = ET.SubElement(attr_el, "clef")
        if pdef.num_staves > 1:
            clef_el.set("number", str(ci + 1))
        if clef_type == "G":
            ET.SubElement(clef_el, "sign").text = "G"
            ET.SubElement(clef_el, "line").text = "2"
        else:
            ET.SubElement(clef_el, "sign").text = "F"
            ET.SubElement(clef_el, "line").text = "4"

    # Tempo
    if text_info.tempo_markings:
        tempo_match = re.search(
            r"(\d+)", text_info.tempo_markings[0]["text"]
        )
        if tempo_match:
            bpm = tempo_match.group(1)
            direction = ET.SubElement(
                measure_el, "direction", placement="above"
            )
            dir_type = ET.SubElement(direction, "direction-type")
            metro = ET.SubElement(dir_type, "metronome")
            ET.SubElement(metro, "beat-unit").text = "quarter"
            ET.SubElement(metro, "per-minute").text = bpm
            ET.SubElement(direction, "sound", tempo=bpm)


def write_filtered_notes(
    measure_el: ET.Element,
    m21_measure,
    pdef: PartDefinition,
    pitch_range: Tuple[int, int],
) -> None:
    """Write notes from a measure, filtered by pitch range.

    Args:
        measure_el: <measure> element.
        m21_measure: music21 Measure.
        pdef: Part definition.
        pitch_range: (low_midi, high_midi) filter range.
    """
    has_notes = False
    for elem in m21_measure.flatten().notesAndRests:
        if isinstance(elem, note.Rest):
            note_el = ET.SubElement(measure_el, "note")
            ET.SubElement(note_el, "rest")
            dur = ql_to_div(elem.duration.quarterLength)
            ET.SubElement(note_el, "duration").text = str(dur)
            ET.SubElement(note_el, "type").text = dur_type(
                elem.duration.quarterLength
            )
            has_notes = True

        elif isinstance(elem, note.Note):
            if pitch_range[0] <= elem.pitch.midi <= pitch_range[1]:
                write_single_note(measure_el, elem, pdef)
                has_notes = True

        elif isinstance(elem, chord.Chord):
            matching = [
                p for p in elem.pitches
                if pitch_range[0] <= p.midi <= pitch_range[1]
            ]
            if matching:
                for ci, p in enumerate(matching):
                    note_el = ET.SubElement(measure_el, "note")
                    if ci > 0:
                        ET.SubElement(note_el, "chord")

                    pitch_el = ET.SubElement(note_el, "pitch")
                    ET.SubElement(pitch_el, "step").text = p.step
                    if p.accidental and p.accidental.alter != 0:
                        ET.SubElement(pitch_el, "alter").text = str(
                            int(p.accidental.alter)
                        )
                    ET.SubElement(pitch_el, "octave").text = str(p.octave)

                    dur = ql_to_div(elem.duration.quarterLength)
                    ET.SubElement(note_el, "duration").text = str(dur)
                    ET.SubElement(note_el, "type").text = dur_type(
                        elem.duration.quarterLength
                    )

                    if pdef.num_staves > 1:
                        staff_num = 1 if p.midi >= 60 else 2
                        ET.SubElement(note_el, "staff").text = str(
                            staff_num
                        )
                has_notes = True

    if not has_notes:
        note_el = ET.SubElement(measure_el, "note")
        ET.SubElement(note_el, "rest", measure="yes")
        ET.SubElement(note_el, "duration").text = str(ql_to_div(4.0))
        ET.SubElement(note_el, "type").text = "whole"


def build_musicxml_from_split(
    parts_def: List[PartDefinition],
    omr_part,
    text_info: ClassifiedText,
    layout: StaffLayout,
) -> ET.Element:
    """Build multi-part MusicXML by splitting a single OMR part by pitch.

    Args:
        parts_def: List of part definitions.
        omr_part: music21 Part from monolithic OMR.
        text_info: Classified text.
        layout: Staff layout.

    Returns:
        Root <score-partwise> ElementTree element.
    """
    root = ET.Element("score-partwise", version="4.0")

    # Title & identification
    if text_info.title:
        work = ET.SubElement(root, "work")
        ET.SubElement(work, "work-title").text = text_info.title

    ident = ET.SubElement(root, "identification")
    if text_info.composer:
        ET.SubElement(ident, "creator", type="composer").text = (
            text_info.composer
        )
    if text_info.arranger:
        ET.SubElement(ident, "creator", type="arranger").text = (
            text_info.arranger
        )
    encoding = ET.SubElement(ident, "encoding")
    ET.SubElement(encoding, "software").text = "Church Music Organizer OMR"

    # Part list
    part_list = ET.SubElement(root, "part-list")

    vocal_parts = [
        p for p in parts_def if p.is_vocal and p.group_number > 0
    ]
    if vocal_parts:
        pg = ET.SubElement(
            part_list, "part-group", type="start", number="1"
        )
        ET.SubElement(pg, "group-symbol").text = "bracket"
        ET.SubElement(pg, "group-barline").text = "yes"

    for i, pdef in enumerate(parts_def):
        sp = ET.SubElement(part_list, "score-part", id=pdef.part_id)
        ET.SubElement(sp, "part-name").text = pdef.part_name
        if pdef.abbreviation:
            ET.SubElement(sp, "part-abbreviation").text = pdef.abbreviation

        inst_id = f"{pdef.part_id}-I1"
        si = ET.SubElement(sp, "score-instrument", id=inst_id)
        ET.SubElement(si, "instrument-name").text = pdef.instrument_name
        if pdef.instrument_sound:
            ET.SubElement(si, "instrument-sound").text = (
                pdef.instrument_sound
            )

        midi_el = ET.SubElement(sp, "midi-instrument", id=inst_id)
        ET.SubElement(midi_el, "midi-channel").text = str(i + 1)
        ET.SubElement(midi_el, "midi-program").text = str(pdef.midi_program)

        if (pdef.is_vocal and pdef.group_number > 0
                and pdef == vocal_parts[-1]):
            ET.SubElement(
                part_list, "part-group", type="stop", number="1"
            )

    # Get measures from OMR
    omr_measures = list(omr_part.getElementsByClass("Measure"))

    # For each part definition, create a part with notes filtered by pitch
    for pdef in parts_def:
        part_el = ET.SubElement(root, "part", id=pdef.part_id)
        pitch_range = get_pitch_range_for_part(pdef, parts_def)

        for m_idx, m21_m in enumerate(omr_measures):
            m_num = m_idx + 1
            measure_el = ET.SubElement(
                part_el, "measure", number=str(m_num)
            )

            if m_idx == 0:
                write_first_measure_attrs(
                    measure_el, pdef, omr_part, text_info
                )

            write_filtered_notes(measure_el, m21_m, pdef, pitch_range)

    return root
