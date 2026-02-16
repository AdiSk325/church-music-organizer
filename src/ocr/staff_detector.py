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
from typing import List, Optional, Tuple

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
        layout.systems = self._detect_systems(layout.staves)

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

    def _detect_systems(self, staves: List[StaffInfo]) -> List[SystemInfo]:
        """Detect systems — groups of staves that form a horizontal row.

        In a typical SATB+Organ score, one system contains:
        staff 0 (SA), staff 1 (TB), staff 2 (Org treble), staff 3 (Org bass)

        Systems are separated by large vertical gaps.
        """
        if not staves:
            return []

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

        # System breaks: gaps significantly larger than the median
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

        return systems

    def _detect_groups(
        self,
        staves: List[StaffInfo],
        systems: List[SystemInfo],
        binary: np.ndarray,
    ) -> List[StaffGroup]:
        """Detect staff groups (brackets/braces) connecting staves.

        Looks for vertical elements at the left margin that connect
        multiple staves. A bracket (thin vertical line) connects vocal
        parts; a brace (curly) connects grand staff (piano/organ).
        """
        if not systems or not staves:
            return []

        groups = []
        first_system = systems[0]
        system_staves = [s for s in staves if s.index in first_system.staff_indices]

        if len(system_staves) < 2:
            return groups

        # Look for vertical connectors left of the staves
        # Check the region to the left of the first staff's x_left
        x_left = min(s.x_left for s in system_staves)
        margin_region = binary[:, max(0, x_left - 60):x_left]

        if margin_region.size == 0:
            return self._infer_groups_from_spacing(system_staves)

        # Vertical projection in the margin region
        v_proj = np.sum(margin_region, axis=1) / 255

        # Look for continuous vertical stretches of black pixels
        # A bracket connects from one staff's y_top to another's y_bottom
        for i in range(len(system_staves)):
            for j in range(i + 1, len(system_staves)):
                y_start = system_staves[i].y_top - 5
                y_end = system_staves[j].y_bottom + 5
                y_start = max(0, y_start)
                y_end = min(len(v_proj), y_end)
                
                if y_end <= y_start:
                    continue

                # Check if there's a continuous vertical line in this range
                region = v_proj[y_start:y_end]
                if len(region) == 0:
                    continue

                # A connector should have most rows with some black pixels
                coverage = np.sum(region > 0) / len(region)
                
                if coverage > 0.7:
                    # Determine type: brace (curly) vs bracket (straight)
                    # Braces are typically thicker and connect exactly 2 staves
                    indices = list(range(i, j + 1))
                    staff_idx_list = [system_staves[k].index for k in indices]
                    
                    if j - i == 1:
                        # 2 adjacent staves — could be grand staff (brace)
                        avg_thickness = np.mean(region[region > 0])
                        if avg_thickness > 5:
                            group_type = "brace"
                        else:
                            group_type = "bracket"
                    else:
                        group_type = "bracket"

                    groups.append(StaffGroup(
                        group_type=group_type,
                        staff_indices=staff_idx_list,
                    ))

        if not groups:
            return self._infer_groups_from_spacing(system_staves)

        # Remove redundant sub-groups
        groups = self._deduplicate_groups(groups)
        return groups

    def _infer_groups_from_spacing(
        self, staves: List[StaffInfo]
    ) -> List[StaffGroup]:
        """Infer staff groups from spacing when visual detection fails.

        Heuristic: staves very close together (small gap) form a grand staff
        (e.g., organ). Staves with moderate gaps are separate parts (vocal).
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

        median_gap = np.median(gaps)

        # Find pairs/groups of closely-spaced staves (grand staff)
        i = 0
        while i < len(staves):
            if i < len(gaps) and gaps[i] < median_gap * 0.6:
                # This staff and the next are closely spaced — grand staff
                groups.append(StaffGroup(
                    group_type="brace",
                    staff_indices=[staves[i].index, staves[i + 1].index],
                ))
                i += 2
            else:
                i += 1

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
