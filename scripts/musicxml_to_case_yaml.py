#!/usr/bin/env python3
"""
Convert expected_final.musicxml → case.yaml

Usage:
    python scripts/musicxml_to_case_yaml.py tests/fixtures/do_Jana_Kantego/expected_final.musicxml
    python scripts/musicxml_to_case_yaml.py tests/fixtures/do_Jana_Kantego/expected_final.musicxml --output case.yaml
    python scripts/musicxml_to_case_yaml.py tests/fixtures/do_Jana_Kantego/  # auto-finds expected_final.musicxml

Generates a case.yaml file with ground truth values extracted from a MusicXML file.
Some fields (step_01, step_02, difficulty, tags, notes) require manual review.
"""

import argparse
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# YAML helpers — preserve nice formatting
# ---------------------------------------------------------------------------

class _LiteralStr(str):
    """Tag a string so PyYAML dumps it as a literal block scalar."""


def _literal_representer(dumper: yaml.Dumper, data: str) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_LiteralStr, _literal_representer)


def _none_representer(dumper: yaml.Dumper, _data: Any) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


yaml.add_representer(type(None), _none_representer)


# ---------------------------------------------------------------------------
# MusicXML parsing helpers
# ---------------------------------------------------------------------------

def _pitch_to_midi(pitch_el: ET.Element) -> int:
    """Convert a MusicXML <pitch> element to MIDI note number."""
    step = pitch_el.findtext("step", "C")
    octave = int(pitch_el.findtext("octave", "4"))
    alter = int(float(pitch_el.findtext("alter", "0")))
    step_map = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return 12 * (octave + 1) + step_map.get(step, 0) + alter


def _clef_label(clef_el: ET.Element) -> str:
    """Return human-readable clef label like 'G' or 'F'."""
    sign = clef_el.findtext("sign", "G")
    return sign


def _key_fifths_to_label(fifths: int) -> str:
    """Convert key fifths to human-readable label, e.g. -1 → 'F major / D minor'."""
    major_keys = {
        -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb", -1: "F",
        0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
    }
    return f"{major_keys.get(fifths, '?')} major"


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

