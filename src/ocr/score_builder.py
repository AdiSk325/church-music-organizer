"""Score builder — assemble multi-part MusicXML from per-staff OMR results.

Takes the OMR results from individual staves and combines them into
a properly structured MusicXML score with:
- Correct part-list with part names and instrument sounds
- Staff groups (brackets/braces)
- Proper voice numbering per part
- Metadata (title, composer, tempo)
- Anacrusis detection
- Lyrics placement on vocal parts only

This module is the orchestrator.  Low-level XML construction lives in
``xml_writer`` and part-definition logic in ``part_definition``.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from music21 import clef, converter

from .part_definition import (
    PartDefinition,
    determine_parts,
)
from .staff_detector import StaffLayout
from .text_classifier import ClassifiedText
from . import xml_writer

logger = logging.getLogger(__name__)


class ScoreBuilder:
    """Build a complete MusicXML score from per-staff OMR results."""

    # Re-export constant so callers that used ScoreBuilder.DIVISIONS
    # continue to work.
    DIVISIONS = xml_writer.DIVISIONS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        staff_omr_results: List[dict],
        text_info: ClassifiedText,
        layout: StaffLayout,
        output_path: str,
        all_page_layouts: Optional[List[StaffLayout]] = None,
    ) -> str:
        """Build a complete MusicXML score.

        Args:
            staff_omr_results: List of {"path": musicxml_path,
                "staff_indices": [int], "group_type": str,
                "page": int (optional), "system": int (optional),
                "clef": str (optional, "G" or "F")}
            text_info: Classified text from PDF
            layout: Staff layout from detector (first page or all)
            output_path: Where to save the final MusicXML
            all_page_layouts: Layouts for all pages (for multi-page)

        Returns:
            Path to the output MusicXML file
        """
        # Step 1: Determine part structure from layout + text + clef info
        clef_map = self._extract_clef_map(staff_omr_results)
        if clef_map:
            from .staff_detector import StaffDetector
            layout = StaffDetector.update_groups_from_clefs(
                layout, clef_map
            )

        parts_def = determine_parts(layout, text_info)

        if not parts_def:
            logger.warning(
                "Could not determine part structure, "
                "falling back to single part"
            )
            if staff_omr_results:
                import shutil
                shutil.copy2(staff_omr_results[0]["path"], output_path)
                return output_path
            return ""

        logger.info(f"Building score with {len(parts_def)} parts")
        self.last_parts_def = parts_def  # expose for lyrics alignment

        # Step 2: Parse each per-staff OMR result
        parsed_parts: Dict[tuple, object] = {}
        for omr_result in staff_omr_results:
            if (not omr_result.get("path")
                    or not Path(omr_result["path"]).exists()):
                continue
            try:
                score = converter.parse(omr_result["path"])
                staff_indices = omr_result.get("staff_indices", [])
                key_str = tuple(staff_indices)
                parsed_parts[key_str] = score
            except Exception as e:
                logger.warning(
                    f"Could not parse {omr_result['path']}: {e}"
                )

        # Step 3: Multi-system/multi-page assembly
        part_omr_mapping = self._map_staves_to_parts(
            staff_omr_results, parts_def, layout, all_page_layouts
        )

        # Step 4: Build the MusicXML using ElementTree
        musicxml = self._build_musicxml_assembled(
            parts_def, parsed_parts, part_omr_mapping, text_info,
            layout, all_page_layouts=all_page_layouts,
        )

        # Step 5: Write output
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
                '<!DOCTYPE score-partwise PUBLIC '
                '"-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                '"http://www.musicxml.org/dtds/partwise.dtd">',
                1,
            )
            output_path.write_text(content, encoding="utf-8")

        logger.info(f"Score saved to {output_path}")
        return str(output_path)

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
        parts_def = determine_parts(layout, text_info)

        if not parts_def:
            logger.warning("Could not determine parts from layout")
            return omr_musicxml_path

        try:
            omr_score = converter.parse(omr_musicxml_path)
        except Exception as e:
            logger.error(f"Could not parse OMR result: {e}")
            return omr_musicxml_path

        if not omr_score.parts:
            return omr_musicxml_path

        omr_part = omr_score.parts[0]

        root = xml_writer.build_musicxml_from_split(
            parts_def, omr_part, text_info, layout,
        )

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
                '<!DOCTYPE score-partwise PUBLIC '
                '"-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                '"http://www.musicxml.org/dtds/partwise.dtd">',
                1,
            )
            output_path.write_text(content, encoding="utf-8")

        logger.info(f"Restructured score saved to {output_path}")
        return str(output_path)

    # ------------------------------------------------------------------
    # Clef extraction
    # ------------------------------------------------------------------

    def _extract_clef_map(
        self, staff_omr_results: List[dict],
    ) -> Dict[int, str]:
        """Extract clef type from each staff's OMR result.

        Reads the first clef found in each parsed MusicXML to build
        a mapping {staff_index: "G" or "F"}.
        """
        clef_map: Dict[int, str] = {}

        for omr in staff_omr_results:
            path = omr.get("path", "")
            indices = omr.get("staff_indices", [])
            if not path or not Path(path).exists() or not indices:
                continue

            # If clef was already annotated
            if "clef" in omr:
                for idx in indices:
                    clef_map[idx] = omr["clef"]
                continue

            try:
                score = converter.parse(path)
                if not score.parts:
                    continue
                part = score.parts[0]
                clefs_found = list(
                    part.flatten().getElementsByClass("Clef")
                )
                if clefs_found:
                    first_clef = clefs_found[0]
                    clef_sign = "G"
                    if isinstance(first_clef, clef.BassClef):
                        clef_sign = "F"
                    elif isinstance(first_clef, clef.TrebleClef):
                        clef_sign = "G"
                    elif hasattr(first_clef, "sign"):
                        clef_sign = first_clef.sign
                    for idx in indices:
                        clef_map[idx] = clef_sign
                else:
                    # Infer from note range
                    notes = list(part.flatten().notes)
                    if notes:
                        pitched = [
                            n for n in notes if hasattr(n, "pitch")
                        ]
                        if pitched:
                            avg_midi = sum(
                                n.pitch.midi for n in pitched
                            ) / len(pitched)
                            clef_sign = (
                                "G" if avg_midi >= 55 else "F"
                            )
                            for idx in indices:
                                clef_map[idx] = clef_sign
            except Exception as e:
                logger.debug(
                    f"Could not extract clef from {path}: {e}"
                )

        return clef_map

    # ------------------------------------------------------------------
    # Multi-system / multi-page assembly helpers
    # ------------------------------------------------------------------

    def _map_staves_to_parts(
        self,
        staff_omr_results: List[dict],
        parts_def: List[PartDefinition],
        layout: StaffLayout,
        all_page_layouts: Optional[List[StaffLayout]] = None,
    ) -> Dict[int, List[dict]]:
        """Map OMR results from multiple systems/pages to part indices.

        For multi-system scores, each system contributes additional
        measures to the same parts.  Matching uses relative position
        within each system (0th staff = first part, etc.).

        Args:
            staff_omr_results: All OMR results with staff_indices and
                optional "page" and "original_staff_indices" keys
            parts_def: Part definitions (from first system)
            layout: Staff layout (first page)
            all_page_layouts: Optional layouts for additional pages

        Returns:
            Dict mapping part_index (0-based) to list of OMR result
            dicts in order (system 1 first, then system 2, etc.)
        """
        part_mapping: Dict[int, List[dict]] = {
            i: [] for i in range(len(parts_def))
        }

        # Build part → relative positions mapping from first system
        part_positions: Dict[int, List[int]] = {}
        first_sys = (
            layout.systems[0] if layout.systems else None
        )
        if first_sys:
            for pi, pdef in enumerate(parts_def):
                positions = []
                for si in pdef.staff_indices:
                    if si in first_sys.staff_indices:
                        pos = first_sys.staff_indices.index(si)
                        positions.append(pos)
                part_positions[pi] = positions

        for omr in staff_omr_results:
            indices = omr.get("staff_indices", [])
            if not indices:
                if parts_def:
                    part_mapping[0].append(omr)
                continue

            matched_part = None

            local_indices = omr.get(
                "original_staff_indices", indices
            )
            page_idx = omr.get("page", 0)

            pg_layout = layout
            if (all_page_layouts
                    and page_idx < len(all_page_layouts)):
                pg_layout = all_page_layouts[page_idx]

            # Method 1: Direct match with first system's parts
            if page_idx == 0:
                key_tuple = tuple(sorted(local_indices))
                for pi, pdef in enumerate(parts_def):
                    if (tuple(sorted(pdef.staff_indices))
                            == key_tuple):
                        matched_part = pi
                        break

            # Method 2: Match by relative position within system
            if matched_part is None:
                for sys_info in pg_layout.systems:
                    if all(
                        i in sys_info.staff_indices
                        for i in local_indices
                    ):
                        rel_positions = sorted([
                            sys_info.staff_indices.index(i)
                            for i in local_indices
                        ])
                        for pi, ppositions in part_positions.items():
                            if rel_positions == sorted(ppositions):
                                matched_part = pi
                                break
                        if matched_part is None:
                            for pi, pp in part_positions.items():
                                if set(rel_positions).issubset(
                                    set(pp)
                                ):
                                    matched_part = pi
                                    break
                        break

            # Method 3: Positional fallback for multi-page
            if matched_part is None and first_sys:
                for pi, ppositions in part_positions.items():
                    expected = sorted(
                        first_sys.staff_indices[p]
                        for p in ppositions
                        if p < len(first_sys.staff_indices)
                    )
                    if sorted(local_indices) == expected:
                        matched_part = pi
                        break

            # Method 4: Brute-force by group type
            if matched_part is None:
                group_type = omr.get("group_type", "single")
                n_staves = len(local_indices)
                for pi, pdef in enumerate(parts_def):
                    if (pdef.num_staves == n_staves
                            and pdef.group_type == group_type):
                        already = any(
                            o.get("page") == page_idx
                            and o.get("original_staff_indices")
                            == local_indices
                            for o in part_mapping[pi]
                        )
                        if not already:
                            matched_part = pi
                            break

            if matched_part is not None:
                part_mapping[matched_part].append(omr)
                logger.debug(
                    f"Mapped staff {indices} "
                    f"(local {local_indices}) -> part "
                    f"{matched_part} "
                    f"({parts_def[matched_part].part_name})"
                )
            else:
                logger.warning(
                    f"Could not map staff {indices} "
                    f"(local {local_indices}) to any part"
                )

        return part_mapping

    @staticmethod
    def _all_systems(
        layout: StaffLayout,
        all_page_layouts: Optional[List[StaffLayout]],
    ) -> List:
        """Get all SystemInfo objects across all pages."""
        systems: List = []
        if all_page_layouts:
            for pg in all_page_layouts:
                systems.extend(pg.systems)
        else:
            systems.extend(layout.systems)
        return systems

    def _different_system(
        self,
        omr_a: dict,
        omr_b: dict,
        layout: StaffLayout,
        all_page_layouts: Optional[List[StaffLayout]],
    ) -> bool:
        """Check if two OMR results come from different systems."""
        indices_a = set(omr_a.get("staff_indices", []))
        indices_b = set(omr_b.get("staff_indices", []))

        for sys_info in self._all_systems(layout, all_page_layouts):
            sys_set = set(sys_info.staff_indices)
            if indices_a & sys_set and indices_b & sys_set:
                return False
        return True

    # ------------------------------------------------------------------
    # System grouping / splitting / merging
    # ------------------------------------------------------------------

    def _group_by_system(
        self,
        omr_results: List[dict],
        layout: StaffLayout,
        all_page_layouts: Optional[List[StaffLayout]],
    ) -> List[Tuple[Tuple[int, int], List[dict]]]:
        """Group OMR results by (page, system_index).

        Returns list of ((page, sys_idx), [omr_dicts]) tuples,
        ordered by page then system.
        """
        all_layouts = [layout]
        if all_page_layouts:
            all_layouts = all_page_layouts

        groups: Dict[Tuple[int, int], List[dict]] = {}

        for omr in omr_results:
            page_idx = omr.get("page", 0)
            local_indices = omr.get(
                "original_staff_indices",
                omr.get("staff_indices", []),
            )

            pg_layout = layout
            if page_idx < len(all_layouts):
                pg_layout = all_layouts[page_idx]

            # Find which system this staff belongs to
            sys_idx = 0
            best_overlap = 0
            for si in pg_layout.systems:
                overlap = sum(
                    1 for i in local_indices
                    if i in si.staff_indices
                )
                if overlap > best_overlap:
                    best_overlap = overlap
                    sys_idx = si.system_index

            key = (page_idx, sys_idx)
            if key not in groups:
                groups[key] = []
            groups[key].append(omr)

        return sorted(groups.items(), key=lambda x: x[0])

    @staticmethod
    def _split_cross_system_measures(
        measures: List,
    ) -> List[List]:
        """Detect if a measure list spans multiple systems via clef change.

        When homr processes a brace image that spans system boundaries,
        it produces measures with a clef change (e.g., F->G) at the
        system break point.  Detect this and split the measures.

        Returns a list of measure-sublists (one per detected system).
        """
        if len(measures) <= 2:
            return [measures]

        current_clef = None
        split_points: List[int] = []

        for m_idx, m in enumerate(measures):
            clefs_found = list(
                m.flatten().getElementsByClass(clef.Clef)
            )
            if clefs_found:
                clef_sign = clefs_found[0].sign
                if (current_clef is not None
                        and clef_sign != current_clef):
                    split_points.append(m_idx)
                    logger.info(
                        f"Detected cross-system break at measure "
                        f"{m_idx}: clef {current_clef} -> {clef_sign}"
                    )
                current_clef = clef_sign

        if not split_points:
            return [measures]

        result: List[List] = []
        prev = 0
        for sp in split_points:
            if sp > prev:
                result.append(measures[prev:sp])
            prev = sp
        if prev < len(measures):
            result.append(measures[prev:])

        return result

    def _merge_system_measures(
        self,
        measures_list: List[List],
        pdef: PartDefinition,
    ) -> List:
        """Merge measures from multiple staves in the same system.

        For a grand-staff part, stave 1 (treble) and stave 2 (bass)
        are separate OMR results.  Their measures at the same index
        should be combined into one measure with notes from both staves.

        Args:
            measures_list: List of measure-lists (one per staff OMR)
            pdef: Part definition

        Returns:
            Single list of merged measures
        """
        if len(measures_list) == 1:
            return measures_list[0]

        max_len = max(len(ml) for ml in measures_list)

        merged: List = []
        for m_idx in range(max_len):
            source_measures = []
            for ml in measures_list:
                if m_idx < len(ml):
                    source_measures.append(ml[m_idx])

            if len(source_measures) == 1:
                merged.append(source_measures[0])
            else:
                combined = self._combine_measures(
                    source_measures, pdef
                )
                merged.append(combined)

        return merged

    @staticmethod
    def _combine_measures(
        measures: List,
        pdef: PartDefinition,
    ):
        """Combine notes from multiple measures into one.

        Creates a new music21 Measure with all notes and rests
        from the input measures.  For grand staff, keeps staff
        assignment based on pitch.
        """
        from music21 import stream as m21stream

        combined = m21stream.Measure()

        first = measures[0]
        if hasattr(first, "timeSignature") and first.timeSignature:
            combined.timeSignature = first.timeSignature
        if hasattr(first, "keySignature") and first.keySignature:
            combined.keySignature = first.keySignature

        for measure in measures:
            for elem in measure.flatten().notesAndRests:
                try:
                    imported = elem.__deepcopy__()
                    combined.insert(float(elem.offset), imported)
                except Exception:
                    pass

        return combined

    # ------------------------------------------------------------------
    # Assembled MusicXML builder (multi-system/page)
    # ------------------------------------------------------------------

    def _build_musicxml_assembled(
        self,
        parts_def: List[PartDefinition],
        parsed_parts: Dict[tuple, object],
        part_omr_mapping: Dict[int, List[dict]],
        text_info: ClassifiedText,
        layout: StaffLayout,
        all_page_layouts: Optional[List[StaffLayout]] = None,
    ) -> ET.Element:
        """Build MusicXML with multi-system assembly.

        Unlike ``xml_writer.build_musicxml`` which maps 1 OMR result
        -> 1 part, this method concatenates measures from multiple OMR
        results (one per system/page) into each part.
        """
        root = ET.Element("score-partwise", version="4.0")

        # --- Work/movement titles ---
        if text_info.title:
            work = ET.SubElement(root, "work")
            ET.SubElement(work, "work-title").text = text_info.title

        # --- Identification ---
        ident = ET.SubElement(root, "identification")
        if text_info.composer:
            ET.SubElement(
                ident, "creator", type="composer"
            ).text = text_info.composer
        if text_info.arranger:
            ET.SubElement(
                ident, "creator", type="arranger"
            ).text = text_info.arranger
        encoding = ET.SubElement(ident, "encoding")
        ET.SubElement(encoding, "software").text = (
            "Church Music Organizer OMR"
        )
        ET.SubElement(encoding, "encoding-date").text = "2025-07-26"

        # --- Part list ---
        part_list = ET.SubElement(root, "part-list")

        vocal_parts = [
            p for p in parts_def
            if p.is_vocal and p.group_number > 0
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
            sp = ET.SubElement(
                part_list, "score-part", id=pdef.part_id
            )
            ET.SubElement(sp, "part-name").text = pdef.part_name
            if pdef.abbreviation:
                ET.SubElement(
                    sp, "part-abbreviation"
                ).text = pdef.abbreviation

            inst_id = f"{pdef.part_id}-I1"
            si = ET.SubElement(sp, "score-instrument", id=inst_id)
            ET.SubElement(
                si, "instrument-name"
            ).text = pdef.instrument_name
            if pdef.instrument_sound:
                ET.SubElement(
                    si, "instrument-sound"
                ).text = pdef.instrument_sound

            midi_el = ET.SubElement(
                sp, "midi-instrument", id=inst_id
            )
            ET.SubElement(
                midi_el, "midi-channel"
            ).text = str(i + 1)
            ET.SubElement(
                midi_el, "midi-program"
            ).text = str(pdef.midi_program)

            if (pdef.is_vocal and pdef.group_number > 0
                    and pdef == vocal_parts[-1]):
                ET.SubElement(
                    part_list, "part-group",
                    type="stop", number=str(pdef.group_number),
                )

        # --- Parts with measures (assembled) ---
        for pi, pdef in enumerate(parts_def):
            part_el = ET.SubElement(root, "part", id=pdef.part_id)

            omr_results_for_part = part_omr_mapping.get(pi, [])

            if not omr_results_for_part:
                okey = tuple(pdef.staff_indices)
                omr_score = parsed_parts.get(okey)
                if omr_score and list(omr_score.parts):
                    xml_writer.fill_part_from_omr(
                        part_el, pdef, omr_score, text_info,
                    )
                else:
                    xml_writer.fill_empty_part(
                        part_el, pdef, text_info,
                    )
                continue

            system_groups = self._group_by_system(
                omr_results_for_part, layout, all_page_layouts,
            )

            all_measures_meta: List[
                Tuple[object, Optional[tuple], Optional[int]]
            ] = []

            for _sys_key, sys_omr_list in system_groups:
                sys_measures_list: List[List] = []
                sys_ts_candidates: List[tuple] = []
                sys_ks_candidates: List[int] = []

                for omr_dict in sys_omr_list:
                    path = omr_dict.get("path", "")
                    okey = tuple(
                        omr_dict.get("staff_indices", [])
                    )
                    omr_score = parsed_parts.get(okey)
                    if (omr_score is None
                            and path and Path(path).exists()):
                        try:
                            omr_score = converter.parse(path)
                        except Exception:
                            continue
                    if omr_score and list(omr_score.parts):
                        omr_part = list(omr_score.parts)[0]
                        measures = list(
                            omr_part.getElementsByClass("Measure")
                        )
                        sys_measures_list.append(measures)
                        ts = list(
                            omr_part.flatten()
                            .getElementsByClass("TimeSignature")
                        )
                        if ts:
                            sys_ts_candidates.append((
                                ts[0].numerator, ts[0].denominator,
                            ))
                        ks = list(
                            omr_part.flatten()
                            .getElementsByClass("KeySignature")
                        )
                        if ks:
                            sys_ks_candidates.append(ks[0].sharps)

                # Vote on time / key signature
                sys_time_sig = self._vote_time_sig(
                    sys_ts_candidates, sys_measures_list,
                )
                sys_key_fifths = self._vote_key_sig(
                    sys_ks_candidates, sys_measures_list,
                )

                if not sys_measures_list:
                    continue

                # Handle cross-system splits
                expanded: List[List] = []
                for ml in sys_measures_list:
                    split_result = (
                        self._split_cross_system_measures(ml)
                    )
                    if len(split_result) > 1:
                        expanded.append(split_result[0])
                        for extra_ml in split_result[1:]:
                            extra_ts, extra_ks = (
                                self._extract_sig_from_measures(
                                    extra_ml
                                )
                            )
                            for m in extra_ml:
                                all_measures_meta.append((
                                    m,
                                    extra_ts or sys_time_sig,
                                    (extra_ks
                                     if extra_ks is not None
                                     else sys_key_fifths),
                                ))
                    else:
                        expanded.append(ml)
                sys_measures_list = expanded

                # Merge or select measures
                if len(sys_measures_list) == 1:
                    sys_merged = sys_measures_list[0]
                elif pdef.num_staves > 1:
                    sys_merged = self._merge_system_measures(
                        sys_measures_list, pdef,
                    )
                else:
                    sys_merged = sys_measures_list[0]

                for m in sys_merged:
                    all_measures_meta.append(
                        (m, sys_time_sig, sys_key_fifths)
                    )

            if not all_measures_meta:
                xml_writer.fill_empty_part(
                    part_el, pdef, text_info,
                )
                continue

            self._write_assembled_measures(
                part_el, pdef, all_measures_meta, text_info,
            )

        return root

    # ------------------------------------------------------------------
    # _build_musicxml_assembled helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vote_time_sig(
        candidates: List[tuple],
        measures_list: List[List],
    ) -> Optional[tuple]:
        """Pick majority time signature weighted by measure count."""
        if not candidates:
            return None
        weights: Dict[tuple, int] = {}
        for i, ts in enumerate(candidates):
            n = (
                len(measures_list[i])
                if i < len(measures_list) else 1
            )
            weights[ts] = weights.get(ts, 0) + n
        return max(weights, key=weights.get)  # type: ignore[arg-type]

    @staticmethod
    def _vote_key_sig(
        candidates: List[int],
        measures_list: List[List],
    ) -> Optional[int]:
        """Pick majority key signature weighted by measure count."""
        if not candidates:
            return None
        weights: Dict[int, int] = {}
        for i, ks in enumerate(candidates):
            n = (
                len(measures_list[i])
                if i < len(measures_list) else 1
            )
            weights[ks] = weights.get(ks, 0) + n
        return max(weights, key=weights.get)  # type: ignore[arg-type]

    @staticmethod
    def _extract_sig_from_measures(
        measures: List,
    ) -> Tuple[Optional[tuple], Optional[int]]:
        """Extract time/key signature from the first measure."""
        ts_val: Optional[tuple] = None
        ks_val: Optional[int] = None
        if measures:
            ts_list = list(
                measures[0].flatten()
                .getElementsByClass("TimeSignature")
            )
            if ts_list:
                ts_val = (
                    ts_list[0].numerator, ts_list[0].denominator
                )
            ks_list = list(
                measures[0].flatten()
                .getElementsByClass("KeySignature")
            )
            if ks_list:
                ks_val = ks_list[0].sharps
        return ts_val, ks_val

    def _write_assembled_measures(
        self,
        part_el: ET.Element,
        pdef: PartDefinition,
        all_measures_meta: List[
            Tuple[object, Optional[tuple], Optional[int]]
        ],
        text_info: ClassifiedText,
    ) -> None:
        """Write the assembled measures for one part.

        Handles anacrusis detection, time/key signature changes,
        and delegates note writing to ``xml_writer``.
        """
        first_ts = all_measures_meta[0][1]
        first_ks = all_measures_meta[0][2]
        expected_beats = (
            first_ts[0] * (4.0 / first_ts[1])
            if first_ts else 4.0
        )

        all_measures = [m for m, _, _ in all_measures_meta]
        first_dur = all_measures[0].duration.quarterLength
        is_anacrusis = first_dur < expected_beats * 0.9

        measure_number = 0 if is_anacrusis else 1
        current_ts = first_ts
        current_ks = first_ks

        for m_idx, (m21_measure, m_ts, m_ks) in enumerate(
            all_measures_meta
        ):
            attrs = {"number": str(measure_number)}
            if m_idx == 0 and is_anacrusis:
                attrs["implicit"] = "yes"

            measure_el = ET.SubElement(
                part_el, "measure", **attrs,
            )

            ts_changed = (
                m_ts is not None
                and m_ts != current_ts
                and m_idx > 0
            )
            ks_changed = (
                m_ks is not None
                and m_ks != current_ks
                and m_idx > 0
            )

            if m_idx == 0 or ts_changed or ks_changed:
                attr_el = ET.SubElement(measure_el, "attributes")

                if m_idx == 0:
                    ET.SubElement(
                        attr_el, "divisions"
                    ).text = str(self.DIVISIONS)

                if m_idx == 0 or ks_changed:
                    key_el = ET.SubElement(attr_el, "key")
                    fifths = m_ks if m_ks is not None else 0
                    ET.SubElement(
                        key_el, "fifths"
                    ).text = str(fifths)
                    if ks_changed:
                        current_ks = m_ks
                        logger.info(
                            f"Key change at measure "
                            f"{measure_number}: fifths={m_ks}"
                        )

                if m_idx == 0 or ts_changed:
                    time_el = ET.SubElement(attr_el, "time")
                    ts_write = m_ts or (4, 4)
                    ET.SubElement(
                        time_el, "beats"
                    ).text = str(ts_write[0])
                    ET.SubElement(
                        time_el, "beat-type"
                    ).text = str(ts_write[1])
                    if ts_changed:
                        current_ts = m_ts
                        logger.info(
                            f"Time sig change at measure "
                            f"{measure_number}: "
                            f"{m_ts[0]}/{m_ts[1]}"
                        )

                if m_idx == 0 and pdef.num_staves > 1:
                    ET.SubElement(
                        attr_el, "staves"
                    ).text = str(pdef.num_staves)

                if m_idx == 0:
                    for ci, clef_type in enumerate(pdef.clefs):
                        clef_el = ET.SubElement(attr_el, "clef")
                        if pdef.num_staves > 1:
                            clef_el.set("number", str(ci + 1))
                        if clef_type == "G":
                            ET.SubElement(
                                clef_el, "sign"
                            ).text = "G"
                            ET.SubElement(
                                clef_el, "line"
                            ).text = "2"
                        elif clef_type == "F":
                            ET.SubElement(
                                clef_el, "sign"
                            ).text = "F"
                            ET.SubElement(
                                clef_el, "line"
                            ).text = "4"

                if m_idx == 0 and text_info.tempo_markings:
                    tempo_text = text_info.tempo_markings[0]["text"]
                    tempo_match = re.search(r"(\d+)", tempo_text)
                    if tempo_match:
                        bpm = tempo_match.group(1)
                        direction = ET.SubElement(
                            measure_el, "direction",
                            placement="above",
                        )
                        dir_type = ET.SubElement(
                            direction, "direction-type",
                        )
                        metro = ET.SubElement(dir_type, "metronome")
                        ET.SubElement(
                            metro, "beat-unit"
                        ).text = "quarter"
                        ET.SubElement(
                            metro, "per-minute"
                        ).text = bpm
                        ET.SubElement(
                            direction, "sound", tempo=bpm,
                        )

            # Write notes (delegated to xml_writer)
            xml_writer.write_measure_notes(
                measure_el, m21_measure, pdef,
            )

            measure_number += 1
