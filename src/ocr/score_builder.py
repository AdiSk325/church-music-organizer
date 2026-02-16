"""Score builder — assemble multi-part MusicXML from per-staff OMR results.

Takes the OMR results from individual staves and combines them into
a properly structured MusicXML score with:
- Correct part-list with part names and instrument sounds
- Staff groups (brackets/braces)
- Proper voice numbering per part
- Metadata (title, composer, tempo)
- Anacrusis detection
- Lyrics placement on vocal parts only
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from music21 import (
    converter, stream, note, chord, key, meter, clef,
    instrument, metadata, tempo, layout, expressions
)

from .text_classifier import ClassifiedText
from .staff_detector import StaffLayout, StaffGroup

logger = logging.getLogger(__name__)


# Mapping from part name abbreviations to instrument types
INSTRUMENT_MAP = {
    "s": ("Soprano", "voice.soprano", "voice.female"),
    "a": ("Alto", "voice.alto", "voice.female"),
    "t": ("Tenor", "voice.tenor", "voice.male"),
    "b": ("Bass", "voice.bass", "voice.male"),
    "org": ("Organo", "keyboard.organ", "keyboard.organ"),
    "org.": ("Organo", "keyboard.organ", "keyboard.organ"),
    "organo": ("Organo", "keyboard.organ", "keyboard.organ"),
    "piano": ("Piano", "keyboard.piano", "keyboard.piano"),
    "pf": ("Piano", "keyboard.piano", "keyboard.piano"),
    "fl": ("Flute", "wind.flutes.flute", "wind.flutes.flute"),
}


@dataclass
class PartDefinition:
    """Definition of a part to be created in the score."""
    part_id: str = ""          # e.g. "P1"
    part_name: str = ""        # e.g. "S\nA" or "Organo"
    abbreviation: str = ""     # e.g. "S.A." or "Org."
    instrument_name: str = ""  # e.g. "Women" or "Organo"
    instrument_sound: str = "" # e.g. "voice.female" or "keyboard.organ"
    midi_channel: int = 1
    midi_program: int = 1
    num_staves: int = 1        # 1 for vocal, 2 for grand staff
    clefs: List[str] = field(default_factory=list)  # per staff: "G", "F"
    staff_indices: List[int] = field(default_factory=list)  # which staves from layout
    is_vocal: bool = True
    group_type: str = "none"   # "bracket", "brace", "none"
    group_number: int = 0      # for part-group start/stop


class ScoreBuilder:
    """Build a complete MusicXML score from per-staff OMR results."""

    # Divisions per quarter note — must be >= 4 for 16th notes.
    DIVISIONS = 4

    def _ql_to_div(self, ql: float) -> int:
        """Convert quarter-length to MusicXML duration units."""
        return max(1, int(round(ql * self.DIVISIONS)))

    def build(
        self,
        staff_omr_results: List[dict],
        text_info: ClassifiedText,
        layout: StaffLayout,
        output_path: str,
    ) -> str:
        """Build a complete MusicXML score.

        Args:
            staff_omr_results: List of {"path": musicxml_path,
                "staff_indices": [int], "group_type": str}
            text_info: Classified text from PDF
            layout: Staff layout from detector
            output_path: Where to save the final MusicXML

        Returns:
            Path to the output MusicXML file
        """
        # Step 1: Determine part structure from layout + text
        parts_def = self._determine_parts(layout, text_info)
        
        if not parts_def:
            logger.warning("Could not determine part structure, "
                           "falling back to single part")
            # Fallback: if we have OMR results, use the first one as-is
            if staff_omr_results:
                import shutil
                shutil.copy2(staff_omr_results[0]["path"], output_path)
                return output_path
            return ""

        logger.info(f"Building score with {len(parts_def)} parts")
        self.last_parts_def = parts_def  # expose for lyrics alignment

        # Step 2: Parse each per-staff OMR result
        parsed_parts = {}
        for omr_result in staff_omr_results:
            if not omr_result.get("path") or not Path(omr_result["path"]).exists():
                continue
            try:
                score = converter.parse(omr_result["path"])
                staff_indices = omr_result.get("staff_indices", [])
                key_str = tuple(staff_indices)
                parsed_parts[key_str] = score
            except Exception as e:
                logger.warning(f"Could not parse {omr_result['path']}: {e}")

        # Step 3: Build the MusicXML using ElementTree for precise control
        musicxml = self._build_musicxml(parts_def, parsed_parts, text_info, layout)

        # Step 4: Write output
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        tree = ET.ElementTree(musicxml)
        ET.indent(tree, space="  ")

        with open(str(output_path), "wb") as f:
            tree.write(f, encoding="UTF-8", xml_declaration=True)

        # Add DOCTYPE
        content = output_path.read_text(encoding="utf-8")
        if "<!DOCTYPE" not in content:
            content = content.replace(
                "<?xml version='1.0' encoding='UTF-8'?>",
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                '"http://www.musicxml.org/dtds/partwise.dtd">',
                1
            )
            output_path.write_text(content, encoding="utf-8")

        logger.info(f"Score saved to {output_path}")
        return str(output_path)

    def _determine_parts(
        self,
        layout: StaffLayout,
        text_info: ClassifiedText,
    ) -> List[PartDefinition]:
        """Determine part structure from staff layout and text metadata.

        Uses the number of staves per system, staff groups, and part labels
        to define the score's part structure.
        """
        parts = []

        if not layout.systems:
            return parts

        first_system = layout.systems[0]
        staves_in_system = first_system.staff_indices
        n_staves = len(staves_in_system)

        # Get sorted part names from text_info (sorted by y position)
        part_names = sorted(text_info.part_names, key=lambda p: p.get("y", 0))
        
        # Find brace groups (grand staff = organ/piano)
        brace_staves = set()
        brace_groups = []
        for g in layout.groups:
            if g.group_type == "brace":
                for idx in g.staff_indices:
                    brace_staves.add(idx)
                brace_groups.append(g)

        # Build parts: single staves become individual parts,
        # brace pairs become grand-staff parts
        processed = set()
        part_idx = 1
        vocal_parts = []
        bracket_group_num = 1
        has_bracket_group = False

        for staff_idx in sorted(staves_in_system):
            if staff_idx in processed:
                continue

            # Check if this staff is part of a brace group
            in_brace = None
            for bg in brace_groups:
                if staff_idx in bg.staff_indices:
                    in_brace = bg
                    break

            if in_brace:
                # Grand staff (organ/piano)
                brace_indices = sorted(in_brace.staff_indices)
                part_name = self._find_part_name(brace_indices, part_names, layout)
                
                part_def = PartDefinition(
                    part_id=f"P{part_idx}",
                    part_name=part_name or "Organo",
                    abbreviation=self._abbreviate(part_name or "Org."),
                    num_staves=len(brace_indices),
                    clefs=["G", "F"],  # typical grand staff
                    staff_indices=brace_indices,
                    is_vocal=False,
                    group_type="brace",
                )
                self._assign_instrument(part_def)
                parts.append(part_def)
                
                for si in brace_indices:
                    processed.add(si)
                part_idx += 1
            else:
                # Single staff
                part_name = self._find_part_name([staff_idx], part_names, layout)
                
                part_def = PartDefinition(
                    part_id=f"P{part_idx}",
                    part_name=part_name or f"Part {part_idx}",
                    abbreviation=self._abbreviate(part_name or ""),
                    num_staves=1,
                    staff_indices=[staff_idx],
                    is_vocal=True,
                )

                # Determine clef from position
                # Upper staves = treble, lower staves = bass
                staff_position = staves_in_system.index(staff_idx)
                non_brace_staves = [s for s in staves_in_system if s not in brace_staves]
                if non_brace_staves:
                    mid = len(non_brace_staves) // 2
                    if non_brace_staves.index(staff_idx) < mid if staff_idx in non_brace_staves else True:
                        part_def.clefs = ["G"]
                    else:
                        part_def.clefs = ["F"]
                else:
                    part_def.clefs = ["G"]

                self._assign_instrument(part_def)
                vocal_parts.append(part_def)
                parts.append(part_def)
                processed.add(staff_idx)
                part_idx += 1

        # If there are multiple vocal parts, they likely need a bracket group
        if len(vocal_parts) >= 2:
            for vp in vocal_parts:
                vp.group_number = bracket_group_num
            has_bracket_group = True

        # Check if we can merge vocal parts that share a staff
        # e.g., "S" and "A" labels near the same staff → combine into "S\nA"
        parts = self._merge_vocal_parts(parts, part_names, layout)

        return parts

    def _find_part_name(
        self,
        staff_indices: List[int],
        part_names: List[Dict],
        layout: StaffLayout,
    ) -> str:
        """Find the part name label closest to the given staff indices.

        Uses RELATIVE y positions because text coords (PDF points @ 72 DPI)
        and staff coords (image pixels @ 300 DPI) are in different units.
        """
        if not part_names or not layout.staves or not layout.image_height:
            return ""

        target_staves = [s for s in layout.staves if s.index in staff_indices]
        if not target_staves:
            return ""

        # Compute relative y range for this staff in image coordinates
        rel_y_top = min(s.y_top for s in target_staves) / layout.image_height
        rel_y_bottom = max(s.y_bottom for s in target_staves) / layout.image_height

        # Search with a generous margin (text labels are offset from staff)
        margin = 0.04  # 4% of page height
        search_top = rel_y_top - margin
        search_bottom = rel_y_bottom + margin

        # Find text labels within this relative y range
        matching = []
        for pn in part_names:
            pn_rel_y = pn.get("rel_y", 0)
            if search_top <= pn_rel_y <= search_bottom:
                matching.append(pn["name"])

        if not matching:
            # Try wider margin
            margin = 0.08
            search_top = rel_y_top - margin
            search_bottom = rel_y_bottom + margin
            for pn in part_names:
                pn_rel_y = pn.get("rel_y", 0)
                if search_top <= pn_rel_y <= search_bottom:
                    matching.append(pn["name"])

        if matching:
            if len(matching) == 1:
                return matching[0]
            else:
                # Multiple labels (e.g., "S" and "A" for SA staff)
                return "\n".join(matching)

        return ""

    def _merge_vocal_parts(
        self,
        parts: List[PartDefinition],
        part_names: List[Dict],
        layout: StaffLayout,
    ) -> List[PartDefinition]:
        """Merge vocal parts that share a staff.

        In SATB scores, S and A are often on the same treble staff,
        T and B on the same bass staff. The text labels tell us if
        a single staff has two voice names.
        """
        # This is already handled by _find_part_name returning "S\nA"
        # Just ensure the part names are correct
        return parts

    def _assign_instrument(self, part: PartDefinition):
        """Assign instrument name and MIDI info based on part name."""
        name_lower = part.part_name.lower().replace("\n", " ").strip()

        # Check for combined vocal parts like "S\nA" or "T\nB"
        parts = [p.strip().lower().rstrip(".") for p in part.part_name.split("\n")]

        if len(parts) == 2:
            # Combined part
            if set(parts) <= {"s", "a", "soprano", "alt", "sopran"}:
                part.instrument_name = "Women"
                part.instrument_sound = "voice.female"
                part.is_vocal = True
                part.midi_program = 53  # Voice Oohs
                return
            elif set(parts) <= {"t", "b", "tenor", "bas", "bass"}:
                part.instrument_name = "Men"
                part.instrument_sound = "voice.male"
                part.is_vocal = True
                part.midi_program = 53
                return

        # Single part
        for key_name, (inst_name, inst_sound, _) in INSTRUMENT_MAP.items():
            if name_lower == key_name or name_lower.rstrip(".") == key_name.rstrip("."):
                part.part_name = inst_name  # normalize to full name
                part.instrument_name = inst_name
                part.instrument_sound = inst_sound
                part.is_vocal = "voice" in inst_sound
                if "organ" in inst_sound:
                    part.midi_program = 20  # Church Organ
                    part.abbreviation = "Org."
                elif "piano" in inst_sound:
                    part.midi_program = 1   # Acoustic Piano
                    part.abbreviation = "Pf."
                else:
                    part.midi_program = 53  # Voice
                return

        # Default
        part.instrument_name = part.part_name
        part.instrument_sound = "voice.female"

    def _abbreviate(self, name: str) -> str:
        """Create abbreviation from part name."""
        if not name:
            return ""
        parts = name.split("\n")
        if len(parts) > 1:
            return ".".join(p[0].upper() for p in parts if p) + "."
        if len(name) <= 4:
            return name
        return name[:3] + "."

    def _build_musicxml(
        self,
        parts_def: List[PartDefinition],
        parsed_parts: Dict[tuple, object],
        text_info: ClassifiedText,
        layout: StaffLayout,
    ) -> ET.Element:
        """Build complete MusicXML XML tree."""

        root = ET.Element("score-partwise", version="4.0")

        # --- Work/movement titles ---
        if text_info.title:
            work = ET.SubElement(root, "work")
            ET.SubElement(work, "work-title").text = text_info.title

        # --- Identification ---
        ident = ET.SubElement(root, "identification")
        if text_info.composer:
            ET.SubElement(ident, "creator", type="composer").text = text_info.composer
        if text_info.arranger:
            ET.SubElement(ident, "creator", type="arranger").text = text_info.arranger
        encoding = ET.SubElement(ident, "encoding")
        ET.SubElement(encoding, "software").text = "Church Music Organizer OMR"
        ET.SubElement(encoding, "encoding-date").text = "2025-07-26"

        # --- Part list ---
        part_list = ET.SubElement(root, "part-list")
        
        # Determine bracket groups
        vocal_parts = [p for p in parts_def if p.is_vocal and p.group_number > 0]
        if vocal_parts:
            group_num = vocal_parts[0].group_number
            pg_start = ET.SubElement(part_list, "part-group",
                                     type="start", number=str(group_num))
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
                ET.SubElement(si, "instrument-sound").text = pdef.instrument_sound

            # MIDI
            midi = ET.SubElement(sp, "midi-instrument", id=inst_id)
            ET.SubElement(midi, "midi-channel").text = str(i + 1)
            ET.SubElement(midi, "midi-program").text = str(pdef.midi_program)

            # Close bracket group after last vocal part
            if (pdef.is_vocal and pdef.group_number > 0 and
                    pdef == vocal_parts[-1]):
                ET.SubElement(part_list, "part-group",
                              type="stop", number=str(pdef.group_number))

        # --- Parts with measures ---
        for pdef in parts_def:
            part_el = ET.SubElement(root, "part", id=pdef.part_id)

            # Try to find matching OMR result
            key = tuple(pdef.staff_indices)
            omr_score = parsed_parts.get(key)

            if omr_score and list(omr_score.parts):
                self._fill_part_from_omr(part_el, pdef, omr_score, text_info)
            else:
                # No OMR data — create empty measures
                self._fill_empty_part(part_el, pdef, text_info)

        return root

    def _fill_part_from_omr(
        self,
        part_el: ET.Element,
        pdef: PartDefinition,
        omr_score,
        text_info: ClassifiedText,
    ):
        """Fill a part element with notes from OMR result."""
        omr_part = list(omr_score.parts)[0]
        measures = list(omr_part.getElementsByClass("Measure"))

        if not measures:
            self._fill_empty_part(part_el, pdef, text_info)
            return

        # Detect anacrusis: if first measure has fewer beats than expected
        first_measure_dur = measures[0].duration.quarterLength
        
        # Try to get time signature
        time_sigs = omr_part.flatten().getElementsByClass("TimeSignature")
        expected_beats = 4.0  # default 4/4
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
                ET.SubElement(attr_el, "divisions").text = str(self.DIVISIONS)

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
                    ET.SubElement(time_el, "beat-type").text = str(ts.denominator)
                else:
                    ET.SubElement(time_el, "beats").text = "4"
                    ET.SubElement(time_el, "beat-type").text = "4"

                # Staves
                if pdef.num_staves > 1:
                    ET.SubElement(attr_el, "staves").text = str(pdef.num_staves)

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
                        direction = ET.SubElement(measure_el, "direction",
                                                  placement="above")
                        dir_type = ET.SubElement(direction, "direction-type")
                        metro = ET.SubElement(dir_type, "metronome")
                        ET.SubElement(metro, "beat-unit").text = "quarter"
                        ET.SubElement(metro, "per-minute").text = bpm
                        sound = ET.SubElement(direction, "sound",
                                              tempo=bpm)

            # Write notes from OMR
            self._write_measure_notes(measure_el, m21_measure, pdef)

    def _write_measure_notes(self, measure_el: ET.Element, m21_measure, pdef):
        """Write notes from a music21 measure to MusicXML elements.

        For grand staff parts (num_staves > 1), uses offset-based layout
        with <backup> elements between staves so that beats aren't doubled.
        """
        if pdef.num_staves > 1:
            self._write_grand_staff_measure(measure_el, m21_measure, pdef)
        else:
            self._write_single_staff_measure(measure_el, m21_measure, pdef)

    # ------------------------------------------------------------------
    # Helpers: single-staff (simple sequential write)
    # ------------------------------------------------------------------

    def _write_single_staff_measure(self, measure_el, m21_measure, pdef):
        """Write notes for a single-staff part sequentially."""
        for elem in m21_measure.flatten().notesAndRests:
            if isinstance(elem, note.Rest):
                note_el = ET.SubElement(measure_el, "note")
                ET.SubElement(note_el, "rest")
                dur_ql = elem.duration.quarterLength
                ET.SubElement(note_el, "duration").text = str(self._ql_to_div(dur_ql))
                ET.SubElement(note_el, "type").text = self._dur_type(dur_ql)
                if dur_ql in (1.5, 3.0):
                    ET.SubElement(note_el, "dot")
            elif isinstance(elem, note.Note):
                self._write_single_note(measure_el, elem, pdef)
            elif isinstance(elem, chord.Chord):
                self._write_chord(measure_el, elem, pdef)

    # ------------------------------------------------------------------
    # Helpers: grand-staff (offset-based with <backup>)
    # ------------------------------------------------------------------

    def _write_grand_staff_measure(self, measure_el, m21_measure, pdef):
        """Write notes for a grand-staff part using backup elements.

        1. Classify every note/chord into staff 1 (treble) or staff 2 (bass).
        2. Within each staff, separate overlapping notes into voices.
        3. Write each voice sequentially with backup between them.
        """
        elements = list(m21_measure.flatten().notesAndRests)

        # ---- classify into staves ----
        staff1_raw = []  # (offset, duration, elem)
        staff2_raw = []

        for elem in elements:
            off = float(elem.offset)
            dur = float(elem.duration.quarterLength)
            if isinstance(elem, note.Rest):
                # Rests go to staff 1 by default
                staff1_raw.append((off, dur, elem))
            elif isinstance(elem, note.Note):
                bucket = (staff1_raw if elem.pitch.midi >= 60
                          else staff2_raw)
                bucket.append((off, dur, elem))
            elif isinstance(elem, chord.Chord):
                avg = sum(p.midi for p in elem.pitches) / len(
                    elem.pitches)
                bucket = (staff1_raw if avg >= 60
                          else staff2_raw)
                bucket.append((off, dur, elem))

        # Skip pure-rest staves when the other has real notes
        s1_real = any(not isinstance(e, note.Rest)
                      for _, _, e in staff1_raw)
        s2_real = any(not isinstance(e, note.Rest)
                      for _, _, e in staff2_raw)
        if not s1_real and s2_real:
            staff1_raw = []
        if not s2_real and s1_real:
            staff2_raw = []

        # ---- separate voices within each staff ----
        staff1_voices = self._separate_into_voices(staff1_raw)
        staff2_voices = self._separate_into_voices(staff2_raw)

        # ---- write all voices ----
        cursor = 0.0
        first_voice = True

        # Staff 1 voices: 1, 2, 3, ...
        for vi, voice_notes in enumerate(staff1_voices):
            voice_num = vi + 1
            if not first_voice:
                bk = ET.SubElement(measure_el, "backup")
                ET.SubElement(bk, "duration").text = str(
                    self._ql_to_div(cursor))
            end = self._write_voice_notes(
                measure_el, voice_notes, voice_num, 1)
            cursor = end
            first_voice = False

        # Staff 2 voices: 5, 6, 7, ...
        for vi, voice_notes in enumerate(staff2_voices):
            voice_num = vi + 5
            if not first_voice:
                bk = ET.SubElement(measure_el, "backup")
                ET.SubElement(bk, "duration").text = str(
                    self._ql_to_div(cursor))
            end = self._write_voice_notes(
                measure_el, voice_notes, voice_num, 2)
            cursor = end
            first_voice = False

    def _separate_into_voices(
        self, raw: List[Tuple[float, float, object]]
    ) -> List[List[Tuple[float, float, object]]]:
        """Separate overlapping notes into non-overlapping voices.

        Uses greedy interval scheduling: each note is placed into the
        first voice whose last note ended at or before this note's offset.
        Notes are processed in order of (offset, -duration) so longer
        notes are placed first.

        Returns list of voices, each a list of (offset, dur, elem).
        """
        if not raw:
            return []

        # Sort by offset, then longest duration first
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

    def _write_voice_notes(
        self,
        measure_el: ET.Element,
        notes: List[Tuple[float, float, object]],
        voice: int,
        staff_num: int,
    ) -> float:
        """Write a sequence of non-overlapping notes for one voice.

        Adds <forward> for gaps. Returns final cursor position.
        """
        cursor = 0.0
        for off, dur, elem in notes:
            # Insert forward for gaps
            if off > cursor + 0.001:
                gap = off - cursor
                fwd = ET.SubElement(measure_el, "forward")
                ET.SubElement(fwd, "duration").text = str(
                    self._ql_to_div(gap))
                ET.SubElement(fwd, "voice").text = str(voice)
                ET.SubElement(fwd, "staff").text = str(staff_num)
                cursor = off

            if isinstance(elem, note.Rest):
                note_el = ET.SubElement(measure_el, "note")
                ET.SubElement(note_el, "rest")
                ET.SubElement(note_el, "duration").text = str(
                    self._ql_to_div(dur))
                ET.SubElement(note_el, "voice").text = str(voice)
                ET.SubElement(note_el, "type").text = self._dur_type(dur)
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
                ET.SubElement(note_el, "duration").text = str(
                    self._ql_to_div(dur))
                ET.SubElement(note_el, "voice").text = str(voice)
                ET.SubElement(note_el, "type").text = self._dur_type(dur)
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
                        self._ql_to_div(dur))
                    ET.SubElement(note_el, "voice").text = str(voice)
                    ET.SubElement(note_el, "type").text = (
                        self._dur_type(dur))
                    if dur in (1.5, 3.0):
                        ET.SubElement(note_el, "dot")
                    ET.SubElement(note_el, "staff").text = str(staff_num)
                cursor += dur

        return cursor

    @staticmethod
    def _elem_dur(elem) -> float:
        """Get quarter-note duration from a music21 element."""
        return float(elem.duration.quarterLength)

    @staticmethod
    def _dur_type(dur_ql: float) -> str:
        """Map quarter-length to MusicXML type name."""
        MAP = {
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
        return MAP.get(dur_ql, "quarter")

    def _write_chord(self, measure_el, ch, pdef):
        """Write a chord to MusicXML."""
        for ci, p in enumerate(ch.pitches):
            note_el = ET.SubElement(measure_el, "note")
            if ci > 0:
                ET.SubElement(note_el, "chord")
            pitch_el = ET.SubElement(note_el, "pitch")
            ET.SubElement(pitch_el, "step").text = p.step
            if p.accidental and p.accidental.alter != 0:
                ET.SubElement(pitch_el, "alter").text = str(int(p.accidental.alter))
            ET.SubElement(pitch_el, "octave").text = str(p.octave)
            dur_ql = ch.duration.quarterLength
            ET.SubElement(note_el, "duration").text = str(self._ql_to_div(dur_ql))
            ET.SubElement(note_el, "type").text = self._dur_type(dur_ql)
            if dur_ql in (1.5, 3.0):
                ET.SubElement(note_el, "dot")

    def _write_single_note(self, measure_el: ET.Element, n: note.Note, pdef):
        """Write a single note to MusicXML (used for single-staff parts)."""
        note_el = ET.SubElement(measure_el, "note")

        pitch_el = ET.SubElement(note_el, "pitch")
        ET.SubElement(pitch_el, "step").text = n.pitch.step
        if n.pitch.accidental and n.pitch.accidental.alter != 0:
            ET.SubElement(pitch_el, "alter").text = str(int(n.pitch.accidental.alter))
        ET.SubElement(pitch_el, "octave").text = str(n.pitch.octave)

        dur_ql = n.duration.quarterLength
        ET.SubElement(note_el, "duration").text = str(self._ql_to_div(dur_ql))
        ET.SubElement(note_el, "type").text = self._dur_type(dur_ql)

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

    def _fill_empty_part(
        self,
        part_el: ET.Element,
        pdef: PartDefinition,
        text_info: ClassifiedText,
    ):
        """Fill a part with empty measures when no OMR data is available."""
        measure = ET.SubElement(part_el, "measure", number="1")
        
        attr_el = ET.SubElement(measure, "attributes")
        ET.SubElement(attr_el, "divisions").text = str(self.DIVISIONS)
        
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
        ET.SubElement(note_el, "duration").text = str(
            self._ql_to_div(4.0))
        ET.SubElement(note_el, "type").text = "whole"

    def build_from_single_omr(
        self,
        omr_musicxml_path: str,
        text_info: ClassifiedText,
        layout: StaffLayout,
        output_path: str,
    ) -> str:
        """Build a multi-part score from a SINGLE OMR result + layout info.

        When per-staff splitting was not possible or we want to restructure
        a single-part OMR result into the correct multi-part layout.

        This approach:
        1. Reads the monolithic OMR MusicXML
        2. Splits notes by pitch range into separate parts
        3. Applies correct metadata and part structure

        Args:
            omr_musicxml_path: Path to the single OMR MusicXML
            text_info: Classified text from PDF
            layout: Staff layout from detector
            output_path: Where to save

        Returns:
            Path to output MusicXML
        """
        # Determine parts from layout
        parts_def = self._determine_parts(layout, text_info)
        
        if not parts_def:
            logger.warning("Could not determine parts from layout")
            return omr_musicxml_path

        # Parse the monolithic OMR score
        try:
            omr_score = converter.parse(omr_musicxml_path)
        except Exception as e:
            logger.error(f"Could not parse OMR result: {e}")
            return omr_musicxml_path

        if not omr_score.parts:
            return omr_musicxml_path

        omr_part = omr_score.parts[0]

        # Build new score with split parts
        root = self._build_musicxml_from_split(parts_def, omr_part, text_info, layout)

        # Write
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        
        with open(str(output_path), "wb") as f:
            tree.write(f, encoding="UTF-8", xml_declaration=True)

        content = output_path.read_text(encoding="utf-8")
        if "<!DOCTYPE" not in content:
            content = content.replace(
                "<?xml version='1.0' encoding='UTF-8'?>",
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                '"http://www.musicxml.org/dtds/partwise.dtd">',
                1
            )
            output_path.write_text(content, encoding="utf-8")

        logger.info(f"Restructured score saved to {output_path}")
        return str(output_path)

    def _build_musicxml_from_split(
        self,
        parts_def: List[PartDefinition],
        omr_part,
        text_info: ClassifiedText,
        layout: StaffLayout,
    ) -> ET.Element:
        """Build multi-part MusicXML by splitting a single OMR part by pitch."""
        
        root = ET.Element("score-partwise", version="4.0")

        # Title & identification (same as build)
        if text_info.title:
            work = ET.SubElement(root, "work")
            ET.SubElement(work, "work-title").text = text_info.title

        ident = ET.SubElement(root, "identification")
        if text_info.composer:
            ET.SubElement(ident, "creator", type="composer").text = text_info.composer
        if text_info.arranger:
            ET.SubElement(ident, "creator", type="arranger").text = text_info.arranger
        encoding = ET.SubElement(ident, "encoding")
        ET.SubElement(encoding, "software").text = "Church Music Organizer OMR"

        # Part list
        part_list = ET.SubElement(root, "part-list")
        
        vocal_parts = [p for p in parts_def if p.is_vocal and p.group_number > 0]
        if vocal_parts:
            pg = ET.SubElement(part_list, "part-group",
                               type="start", number="1")
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
                ET.SubElement(si, "instrument-sound").text = pdef.instrument_sound

            midi = ET.SubElement(sp, "midi-instrument", id=inst_id)
            ET.SubElement(midi, "midi-channel").text = str(i + 1)
            ET.SubElement(midi, "midi-program").text = str(pdef.midi_program)

            if pdef.is_vocal and pdef.group_number > 0 and pdef == vocal_parts[-1]:
                ET.SubElement(part_list, "part-group", type="stop", number="1")

        # Get measures from OMR
        omr_measures = list(omr_part.getElementsByClass("Measure"))

        # For each part definition, create a part with notes filtered by pitch
        for pdef in parts_def:
            part_el = ET.SubElement(root, "part", id=pdef.part_id)
            
            # Determine pitch range for this part
            pitch_range = self._get_pitch_range_for_part(pdef, parts_def)

            for m_idx, m21_m in enumerate(omr_measures):
                m_num = m_idx + 1
                measure_el = ET.SubElement(part_el, "measure", number=str(m_num))

                # First measure: attributes
                if m_idx == 0:
                    self._write_first_measure_attrs(
                        measure_el, pdef, omr_part, text_info
                    )

                # Filter notes by pitch range
                self._write_filtered_notes(
                    measure_el, m21_m, pdef, pitch_range
                )

        return root

    def _get_pitch_range_for_part(
        self,
        pdef: PartDefinition,
        all_parts: List[PartDefinition],
    ) -> Tuple[int, int]:
        """Get the MIDI pitch range for note assignment to this part."""
        name_lower = pdef.part_name.lower().replace("\n", " ")

        # Standard ranges
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

    def _write_first_measure_attrs(
        self,
        measure_el: ET.Element,
        pdef: PartDefinition,
        omr_part,
        text_info: ClassifiedText,
    ):
        """Write first-measure attributes for a part."""
        attr_el = ET.SubElement(measure_el, "attributes")
        ET.SubElement(attr_el, "divisions").text = str(self.DIVISIONS)

        key_el = ET.SubElement(attr_el, "key")
        keys = omr_part.flatten().getElementsByClass("KeySignature")
        fifths = keys[0].sharps if keys else 0
        ET.SubElement(key_el, "fifths").text = str(fifths)

        time_el = ET.SubElement(attr_el, "time")
        time_sigs = omr_part.flatten().getElementsByClass("TimeSignature")
        if time_sigs:
            ET.SubElement(time_el, "beats").text = str(time_sigs[0].numerator)
            ET.SubElement(time_el, "beat-type").text = str(time_sigs[0].denominator)
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
            tempo_match = re.search(r"(\d+)", text_info.tempo_markings[0]["text"])
            if tempo_match:
                bpm = tempo_match.group(1)
                direction = ET.SubElement(measure_el, "direction", placement="above")
                dir_type = ET.SubElement(direction, "direction-type")
                metro = ET.SubElement(dir_type, "metronome")
                ET.SubElement(metro, "beat-unit").text = "quarter"
                ET.SubElement(metro, "per-minute").text = bpm
                ET.SubElement(direction, "sound", tempo=bpm)

    def _write_filtered_notes(
        self,
        measure_el: ET.Element,
        m21_measure,
        pdef: PartDefinition,
        pitch_range: Tuple[int, int],
    ):
        """Write notes from a measure, filtered by pitch range."""
        DURATION_MAP = {
            0.25: "16th",
            0.5: "eighth",
            1.0: "quarter",
            1.5: "quarter",
            2.0: "half",
            3.0: "half",
            4.0: "whole",
        }

        has_notes = False
        for elem in m21_measure.flatten().notesAndRests:
            if isinstance(elem, note.Rest):
                note_el = ET.SubElement(measure_el, "note")
                ET.SubElement(note_el, "rest")
                dur = self._ql_to_div(elem.duration.quarterLength)
                ET.SubElement(note_el, "duration").text = str(dur)
                dur_name = DURATION_MAP.get(elem.duration.quarterLength, "quarter")
                ET.SubElement(note_el, "type").text = dur_name
                has_notes = True

            elif isinstance(elem, note.Note):
                if pitch_range[0] <= elem.pitch.midi <= pitch_range[1]:
                    self._write_single_note(measure_el, elem, pdef)
                    has_notes = True

            elif isinstance(elem, chord.Chord):
                # Filter chord pitches by range
                matching = [p for p in elem.pitches
                           if pitch_range[0] <= p.midi <= pitch_range[1]]
                if matching:
                    for ci, p in enumerate(matching):
                        note_el = ET.SubElement(measure_el, "note")
                        if ci > 0:
                            ET.SubElement(note_el, "chord")
                        
                        pitch_el = ET.SubElement(note_el, "pitch")
                        ET.SubElement(pitch_el, "step").text = p.step
                        if p.accidental and p.accidental.alter != 0:
                            ET.SubElement(pitch_el, "alter").text = str(int(p.accidental.alter))
                        ET.SubElement(pitch_el, "octave").text = str(p.octave)
                        
                        dur = self._ql_to_div(elem.duration.quarterLength)
                        ET.SubElement(note_el, "duration").text = str(dur)
                        dur_name = DURATION_MAP.get(elem.duration.quarterLength, "quarter")
                        ET.SubElement(note_el, "type").text = dur_name

                        if pdef.num_staves > 1:
                            staff_num = 1 if p.midi >= 60 else 2
                            ET.SubElement(note_el, "staff").text = str(staff_num)
                    has_notes = True

        if not has_notes:
            # Add a whole rest if no notes passed the filter
            note_el = ET.SubElement(measure_el, "note")
            ET.SubElement(note_el, "rest", measure="yes")
            ET.SubElement(note_el, "duration").text = str(
                self._ql_to_div(4.0))
            ET.SubElement(note_el, "type").text = "whole"
