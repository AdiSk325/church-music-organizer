"""Staff detector — detect staff lines, brackets, clefs, barlines from images.

Uses OpenCV to analyze sheet music images and detect:
- Individual staff lines (groups of 5 horizontal lines)
- Staff groupings (brackets, braces connecting staves)
- Approximate clef position per staff
- Barlines and their spans
- System breaks

This visual analysis runs BEFORE OMR to understand the score layout,
enabling per-staff OMR and correct multi-part assembly.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class StaffInfo:
    """Information about a single detected staff (5 lines)."""
    index: int = 0           # staff index (0-based, top to bottom)
    y_top: int = 0           # y coordinate of the topmost line
    y_bottom: int = 0        # y coordinate of the bottommost line
    y_center: int = 0        # center y
    x_left: int = 0          # leftmost x where staff starts
    x_right: int = 0         # rightmost x
    line_positions: List[int] = field(default_factory=list)  # y of each of the 5 lines
    line_spacing: float = 0.0  # average spacing between lines


@dataclass
class StaffGroup:
    """A group of staves connected by a bracket or brace."""
    group_type: str = "bracket"  # "bracket", "brace", "none"
    staff_indices: List[int] = field(default_factory=list)
    part_name: str = ""          # from text classifier if available


@dataclass
class SystemInfo:
    """A system (row) of staves on the page."""
    system_index: int = 0
    staff_indices: List[int] = field(default_factory=list)
    y_top: int = 0
    y_bottom: int = 0


@dataclass
class StaffLayout:
    """Complete staff layout detected from an image."""
    staves: List[StaffInfo] = field(default_factory=list)
    groups: List[StaffGroup] = field(default_factory=list)
    systems: List[SystemInfo] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
    
    @property
    def num_staves_per_system(self) -> int:
        """Number of staves in the first system."""
        if self.systems:
            return len(self.systems[0].staff_indices)
        return len(self.staves)


class StaffDetector:
    """Detect staff lines and layout from sheet music images."""

    def __init__(self, min_staff_gap: int = 30):
        """
        Args:
            min_staff_gap: Minimum vertical gap (px) between separate staves
        """
        self.min_staff_gap = min_staff_gap

    def detect(self, image_path: str) -> StaffLayout:
        """Detect staff layout from an image.

        Args:
            image_path: Path to preprocessed image (PNG)

        Returns:
            StaffLayout with detected staves, groups, and systems
        """
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"Could not read image: {image_path}")
            return StaffLayout()

        layout = StaffLayout()
        layout.image_width = img.shape[1]
        layout.image_height = img.shape[0]

        # Convert to grayscale and binarize
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Step 1: Find horizontal lines (staff lines)
        staff_line_ys = self._find_staff_lines(binary, layout.image_width)
        if not staff_line_ys:
            logger.warning("No staff lines detected")
            return layout

        # Step 2: Group into staves (5 lines each)
        layout.staves = self._group_into_staves(staff_line_ys, binary)
        if not layout.staves:
            logger.warning("Could not group lines into staves")
            return layout

        # Step 3: Detect systems
        layout.systems = self._detect_systems(layout.staves, binary)

        # Step 3b: Filter phantom staves
        layout.staves, layout.systems = self._filter_phantom_staves(
            layout.staves, layout.systems, binary
        )

        # Step 4: Detect staff groups (brackets/braces)
        layout.groups = self._detect_groups(layout.staves, layout.systems, binary)

        logger.info(
            f"StaffDetector: {len(layout.staves)} staves, "
            f"{len(layout.systems)} systems, "
            f"{len(layout.groups)} groups"
        )
        return layout

    def _find_staff_lines(self, binary: np.ndarray, img_width: int) -> List[int]:
        """Find y-coordinates of staff lines using horizontal projection.

        A staff line appears as a row with many black pixels spanning
        most of the page width.
        """
        # Horizontal projection: count black pixels per row
        h_proj = np.sum(binary, axis=1) / 255

        # Threshold: a staff line should span at least 40% of the image width
        threshold = img_width * 0.3
        
        candidate_rows = np.where(h_proj > threshold)[0]
        
        if len(candidate_rows) == 0:
            # Try lower threshold
            threshold = img_width * 0.15
            candidate_rows = np.where(h_proj > threshold)[0]

        if len(candidate_rows) == 0:
            return []

        # Cluster consecutive rows (a thick staff line spans a few pixels)
        line_centers = []
        cluster_start = candidate_rows[0]
        cluster_end = candidate_rows[0]

        for i in range(1, len(candidate_rows)):
            if candidate_rows[i] - candidate_rows[i - 1] <= 2:
                # Same cluster
                cluster_end = candidate_rows[i]
            else:
                # New cluster
                center = (cluster_start + cluster_end) // 2
                line_centers.append(center)
                cluster_start = candidate_rows[i]
                cluster_end = candidate_rows[i]

        # Don't forget the last cluster
        center = (cluster_start + cluster_end) // 2
        line_centers.append(center)

        logger.debug(f"Found {len(line_centers)} horizontal lines")
        return line_centers

    def _group_into_staves(
        self, line_ys: List[int], binary: np.ndarray
    ) -> List[StaffInfo]:
        """Group detected lines into staves of 5 lines each.

        Lines within a staff have consistent, small spacing (6-15px typically).
        Lines across different staves have large gaps.
        """
        if len(line_ys) < 5:
            return []

        # Calculate gaps between consecutive lines
        gaps = [line_ys[i + 1] - line_ys[i] for i in range(len(line_ys) - 1)]
        
        if not gaps:
            return []

        # Find the typical intra-staff gap (most common small gap)
        small_gaps = [g for g in gaps if g < 30]
        if not small_gaps:
            small_gaps = sorted(gaps)[:len(gaps) // 2]
        
        median_gap = int(np.median(small_gaps)) if small_gaps else 10

        # Group lines: consecutive lines with gap close to median_gap belong together
        staves = []
        current_lines = [line_ys[0]]

        for i in range(1, len(line_ys)):
            gap = line_ys[i] - line_ys[i - 1]
            
            # If gap is much larger than typical, start a new staff
            if gap > median_gap * 2.5:
                # Close current staff if it has enough lines
                if len(current_lines) >= 4:
                    staves.append(self._make_staff(current_lines, len(staves), binary))
                elif len(current_lines) >= 3:
                    # Partial staff — might still be valid
                    staves.append(self._make_staff(current_lines, len(staves), binary))
                current_lines = [line_ys[i]]
            else:
                current_lines.append(line_ys[i])
                
                # If we have 5 lines and the next gap would be large, close staff
                if len(current_lines) == 5:
                    if (i + 1 >= len(line_ys) or
                            line_ys[i + 1] - line_ys[i] > median_gap * 2.5):
                        staves.append(self._make_staff(current_lines, len(staves), binary))
                        current_lines = []

        # Don't forget the last group
        if len(current_lines) >= 4:
            staves.append(self._make_staff(current_lines, len(staves), binary))

        return staves

    def _make_staff(
        self, lines: List[int], index: int, binary: np.ndarray
    ) -> StaffInfo:
        """Create a StaffInfo from a list of line y-positions."""
        # Determine staff horizontal extent
        row = lines[len(lines) // 2]  # middle line
        row_pixels = binary[row, :]
        black_cols = np.where(row_pixels > 0)[0]
        
        x_left = int(black_cols[0]) if len(black_cols) > 0 else 0
        x_right = int(black_cols[-1]) if len(black_cols) > 0 else binary.shape[1]

        spacings = [lines[i + 1] - lines[i] for i in range(len(lines) - 1)]
        avg_spacing = np.mean(spacings) if spacings else 10.0

        return StaffInfo(
            index=index,
            y_top=lines[0],
            y_bottom=lines[-1],
            y_center=(lines[0] + lines[-1]) // 2,
            x_left=x_left,
            x_right=x_right,
            line_positions=lines[:5],  # cap at 5
            line_spacing=avg_spacing,
        )

    def _detect_systems(
        self, staves: List[StaffInfo], binary: Optional[np.ndarray] = None
    ) -> List[SystemInfo]:
        """Detect systems — groups of staves that form a horizontal row.

        Uses a hybrid approach:
        1. Gap analysis — large gaps between staves indicate system breaks
        2. Barline spanning — a vertical barline connecting staves = same system
        3. Consistency check — all systems should have the same # of staves

        In a typical church music score, one system contains:
        staff 0 (SA), staff 1 (TB), staff 2 (Org treble), staff 3 (Org bass)
        """
        if not staves:
            return []

        if len(staves) == 1:
            return [SystemInfo(
                system_index=0,
                staff_indices=[staves[0].index],
                y_top=staves[0].y_top,
                y_bottom=staves[0].y_bottom,
            )]

        # Calculate gaps between consecutive staves
        gaps = []
        for i in range(len(staves) - 1):
            gap = staves[i + 1].y_top - staves[i].y_bottom
            gaps.append(gap)

        if not gaps:
            return [SystemInfo(
                system_index=0,
                staff_indices=[s.index for s in staves],
                y_top=staves[0].y_top,
                y_bottom=staves[-1].y_bottom,
            )]

        # ---- Strategy 1: Try barline spanning detection ----
        if binary is not None:
            barline_systems = self._detect_systems_by_barline(
                staves, binary
            )
            if barline_systems and self._systems_are_consistent(barline_systems):
                logger.debug(
                    f"System detection via barline: "
                    f"{len(barline_systems)} systems"
                )
                return barline_systems

        # ---- Strategy 2: Gap-based clustering ----
        # Use kmeans-style gap analysis: find natural breakpoints
        sorted_gaps = sorted(gaps)
        n_gaps = len(sorted_gaps)

        # Find the largest single jump in gap sizes
        best_break = None
        best_ratio = 0
        for i in range(n_gaps - 1):
            if sorted_gaps[i] > 0:
                ratio = sorted_gaps[i + 1] / sorted_gaps[i]
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_break = (sorted_gaps[i] + sorted_gaps[i + 1]) / 2

        # Need a clear break (ratio > 1.5) and the gap should be significant
        if best_break and best_ratio > 1.5:
            system_break_threshold = best_break
        else:
            # Fallback: use median * 1.8
            median_gap = np.median(gaps)
            system_break_threshold = median_gap * 1.8

        systems = []
        current_staves = [staves[0].index]
        current_top = staves[0].y_top

        for i, gap in enumerate(gaps):
            if gap > system_break_threshold and len(current_staves) >= 2:
                # System break
                systems.append(SystemInfo(
                    system_index=len(systems),
                    staff_indices=list(current_staves),
                    y_top=current_top,
                    y_bottom=staves[i].y_bottom,
                ))
                current_staves = [staves[i + 1].index]
                current_top = staves[i + 1].y_top
            else:
                current_staves.append(staves[i + 1].index)

        # Last system
        systems.append(SystemInfo(
            system_index=len(systems),
            staff_indices=list(current_staves),
            y_top=current_top,
            y_bottom=staves[-1].y_bottom,
        ))

        # ---- Consistency check ----
        # All systems should have the same number of staves
        # If not, try to fix by adjusting the threshold
        if not self._systems_are_consistent(systems) and len(staves) >= 4:
            # Try even split
            even_systems = self._try_even_split(staves)
            if even_systems and self._systems_are_consistent(even_systems):
                systems = even_systems

        return systems

    def _detect_systems_by_barline(
        self, staves: List[StaffInfo], binary: np.ndarray
    ) -> List[SystemInfo]:
        """Detect systems by checking which staves share a left barline.

        A system barline is a vertical line on the left side that connects
        the topmost and bottommost staves in a system.
        """
        if len(staves) < 2:
            return []

        # Find the left edge of staves (where the system barline should be)
        x_left = min(s.x_left for s in staves)
        # Check a narrow column right at x_left
        x_start = max(0, x_left - 5)
        x_end = min(binary.shape[1], x_left + 10)
        barline_col = binary[:, x_start:x_end]

        if barline_col.size == 0:
            return []

        v_proj = np.sum(barline_col, axis=1) / 255

        # For each pair of consecutive staves, check if a barline
        # connects them (continuous black in the gap region)
        connected = []
        for i in range(len(staves) - 1):
            gap_start = staves[i].y_bottom
            gap_end = staves[i + 1].y_top
            if gap_end <= gap_start:
                connected.append(True)
                continue
            gap_region = v_proj[gap_start:gap_end]
            if len(gap_region) == 0:
                connected.append(False)
                continue
            coverage = np.sum(gap_region > 0) / len(gap_region)
            connected.append(coverage > 0.5)

        # Build systems from connected staves
        systems = []
        current = [staves[0].index]
        for i, is_connected in enumerate(connected):
            if is_connected:
                current.append(staves[i + 1].index)
            else:
                system_staves = [s for s in staves if s.index in current]
                systems.append(SystemInfo(
                    system_index=len(systems),
                    staff_indices=list(current),
                    y_top=system_staves[0].y_top,
                    y_bottom=system_staves[-1].y_bottom,
                ))
                current = [staves[i + 1].index]

        # Last system
        system_staves = [s for s in staves if s.index in current]
        if system_staves:
            systems.append(SystemInfo(
                system_index=len(systems),
                staff_indices=list(current),
                y_top=system_staves[0].y_top,
                y_bottom=system_staves[-1].y_bottom,
            ))

        return systems

    def _systems_are_consistent(self, systems: List[SystemInfo]) -> bool:
        """Check if all systems have the same number of staves."""
        if len(systems) <= 1:
            return True
        sizes = [len(s.staff_indices) for s in systems]
        return len(set(sizes)) == 1 and all(s >= 2 for s in sizes)

    def _try_even_split(self, staves: List[StaffInfo]) -> List[SystemInfo]:
        """Try to split staves evenly into systems.

        If we have 4 staves, try 2 systems of 2.
        If we have 6 staves, try 2 systems of 3 or 3 systems of 2.
        """
        n = len(staves)
        best_systems = None
        best_score = -1

        for staves_per_system in range(2, min(n, 5)):
            if n % staves_per_system != 0:
                continue
            systems = []
            for i in range(0, n, staves_per_system):
                group = staves[i:i + staves_per_system]
                systems.append(SystemInfo(
                    system_index=len(systems),
                    staff_indices=[s.index for s in group],
                    y_top=group[0].y_top,
                    y_bottom=group[-1].y_bottom,
                ))

            # Score: prefer splits where inter-system gaps are larger
            # than intra-system gaps
            if len(systems) > 1:
                inter_gaps = []
                intra_gaps = []
                for si, sys in enumerate(systems):
                    sys_staves = [s for s in staves if s.index in sys.staff_indices]
                    for j in range(len(sys_staves) - 1):
                        intra_gaps.append(
                            sys_staves[j + 1].y_top - sys_staves[j].y_bottom
                        )
                    if si < len(systems) - 1:
                        next_sys_staves = [
                            s for s in staves
                            if s.index in systems[si + 1].staff_indices
                        ]
                        inter_gaps.append(
                            next_sys_staves[0].y_top - sys_staves[-1].y_bottom
                        )

                if intra_gaps and inter_gaps:
                    avg_inter = np.mean(inter_gaps)
                    avg_intra = np.mean(intra_gaps) if intra_gaps else avg_inter
                    score = avg_inter / max(avg_intra, 1)
                    if score > best_score:
                        best_score = score
                        best_systems = systems

        return best_systems

    def _detect_groups(
        self,
        staves: List[StaffInfo],
        systems: List[SystemInfo],
        binary: np.ndarray,
    ) -> List[StaffGroup]:
        """Detect staff groups (brackets/braces) connecting staves.

        IMPORTANT: Groups are detected WITHIN each system only.
        A brace (grand staff) connects exactly 2 adjacent staves
        within the same system. A bracket connects vocal parts.

        Uses two strategies:
        1. Visual: look for brace/bracket symbols to the left of the
           system barline (further left than the barline itself)
        2. Spacing: within a system, closely-spaced staves = grand staff
        """
        if not systems or not staves:
            return []

        all_groups = []

        # Analyze each system independently
        for sys_info in systems:
            sys_staves = [
                s for s in staves if s.index in sys_info.staff_indices
            ]
            if len(sys_staves) < 2:
                continue

            sys_groups = self._detect_groups_in_system(
                sys_staves, binary
            )
            all_groups.extend(sys_groups)

        if not all_groups:
            # Try spacing-based inference per system
            for sys_info in systems:
                sys_staves = [
                    s for s in staves if s.index in sys_info.staff_indices
                ]
                if len(sys_staves) >= 2:
                    inferred = self._infer_groups_from_spacing(sys_staves)
                    all_groups.extend(inferred)

        return self._deduplicate_groups(all_groups)

    def _detect_groups_in_system(
        self,
        system_staves: List[StaffInfo],
        binary: np.ndarray,
    ) -> List[StaffGroup]:
        """Detect brace/bracket groups within a single system.

        Looks for visual connectors in the far-left margin region,
        further left than the system barline.
        """
        groups = []
        x_left = min(s.x_left for s in system_staves)

        # Brace is typically 15-40px to the left of the system barline
        # We look further left than the barline itself
        brace_x_end = max(0, x_left - 5)
        brace_x_start = max(0, x_left - 50)
        brace_region = binary[:, brace_x_start:brace_x_end]

        if brace_region.size == 0:
            return groups

        brace_proj = np.sum(brace_region, axis=1) / 255

        # Check ONLY adjacent pairs within this system for brace
        for i in range(len(system_staves) - 1):
            s_top = system_staves[i]
            s_bot = system_staves[i + 1]

            y_start = max(0, s_top.y_top - 10)
            y_end = min(len(brace_proj), s_bot.y_bottom + 10)

            if y_end <= y_start:
                continue

            region = brace_proj[y_start:y_end]
            if len(region) == 0:
                continue

            # Brace should have significant coverage in this region
            coverage = np.sum(region > 0) / len(region)

            # Also check that it does NOT extend beyond this pair
            # (i.e., it's not just the system barline)
            extends_above = False
            extends_below = False

            if i > 0:
                # Check if brace extends to the staff above
                prev_bot = system_staves[i - 1].y_bottom
                above_region = brace_proj[
                    max(0, prev_bot):max(0, s_top.y_top - 15)
                ]
                if len(above_region) > 5:
                    above_cov = np.sum(above_region > 0) / len(above_region)
                    extends_above = above_cov > 0.3

            if i + 2 < len(system_staves):
                # Check if brace extends to the staff below
                next_top = system_staves[i + 2].y_top
                below_region = brace_proj[
                    min(len(brace_proj), s_bot.y_bottom + 15):
                    min(len(brace_proj), next_top)
                ]
                if len(below_region) > 5:
                    below_cov = np.sum(below_region > 0) / len(below_region)
                    extends_below = below_cov > 0.3

            if coverage > 0.5 and not extends_above and not extends_below:
                # This is a local connector (brace) for just this pair
                avg_thickness = np.mean(region[region > 0]) if np.any(region > 0) else 0
                if avg_thickness > 3:
                    groups.append(StaffGroup(
                        group_type="brace",
                        staff_indices=[s_top.index, s_bot.index],
                    ))

        # If no brace found but all staves connected, it's a bracket
        if not groups and len(system_staves) > 1:
            # Check for bracket (full system connector)
            y_start = max(0, system_staves[0].y_top - 5)
            y_end = min(
                len(brace_proj), system_staves[-1].y_bottom + 5
            )
            region = brace_proj[y_start:y_end]
            if len(region) > 0:
                coverage = np.sum(region > 0) / len(region)
                if coverage > 0.6:
                    groups.append(StaffGroup(
                        group_type="bracket",
                        staff_indices=[
                            s.index for s in system_staves
                        ],
                    ))

        return groups

    def _infer_groups_from_spacing(
        self, staves: List[StaffInfo]
    ) -> List[StaffGroup]:
        """Infer staff groups from spacing when visual detection fails.

        Heuristic: staves very close together (small gap) form a grand staff
        (e.g., organ). Staves with moderate gaps are separate parts (vocal).

        Uses adaptive threshold: the smallest gap in a system is likely
        the grand staff gap (treble + bass clef together).
        """
        if len(staves) < 2:
            return []

        groups = []
        gaps = []
        for i in range(len(staves) - 1):
            gap = staves[i + 1].y_top - staves[i].y_bottom
            gaps.append(gap)

        if not gaps:
            return groups

        # If only 2 staves, they might be a grand staff
        if len(staves) == 2:
            # Church music: 2 staves = either SA+TB or grand staff organ
            # Grand staff has smaller gap than vocal parts
            staff_height = np.mean([
                s.y_bottom - s.y_top for s in staves
            ])
            if gaps[0] < staff_height * 1.5:
                groups.append(StaffGroup(
                    group_type="brace",
                    staff_indices=[staves[0].index, staves[1].index],
                ))
            return groups

        # For 3+ staves: find the smallest gap and check if it's
        # significantly smaller than others
        min_gap = min(gaps)
        max_gap = max(gaps)

        if max_gap > 0 and min_gap / max_gap < 0.7:
            # There's a clear gap difference — smallest gaps = grand staff
            threshold = (min_gap + max_gap) / 2

            i = 0
            while i < len(staves):
                if i < len(gaps) and gaps[i] < threshold:
                    groups.append(StaffGroup(
                        group_type="brace",
                        staff_indices=[staves[i].index, staves[i + 1].index],
                    ))
                    i += 2
                else:
                    i += 1
        else:
            # All gaps similar — likely all single staves or all grand staff pairs
            # In church music with even staves, try pairing (0,1), (2,3), etc.
            if len(staves) % 2 == 0 and len(staves) <= 4:
                for i in range(0, len(staves), 2):
                    groups.append(StaffGroup(
                        group_type="brace",
                        staff_indices=[staves[i].index, staves[i + 1].index],
                    ))

        return groups

    def _deduplicate_groups(self, groups: List[StaffGroup]) -> List[StaffGroup]:
        """Remove groups that are subsets of other groups."""
        if len(groups) <= 1:
            return groups

        result = []
        for g in groups:
            g_set = set(g.staff_indices)
            is_subset = False
            for other in groups:
                if other is g:
                    continue
                if g_set < set(other.staff_indices):
                    is_subset = True
                    break
            if not is_subset:
                result.append(g)
        return result

    def _filter_phantom_staves(
        self,
        staves: List[StaffInfo],
        systems: List[SystemInfo],
        binary: np.ndarray,
    ) -> Tuple[List[StaffInfo], List[SystemInfo]]:
        """Remove phantom staves (text/lyrics detected as staves).

        A phantom staff has very low note-like content compared to real
        staves. We detect this by:
        - Checking if the staff region has black pixel density much
          lower than other staves (after removing the staff lines)
        - If the staff is in the bottom 10% of the page (likely footer)
        - If the staff's horizontal extent is much shorter than others
        """
        if len(staves) <= 2:
            return staves, systems

        # Calculate content density for each staff
        densities = []
        for s in staves:
            y_top = max(0, s.y_top - 5)
            y_bot = min(binary.shape[0], s.y_bottom + 5)
            region = binary[y_top:y_bot, s.x_left:s.x_right]
            if region.size > 0:
                density = np.sum(region) / (255.0 * region.size)
            else:
                density = 0.0
            densities.append(density)

        if not densities:
            return staves, systems

        median_density = np.median(densities)
        median_width = np.median([s.x_right - s.x_left for s in staves])

        # Filter
        kept_staves = []
        for s, d in zip(staves, densities):
            staff_width = s.x_right - s.x_left
            is_phantom = False

            # Very low density compared to median
            if d < median_density * 0.3 and median_density > 0:
                is_phantom = True
            # Much shorter than median width
            if staff_width < median_width * 0.5:
                is_phantom = True
            # In footer region
            if s.y_center > binary.shape[0] * 0.92:
                is_phantom = True

            if is_phantom:
                logger.info(
                    f"Filtering phantom staff {s.index}: "
                    f"density={d:.3f}, width={staff_width}"
                )
            else:
                kept_staves.append(s)

        if len(kept_staves) == len(staves):
            return staves, systems

        # Re-index kept staves
        for i, s in enumerate(kept_staves):
            s.index = i

        # Re-detect systems on kept staves
        new_systems = self._detect_systems(kept_staves)

        return kept_staves, new_systems

    @staticmethod
    def update_groups_from_clefs(
        layout: 'StaffLayout',
        clef_map: Dict[int, str],
    ) -> 'StaffLayout':
        """Update staff groups based on clef information from OMR.

        This method should be called AFTER OMR, when we know each staff's
        clef. Adjacent staves with G+F clefs in the same system
        are grouped as grand staff (brace).

        Args:
            layout: Current StaffLayout (groups may be empty/wrong)
            clef_map: {staff_index: 'G' or 'F'} from OMR results

        Returns:
            Updated StaffLayout with corrected groups
        """
        if not clef_map or not layout.systems:
            return layout

        new_groups = []

        for sys_info in layout.systems:
            sys_indices = sys_info.staff_indices
            if len(sys_indices) < 2:
                continue

            # Look for adjacent G+F pairs → grand staff (brace)
            i = 0
            braced = set()
            while i < len(sys_indices) - 1:
                idx_a = sys_indices[i]
                idx_b = sys_indices[i + 1]
                clef_a = clef_map.get(idx_a, "?")
                clef_b = clef_map.get(idx_b, "?")

                if clef_a == "G" and clef_b == "F":
                    new_groups.append(StaffGroup(
                        group_type="brace",
                        staff_indices=[idx_a, idx_b],
                    ))
                    braced.add(idx_a)
                    braced.add(idx_b)
                    i += 2
                else:
                    i += 1

            # Non-braced staves within the system get a bracket
            # if there are multiple unbraced staves
            unbraced = [
                idx for idx in sys_indices if idx not in braced
            ]
            if len(unbraced) >= 2:
                new_groups.append(StaffGroup(
                    group_type="bracket",
                    staff_indices=unbraced,
                ))

        layout.groups = new_groups
        logger.info(
            f"Updated groups from clefs: {len(new_groups)} groups"
        )
        return layout

    def get_summary(self, layout: StaffLayout) -> str:
        """Human-readable summary of detected layout."""
        lines = [
            f"  Image:   {layout.image_width} x {layout.image_height}",
            f"  Staves:  {len(layout.staves)}",
            f"  Systems: {len(layout.systems)}",
        ]

        for sys in layout.systems:
            staff_str = ", ".join(str(i) for i in sys.staff_indices)
            lines.append(f"    System {sys.system_index}: staves [{staff_str}]")

        if layout.groups:
            for g in layout.groups:
                idx_str = ", ".join(str(i) for i in g.staff_indices)
                lines.append(f"    Group ({g.group_type}): staves [{idx_str}]")
        else:
            lines.append("    No staff groups detected")

        return "\n".join(lines)
