"""Part definition — data structures and logic for determining score parts.

Extracts part structure from staff layout and text metadata:
- PartDefinition dataclass for part configuration
- INSTRUMENT_MAP for mapping part names to instruments
- Functions for determining, naming, and assigning instruments to parts
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .staff_detector import StaffLayout
from .text_classifier import ClassifiedText

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
    staff_indices: List[int] = field(default_factory=list)
    is_vocal: bool = True
    group_type: str = "none"   # "bracket", "brace", "none"
    group_number: int = 0      # for part-group start/stop


def abbreviate(name: str) -> str:
    """Create abbreviation from part name.

    Args:
        name: Full part name, may contain newlines for multi-voice parts.

    Returns:
        Abbreviated form (e.g. "S.A.", "Org.", "T.B.").
    """
    if not name:
        return ""
    parts = name.split("\n")
    if len(parts) > 1:
        return ".".join(p[0].upper() for p in parts if p) + "."
    if len(name) <= 4:
        return name
    return name[:3] + "."


def assign_instrument(part: PartDefinition) -> None:
    """Assign instrument name and MIDI info based on part name.

    Modifies the PartDefinition in place with instrument_name,
    instrument_sound, midi_program, and other fields.

    Args:
        part: PartDefinition to update.
    """
    name_lower = part.part_name.lower().replace("\n", " ").strip()

    # Check for combined vocal parts like "S\nA" or "T\nB"
    name_parts = [
        p.strip().lower().rstrip(".") for p in part.part_name.split("\n")
    ]

    if len(name_parts) == 2:
        if set(name_parts) <= {"s", "a", "soprano", "alt", "sopran"}:
            part.instrument_name = "Women"
            part.instrument_sound = "voice.female"
            part.is_vocal = True
            part.midi_program = 53  # Voice Oohs
            return
        elif set(name_parts) <= {"t", "b", "tenor", "bas", "bass"}:
            part.instrument_name = "Men"
            part.instrument_sound = "voice.male"
            part.is_vocal = True
            part.midi_program = 53
            return

    # Single part — match against INSTRUMENT_MAP
    for key_name, (inst_name, inst_sound, _) in INSTRUMENT_MAP.items():
        if (name_lower == key_name
                or name_lower.rstrip(".") == key_name.rstrip(".")):
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


def find_part_name(
    staff_indices: List[int],
    part_names: List[Dict],
    layout: StaffLayout,
) -> str:
    """Find the part name label closest to the given staff indices.

    Uses RELATIVE y positions because text coords (PDF points @ 72 DPI)
    and staff coords (image pixels @ 300 DPI) are in different units.

    Args:
        staff_indices: Staff indices to match.
        part_names: List of {"name": str, "y": float, "rel_y": float}.
        layout: Staff layout with stave positions.

    Returns:
        Part name string (may contain newlines for multi-voice parts).
    """
    if not part_names or not layout.staves or not layout.image_height:
        return ""

    target_staves = [s for s in layout.staves if s.index in staff_indices]
    if not target_staves:
        return ""

    # Compute relative y range for this staff in image coordinates
    rel_y_top = min(s.y_top for s in target_staves) / layout.image_height
    rel_y_bottom = (
        max(s.y_bottom for s in target_staves) / layout.image_height
    )

    # Search with a generous margin (text labels are offset from staff)
    for margin in (0.04, 0.08):
        search_top = rel_y_top - margin
        search_bottom = rel_y_bottom + margin

        matching = []
        for pn in part_names:
            pn_rel_y = pn.get("rel_y", 0)
            if search_top <= pn_rel_y <= search_bottom:
                matching.append(pn["name"])

        if matching:
            if len(matching) == 1:
                return matching[0]
            return "\n".join(matching)

    return ""


def merge_vocal_parts(
    parts: List[PartDefinition],
    part_names: List[Dict],
    layout: StaffLayout,
) -> List[PartDefinition]:
    """Merge vocal parts that share a staff.

    In SATB scores, S and A are often on the same treble staff,
    T and B on the same bass staff. The text labels tell us if
    a single staff has two voice names.

    Args:
        parts: List of PartDefinitions to potentially merge.
        part_names: Text-classified part name labels.
        layout: Staff layout.

    Returns:
        Updated list of PartDefinitions.
    """
    # Already handled by find_part_name returning "S\nA"
    return parts


def determine_parts(
    layout: StaffLayout,
    text_info: ClassifiedText,
) -> List[PartDefinition]:
    """Determine part structure from staff layout and text metadata.

    Uses the number of staves per system, staff groups, and part labels
    to define the score's part structure.

    Args:
        layout: Staff layout from StaffDetector.
        text_info: Classified text from PDF (title, composer, part names).

    Returns:
        List of PartDefinitions describing the score's parts.
    """
    parts: List[PartDefinition] = []

    if not layout.systems:
        return parts

    first_system = layout.systems[0]
    staves_in_system = first_system.staff_indices
    n_staves = len(staves_in_system)

    # Get sorted part names from text_info (sorted by y position)
    part_names = sorted(
        text_info.part_names, key=lambda p: p.get("y", 0)
    )

    # Find brace groups (grand staff = organ/piano)
    brace_staves: set = set()
    brace_groups = []
    for g in layout.groups:
        if g.group_type == "brace":
            for idx in g.staff_indices:
                brace_staves.add(idx)
            brace_groups.append(g)

    # Build parts: single staves become individual parts,
    # brace pairs become grand-staff parts
    processed: set = set()
    part_idx = 1
    vocal_parts: List[PartDefinition] = []
    bracket_group_num = 1

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
            part_name = find_part_name(brace_indices, part_names, layout)

            part_def = PartDefinition(
                part_id=f"P{part_idx}",
                part_name=part_name or "Organo",
                abbreviation=abbreviate(part_name or "Org."),
                num_staves=len(brace_indices),
                clefs=["G", "F"],  # typical grand staff
                staff_indices=brace_indices,
                is_vocal=False,
                group_type="brace",
            )
            assign_instrument(part_def)
            parts.append(part_def)

            for si in brace_indices:
                processed.add(si)
            part_idx += 1
        else:
            # Single staff
            part_name = find_part_name([staff_idx], part_names, layout)

            part_def = PartDefinition(
                part_id=f"P{part_idx}",
                part_name=part_name or f"Part {part_idx}",
                abbreviation=abbreviate(part_name or ""),
                num_staves=1,
                staff_indices=[staff_idx],
                is_vocal=True,
            )

            # Determine clef from position
            non_brace_staves = [
                s for s in staves_in_system if s not in brace_staves
            ]
            if non_brace_staves and staff_idx in non_brace_staves:
                mid = len(non_brace_staves) // 2
                if non_brace_staves.index(staff_idx) < mid:
                    part_def.clefs = ["G"]
                else:
                    part_def.clefs = ["F"]
            else:
                part_def.clefs = ["G"]

            assign_instrument(part_def)
            vocal_parts.append(part_def)
            parts.append(part_def)
            processed.add(staff_idx)
            part_idx += 1

    # If there are multiple vocal parts, they need a bracket group
    if len(vocal_parts) >= 2:
        for vp in vocal_parts:
            vp.group_number = bracket_group_num

    # Check if we can merge vocal parts that share a staff
    parts = merge_vocal_parts(parts, part_names, layout)

    return parts