class MusicXMLExtractor:
    """Extract ground-truth data from a MusicXML file for case.yaml."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tree = ET.parse(str(path))
        self.root = self.tree.getroot()

    # -- metadata ----------------------------------------------------------

    def extract_title(self) -> str | None:
        """Title from <credit> or <work-title>."""
        for credit in self.root.findall("credit"):
            ctype = credit.findtext("credit-type", "")
            if ctype == "title":
                words = credit.findtext("credit-words", "").strip()
                if words:
                    return words
        wt = self.root.findtext("work/work-title")
        return wt.strip() if wt else None

    def extract_subtitle(self) -> str | None:
        for credit in self.root.findall("credit"):
            ctype = credit.findtext("credit-type", "")
            if ctype == "subtitle":
                parts = []
                for cw in credit.findall("credit-words"):
                    t = (cw.text or "").strip()
                    if t:
                        parts.append(t)
                return " ".join(parts) if parts else None
        misc = self.root.find("identification/miscellaneous")
        if misc is not None:
            for mf in misc.findall("miscellaneous-field"):
                if mf.get("name") == "subtitle":
                    return (mf.text or "").strip() or None
        return None

    def extract_composer(self) -> str | None:
        for credit in self.root.findall("credit"):
            ctype = credit.findtext("credit-type", "")
            if ctype == "composer":
                return credit.findtext("credit-words", "").strip() or None
        return (self.root.findtext("identification/creator[@type='composer']") or "").strip() or None

    def extract_arranger(self) -> str | None:
        return (self.root.findtext("identification/creator[@type='arranger']") or "").strip() or None

    # -- parts & staves ---------------------------------------------------

    def extract_parts_info(self) -> list[dict]:
        """Return list of part dicts with id, name, abbreviation."""
        parts = []
        for sp in self.root.findall("part-list/score-part"):
            # Normalize whitespace in part names (MusicXML may have newlines)
            raw_name = sp.findtext("part-name", "")
            name = " ".join(raw_name.split())
            raw_abbr = sp.findtext("part-abbreviation", "")
            abbreviation = " ".join(raw_abbr.split())
            parts.append({
                "id": sp.get("id"),
                "name": name,
                "abbreviation": abbreviation,
            })
        return parts

    def _get_part_element(self, part_id: str) -> ET.Element | None:
        for p in self.root.findall("part"):
            if p.get("id") == part_id:
                return p
        return None

    # -- per-part analysis -------------------------------------------------

    def analyze_part(self, part_id: str) -> dict:
        """Analyze a single part: measures, clefs, key, time, notes, voices, staves, pitch range, lyrics."""
        part_el = self._get_part_element(part_id)
        if part_el is None:
            return {}

        measures = part_el.findall("measure")
        total_measures = len(measures)

        # First measure attributes
        first_attrs = measures[0].find("attributes") if measures else None

        # Divisions
        divisions = int(first_attrs.findtext("divisions", "1")) if first_attrs is not None else 1

        # Staves count
        staves_count = int(first_attrs.findtext("staves", "1")) if first_attrs is not None else 1

        # Clefs
        clefs = []
        if first_attrs is not None:
            for clef_el in first_attrs.findall("clef"):
                clefs.append(_clef_label(clef_el))
        if not clefs:
            clefs = ["G"]

        # Key signature (fifths)
        key_fifths = 0
        if first_attrs is not None:
            key_el = first_attrs.find("key")
            if key_el is not None:
                key_fifths = int(key_el.findtext("fifths", "0"))

        # Time signature
        time_beats = "4"
        time_beat_type = "4"
        time_symbol = None
        if first_attrs is not None:
            time_el = first_attrs.find("time")
            if time_el is not None:
                time_beats = time_el.findtext("beats", "4")
                time_beat_type = time_el.findtext("beat-type", "4")
                time_symbol = time_el.get("symbol")

        # Check for time/key changes mid-piece
        key_changes = []
        time_changes = []
        for m in measures:
            m_num = m.get("number", "?")
            attrs = m.find("attributes")
            if attrs is not None:
                k = attrs.find("key")
                if k is not None:
                    f = int(k.findtext("fifths", "0"))
                    if f != key_fifths or m_num != measures[0].get("number"):
                        key_changes.append({"measure": int(m_num), "fifths": f})
                t = attrs.find("time")
                if t is not None:
                    b = t.findtext("beats", "4")
                    bt = t.findtext("beat-type", "4")
                    ts = f"{b}/{bt}"
                    initial_ts = f"{time_beats}/{time_beat_type}"
                    if ts != initial_ts or m_num != measures[0].get("number"):
                        time_changes.append({"measure": int(m_num), "time": ts})

        # Notes analysis
        midi_pitches: list[int] = []
        note_count = 0
        rest_count = 0
        voices_seen: set[str] = set()
        staves_seen: set[str] = set()
        has_lyrics = False
        lyric_numbers: set[str] = set()
        lyric_syllables_v1: list[str] = []  # first verse only
        has_ties = False
        has_chords = False
        has_dots = False

        for m in measures:
            for note in m.findall("note"):
                voice = note.findtext("voice", "1")
                staff = note.findtext("staff", "1")
                voices_seen.add(voice)
                staves_seen.add(staff)

                if note.find("rest") is not None:
                    rest_count += 1
                    continue

                # Skip grace notes for counting
                if note.find("grace") is not None:
                    continue

                note_count += 1

                pitch = note.find("pitch")
                if pitch is not None:
                    midi_pitches.append(_pitch_to_midi(pitch))

                if note.find("dot") is not None:
                    has_dots = True

                if note.find("chord") is not None:
                    has_chords = True

                for tie in note.findall("tie"):
                    has_ties = True

                for lyric in note.findall("lyric"):
                    has_lyrics = True
                    num = lyric.get("number", "1")
                    lyric_numbers.add(num)
                    if num == "1":
                        text = lyric.findtext("text", "").strip()
                        # Remove verse number prefix like "1. "
                        if text and len(text) > 3 and text[0].isdigit() and text[1] == '.':
                            text = text[2:].strip()
                        if text:
                            lyric_syllables_v1.append(text)

        pitch_range = [min(midi_pitches), max(midi_pitches)] if midi_pitches else [0, 0]

        # Systems and pages detection
        pages: list[dict] = []
        current_page = 1
        current_system = 1
        page_measures: dict[int, list[int]] = defaultdict(list)
        system_info: list[dict] = []

        for m in measures:
            m_num = int(m.get("number", "0"))
            print_el = m.find("print")
            if print_el is not None:
                if print_el.get("new-page") == "yes":
                    current_page += 1
                    current_system += 1
                elif print_el.get("new-system") == "yes":
                    current_system += 1
            page_measures[current_page].append(m_num)

        total_pages = max(page_measures.keys()) if page_measures else 1

        # Beats per measure calculation
        beats_per_measure = float(time_beats)
        beat_type_val = float(time_beat_type)
        # Standardize to quarter-note beats
        beats_in_quarters = beats_per_measure * (4.0 / beat_type_val)

        # Barline types
        final_barline = None
        repeat_barlines = []
        for m in measures:
            m_num = m.get("number", "?")
            for barline in m.findall("barline"):
                bar_style = barline.findtext("bar-style", "")
                repeat = barline.find("repeat")
                loc = barline.get("location", "right")
                if bar_style == "light-heavy" and loc == "right":
                    final_barline = int(m_num)
                if repeat is not None:
                    repeat_barlines.append({
                        "measure": int(m_num),
                        "direction": repeat.get("direction", ""),
                        "location": loc,
                    })

        # Direction/text annotations
        directions: list[dict] = []
        for m in measures:
            m_num = m.get("number", "?")
            for direction in m.findall("direction"):
                for dt in direction.findall("direction-type"):
                    words_el = dt.find("words")
                    if words_el is not None and words_el.text:
                        text = words_el.text.strip()
                        if text:
                            directions.append({"measure": int(m_num), "text": text})

        return {
            "total_measures": total_measures,
            "divisions": divisions,
            "staves_count": staves_count,
            "clefs": clefs if len(clefs) > 1 else clefs[0],
            "key_fifths": key_fifths,
            "key_label": _key_fifths_to_label(key_fifths),
            "time_signature": f"{time_beats}/{time_beat_type}",
            "time_symbol": time_symbol,
            "note_count": note_count,
            "rest_count": rest_count,
            "voices": sorted(voices_seen),
            "staves_used": sorted(staves_seen),
            "pitch_range_midi": pitch_range,
            "has_lyrics": has_lyrics,
            "lyric_verse_count": len(lyric_numbers),
            "lyric_syllables_v1_snippet": " ".join(lyric_syllables_v1[:10]),
            "total_lyric_syllables_v1": len(lyric_syllables_v1),
            "has_ties": has_ties,
            "has_chords": has_chords,
            "has_dots": has_dots,
            "total_pages": total_pages,
            "beats_per_measure": beats_in_quarters,
            "key_changes": key_changes if len(key_changes) > 1 else [],
            "time_changes": time_changes if len(time_changes) > 1 else [],
            "final_barline_measure": final_barline,
            "repeat_barlines": repeat_barlines,
            "directions": directions,
        }

    # -- grouping info (brackets, braces) ----------------------------------

    def extract_grouping(self) -> list[dict]:
        """Extract part-group info from <part-list>."""
        groups: list[dict] = []
        part_list = self.root.find("part-list")
        if part_list is None:
            return groups

        active_groups: dict[str, dict] = {}
        current_parts: dict[str, list[str]] = {}
        part_order: list[str] = []

        for el in part_list:
            if el.tag == "part-group":
                grp_num = el.get("number", "1")
                grp_type = el.get("type", "")
                if grp_type == "start":
                    symbol = el.findtext("group-symbol", "bracket")
                    active_groups[grp_num] = {"type": symbol}
                    current_parts[grp_num] = []
                elif grp_type == "stop" and grp_num in active_groups:
                    groups.append({
                        "type": active_groups[grp_num]["type"],
                        "parts": current_parts[grp_num],
                    })
                    del active_groups[grp_num]
                    del current_parts[grp_num]
            elif el.tag == "score-part":
                pid = el.get("id", "")
                raw_pname = el.findtext("part-name", pid)
                pname = " ".join(raw_pname.split())  # normalize whitespace
                part_order.append(pname)
                for grp_num in current_parts:
                    current_parts[grp_num].append(pname)

        return groups

    # -- page / system layout analysis -------------------------------------

    def extract_layout(self) -> list[dict]:
        """Determine pages and systems from <print> elements across all parts."""
        # Use the first part for layout info (all parts share the same measures)
        parts = self.root.findall("part")
        if not parts:
            return []

        part_el = parts[0]
        measures = part_el.findall("measure")

        pages_info: list[dict] = []
        current_page = 1
        current_system_on_page = 1
        page_start_measure = 1

        for m in measures:
            m_num = int(m.get("number", "0"))
            print_el = m.find("print")
            if print_el is not None:
                if print_el.get("new-page") == "yes":
                    # Close previous page
                    pages_info.append({
                        "page": current_page,
                        "systems": current_system_on_page,
                        "first_measure": page_start_measure,
                        "last_measure": m_num - 1,
                    })
                    current_page += 1
                    current_system_on_page = 1
                    page_start_measure = m_num
                elif print_el.get("new-system") == "yes":
                    current_system_on_page += 1

        # Close last page
        last_measure = int(measures[-1].get("number", "0")) if measures else 0
        pages_info.append({
            "page": current_page,
            "systems": current_system_on_page,
            "first_measure": page_start_measure,
            "last_measure": last_measure,
        })

        return pages_info


# ---------------------------------------------------------------------------
# case.yaml builder
# ---------------------------------------------------------------------------

def build_case_yaml(extractor: MusicXMLExtractor, fixture_dir: Path) -> dict:
    """Build a case.yaml dict from extracted MusicXML data."""
    parts_info = extractor.extract_parts_info()
    grouping = extractor.extract_grouping()
    layout = extractor.extract_layout()

    # Analyze each part
    part_analyses = {}
    for pi in parts_info:
        part_analyses[pi["id"]] = extractor.analyze_part(pi["id"])

    # Global values from first part (or merged)
    first_analysis = list(part_analyses.values())[0] if part_analyses else {}
    total_measures = first_analysis.get("total_measures", 0)
    total_pages = first_analysis.get("total_pages", 1)

    title = extractor.extract_title() or ""
    subtitle = extractor.extract_subtitle()
    composer = extractor.extract_composer()
    arranger = extractor.extract_arranger()

    # Detect source file
    source_file = "input.pdf"
    if (fixture_dir / "input.png").exists():
        source_file = "input.png"

    # Derive case id from directory name
    case_id = fixture_dir.name.lower().replace(" ", "_")

    # Determine part names list
    part_names = [pi["name"] for pi in parts_info]

    # Determine vocal vs non-vocal parts (based on lyrics presence)
    vocal_parts = []
    non_vocal_parts = []
    for pi in parts_info:
        analysis = part_analyses[pi["id"]]
        if analysis.get("has_lyrics"):
            vocal_parts.append(pi["name"])
        else:
            non_vocal_parts.append(pi["name"])

    # Total syllable count across all vocal parts
    total_syllables = sum(
        part_analyses[pi["id"]].get("total_lyric_syllables_v1", 0)
        for pi in parts_info
    )

    # Time signature from first part
    time_sig = first_analysis.get("time_signature", "4/4")
    beats_per_measure = first_analysis.get("beats_per_measure", 4.0)

    # Determine staves per part for step_06
    staves_info = []
    for pi in parts_info:
        a = part_analyses[pi["id"]]
        clefs = a.get("clefs", "G")
        note_count = a.get("note_count", 0)
        pitch_range = a.get("pitch_range_midi", [0, 0])

        staff_entry = {
            "label": pi["name"],
            "clef": clefs,
            "key_signature": a.get("key_fifths", 0),
            "time_signature": a.get("time_signature", "4/4"),
            "expected_measures": a.get("total_measures", 0),
            "expected_note_count": [int(note_count * 0.9), int(note_count * 1.1)],
            "pitch_range_midi": pitch_range,
        }

        # Extra info
        if a.get("lyric_verse_count", 0) > 0:
            staff_entry["lyric_verses"] = a["lyric_verse_count"]
        if a.get("has_ties"):
            staff_entry["has_ties"] = True
        if a.get("staves_count", 1) > 1:
            staff_entry["staves_in_part"] = a["staves_count"]
            staff_entry["voices"] = a.get("voices", [])

        staves_info.append(staff_entry)

    # Build staff groups for step_04_layout
    # Determine staff count per page from part staves
    total_staves_per_system = sum(
        part_analyses[pi["id"]].get("staves_count", 1)
        for pi in parts_info
    )

    # Layout pages
    page_layouts = []
    for pg in layout:
        groups_for_page = []
        # Groups are the same on every page, derived from part-list grouping
        for grp in grouping:
            groups_for_page.append({
                "type": grp["type"],
                "parts": grp["parts"],
            })

        page_layouts.append({
            "page": pg["page"],
            "staff_count": total_staves_per_system,
            "groups": groups_for_page,
            "systems": pg["systems"],
            "measures": f"{pg['first_measure']}-{pg['last_measure']}",
        })

    # Detect key/time changes for notes
    key_changes = first_analysis.get("key_changes", [])
    time_changes = first_analysis.get("time_changes", [])
    repeat_barlines = first_analysis.get("repeat_barlines", [])
    directions = first_analysis.get("directions", [])

    # Determine difficulty heuristically
    difficulty = "easy"
    if total_pages > 1:
        difficulty = "medium"
    if total_measures > 20:
        difficulty = "medium"
    if total_pages > 2 or total_measures > 40:
        difficulty = "hard"
    if len(parts_info) > 3 or len(key_changes) > 0:
        difficulty = "hard"

    # Tags
    tags = []
    if len(parts_info) == 1 and first_analysis.get("staves_count", 1) >= 2:
        tags.append("organ")
    for pi in parts_info:
        name_lower = pi["name"].lower()
        if any(v in name_lower for v in ["organo", "org"]):
            if "organ" not in tags:
                tags.append("organ")
        if any(v in name_lower for v in ["s a", "s", "soprano", "sopran"]):
            if "satb" not in tags:
                tags.append("satb")
    if total_pages > 1:
        tags.append("multi_page")
    if any(a.get("has_lyrics") for a in part_analyses.values()):
        tags.append("polish_text")
    if repeat_barlines:
        tags.append("repeat")
    if key_changes:
        tags.append("key_change")
    if time_changes:
        tags.append("time_change")

    # Build notes string
    notes_parts = []
    for pi in parts_info:
        a = part_analyses[pi["id"]]
        clefs_val = a.get("clefs", "G")
        if isinstance(clefs_val, list):
            clefs_str = "/".join(clefs_val)
        else:
            clefs_str = clefs_val
        staves_str = f", {a['staves_count']} staves" if a.get("staves_count", 1) > 1 else ""
        notes_parts.append(f"{pi['name']} ({clefs_str}{staves_str})")
    notes = f"{' + '.join(notes_parts)}, {total_pages} page(s), {total_measures} measures"

    # Lyrics snippet from first vocal part
    lyrics_snippet = ""
    for pi in parts_info:
        a = part_analyses[pi["id"]]
        if a.get("has_lyrics"):
            lyrics_snippet = a.get("lyric_syllables_v1_snippet", "")
            break

    # --- Assemble YAML dict ---
    case = {
        "id": case_id,
        "title": title,
        "source": source_file,
        "difficulty": difficulty,
        "tags": tags,
        "notes": notes,
    }

    # Step 01: Ingestion
    case["step_01_ingestion"] = {
        "expected_pages": total_pages,
        "expected_dpi": 300,
        "has_text_layer": source_file.endswith(".pdf"),
    }

    # Step 02: Preprocessing
    case["step_02_preprocessing"] = {
        "expected_pages": total_pages,
    }

    # Step 03: Text Classification
    case["step_03_text"] = {
        "title": title,
        "subtitle": subtitle,
        "composer": composer,
        "arranger": arranger,
        "part_names": part_names,
        "has_lyrics": any(a.get("has_lyrics") for a in part_analyses.values()),
        "lyrics_snippet": lyrics_snippet,
        "tempo": None,
    }

    # Step 04: Staff Detection / Layout
    case["step_04_layout"] = {
        "pages": page_layouts,
    }

    # Step 05: Staff Splitting
    # Determine splits from grouping
    splits = []
    if grouping:
        for grp in grouping:
            splits.append({
                "group_type": grp["type"],
                "parts": grp["parts"],
            })
    else:
        # No grouping — each part is its own split
        for pi in parts_info:
            a = part_analyses[pi["id"]]
            staff_indices = list(range(a.get("staves_count", 1)))
            splits.append({
                "group_type": "brace" if a.get("staves_count", 1) > 1 else "single",
                "parts": [pi["name"]],
            })

    case["step_05_splitting"] = {
        "expected_images": len(splits),
        "splits": splits,
    }

    # Step 06: OMR per Staff
    case["step_06_omr"] = {
        "staves": staves_info,
    }

    # Step 07: Score Assembly
    case["step_07_assembly"] = {
        "expected_parts": len(parts_info),
        "part_names": part_names,
        "grouping": [{
            "type": g["type"],
            "parts": g["parts"],
        } for g in grouping] if grouping else [],
        "total_measures": total_measures,
        "beats_per_measure": beats_per_measure,
    }

    # Add key/time change info if present
    if key_changes:
        case["step_07_assembly"]["key_changes"] = key_changes
    if time_changes:
        case["step_07_assembly"]["time_changes"] = time_changes
    if repeat_barlines:
        case["step_07_assembly"]["repeat_barlines"] = repeat_barlines

    # Step 08: Lyrics
    case["step_08_lyrics"] = {
        "vocal_parts": vocal_parts,
        "non_vocal_parts": non_vocal_parts,
        "expected_syllable_count": [int(total_syllables * 0.8), int(total_syllables * 1.2)] if total_syllables else [0, 0],
    }

    # Step 09: Validation
    case["step_09_validation"] = {
        "max_beat_errors": 0,
        "max_ambitus_warnings": 5,
        "expected_key_consistency": len(key_changes) <= 1,
        "expected_part_length_match": True,
    }

    # Step 10: Final Output
    case["step_10_final"] = {
        "ground_truth_file": "expected_final.musicxml",
        "min_pitch_accuracy": 0.80,
        "min_duration_accuracy": 0.80,
        "min_measure_count_accuracy": 1.0,
        "min_part_count_accuracy": 1.0,
    }

    # Sections — additional detail for human review
    # Include per-part detailed analysis as comments
    case["_extracted_details"] = {
        "per_part": {},
    }
    for pi in parts_info:
        a = part_analyses[pi["id"]]
        case["_extracted_details"]["per_part"][pi["name"]] = {
            "note_count": a.get("note_count", 0),
            "rest_count": a.get("rest_count", 0),
            "voices": a.get("voices", []),
            "staves_count": a.get("staves_count", 1),
            "has_ties": a.get("has_ties", False),
            "has_chords": a.get("has_chords", False),
            "has_dots": a.get("has_dots", False),
            "directions": a.get("directions", []),
            "lyric_verse_count": a.get("lyric_verse_count", 0),
        }

    return case


def write_case_yaml(case: dict, output_path: Path) -> None:
    """Write case.yaml with nice formatting and section comments."""
    # Separate the _extracted_details section
    details = case.pop("_extracted_details", {})

    # Add YAML header comment
    lines = [
        f"# case.yaml for: {case.get('title', 'Unknown')}",
        f"# Auto-generated from expected_final.musicxml",
        f"# Review and adjust values marked with TODO",
        "",
    ]

    yaml_str = yaml.dump(
        case,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    # Add section separators
    step_headers = {
        "step_01_ingestion:": "# ── Step 1: Ingestion ──────────────────────────────",
        "step_02_preprocessing:": "# ── Step 2: Preprocessing ──────────────────────────",
        "step_03_text:": "# ── Step 3: Text Classification ────────────────────",
        "step_04_layout:": "# ── Step 4: Staff Detection ───────────────────────",
        "step_05_splitting:": "# ── Step 5: Staff Splitting ───────────────────────",
        "step_06_omr:": "# ── Step 6: OMR per Staff ─────────────────────────",
        "step_07_assembly:": "# ── Step 7: Score Assembly ────────────────────────",
        "step_08_lyrics:": "# ── Step 8: Lyrics ────────────────────────────────",
        "step_09_validation:": "# ── Step 9: Validation ───────────────────────────",
        "step_10_final:": "# ── Step 10: Final Output ────────────────────────",
    }

    formatted_lines = []
    for line in yaml_str.split("\n"):
        stripped = line.strip()
        if stripped in step_headers:
            formatted_lines.append("")
            formatted_lines.append(step_headers[stripped])
        formatted_lines.append(line)

    lines.extend(formatted_lines)

    # Add extracted details as YAML comments
    if details:
        lines.append("")
        lines.append("# ── Extracted Details (for reference, not used by tests) ──")
        details_yaml = yaml.dump(
            details,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )
        for dl in details_yaml.split("\n"):
            if dl.strip():
                lines.append(f"# {dl}")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Written: {output_path}")
    print(f"   Title:    {case.get('title', '?')}")
    print(f"   Parts:    {case.get('step_07_assembly', {}).get('part_names', [])}")
    print(f"   Measures: {case.get('step_07_assembly', {}).get('total_measures', '?')}")
    print(f"   Pages:    {case.get('step_01_ingestion', {}).get('expected_pages', '?')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert expected_final.musicxml to case.yaml"
    )
    parser.add_argument(
        "input",
        help="Path to expected_final.musicxml or fixture directory",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path for case.yaml (default: same directory as input)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)

    # If input is a directory, look for expected_final.musicxml
    if input_path.is_dir():
        musicxml_path = input_path / "expected_final.musicxml"
        if not musicxml_path.exists():
            print(f"❌ No expected_final.musicxml found in {input_path}")
            return
        fixture_dir = input_path
    else:
        musicxml_path = input_path
        fixture_dir = input_path.parent

    if not musicxml_path.exists():
        print(f"❌ File not found: {musicxml_path}")
        return

    output_path = Path(args.output) if args.output else (fixture_dir / "case.yaml")

    print(f"📄 Parsing: {musicxml_path}")
    extractor = MusicXMLExtractor(musicxml_path)
    case = build_case_yaml(extractor, fixture_dir)
    write_case_yaml(case, output_path)


if __name__ == "__main__":
    main()
