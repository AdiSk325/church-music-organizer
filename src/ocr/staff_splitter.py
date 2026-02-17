"""Staff splitter — cut a full-page image into per-staff images.

Uses StaffDetector results to extract individual staves or staff groups
as separate images, which are then fed to the OMR engine independently.
This prevents homr from merging all staves into a single part.
"""

import logging
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np

from .staff_detector import StaffLayout, StaffInfo, StaffGroup

logger = logging.getLogger(__name__)


class StaffSplitter:
    """Split a full-page image into individual staff images."""

    def __init__(self, output_dir: str = "data/processed/staves"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def split(
        self,
        image_path: str,
        layout: StaffLayout,
        margin_factor: float = 0.5,
    ) -> List[dict]:
        """Split image into per-staff-group images.

        For vocal parts (single staves), each staff becomes one image.
        For grand staff (e.g., organ with brace), the pair of staves
        becomes one image.

        Args:
            image_path: Path to the full-page image
            layout: StaffLayout from StaffDetector
            margin_factor: Extra vertical margin as a fraction of staff height.
                           0.5 = add 50% of staff height above and below.

        Returns:
            List of dicts: [{"path": str, "staff_indices": [int],
                             "group_type": "single"|"brace"|"bracket",
                             "y_top": int, "y_bottom": int}]
        """
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"Could not read image: {image_path}")
            return []

        if not layout.staves:
            logger.warning("No staves in layout, returning full image")
            return [{"path": image_path, "staff_indices": [],
                     "group_type": "full", "y_top": 0, "y_bottom": img.shape[0]}]

        img_stem = Path(image_path).stem
        h, w = img.shape[:2]

        # Determine which staves to cut together
        cut_groups = self._plan_cuts(layout)

        results = []
        for group_idx, group in enumerate(cut_groups):
            staff_indices = group["staff_indices"]
            group_staves = [s for s in layout.staves if s.index in staff_indices]

            if not group_staves:
                continue

            y_top = min(s.y_top for s in group_staves)
            y_bottom = max(s.y_bottom for s in group_staves)
            staff_height = y_bottom - y_top

            # Add margin
            margin = int(staff_height * margin_factor)
            cut_top = max(0, y_top - margin)
            cut_bottom = min(h, y_bottom + margin)

            # Crop
            crop = img[cut_top:cut_bottom, :]

            # Save
            indices_str = "_".join(str(i) for i in staff_indices)
            out_name = f"{img_stem}_staff_{indices_str}.png"
            out_path = self.output_dir / out_name
            cv2.imwrite(str(out_path), crop)

            results.append({
                "path": str(out_path),
                "staff_indices": staff_indices,
                "group_type": group["group_type"],
                "y_top": cut_top,
                "y_bottom": cut_bottom,
            })

            logger.debug(
                f"Cut staves {staff_indices} ({group['group_type']}): "
                f"y={cut_top}-{cut_bottom}, saved to {out_name}"
            )

        logger.info(f"Split {image_path} into {len(results)} staff images")
        return results

    def _plan_cuts(self, layout: StaffLayout) -> List[dict]:
        """Plan which staves to cut together based on groups.

        Grand staff staves (brace) are cut together.
        Other staves are cut individually.
        Brace groups are validated against system boundaries —
        staves from different systems are never grouped together.
        """
        if not layout.systems:
            # No system info — cut each staff individually
            return [
                {"staff_indices": [s.index], "group_type": "single"}
                for s in layout.staves
            ]

        cuts = []

        for sys in layout.systems:
            system_indices = set(sys.staff_indices)

            # Find brace groups within THIS system only
            braced = set()
            brace_groups_in_system = []
            for g in layout.groups:
                if g.group_type == "brace":
                    # Only include staves that are in this system
                    group_in_sys = [
                        idx for idx in g.staff_indices
                        if idx in system_indices
                    ]
                    if len(group_in_sys) >= 2:
                        brace_groups_in_system.append(group_in_sys)
                        for idx in group_in_sys:
                            braced.add(idx)

            # Process staves in order within this system
            processed = set()
            for idx in sorted(sys.staff_indices):
                if idx in processed:
                    continue

                # Check if this staff is part of a brace group
                in_brace = None
                for bg_indices in brace_groups_in_system:
                    if idx in bg_indices:
                        in_brace = bg_indices
                        break

                if in_brace:
                    cuts.append({
                        "staff_indices": sorted(in_brace),
                        "group_type": "brace",
                    })
                    for si in in_brace:
                        processed.add(si)
                else:
                    cuts.append({
                        "staff_indices": [idx],
                        "group_type": "single",
                    })
                    processed.add(idx)

        return cuts

    def split_first_system_only(
        self,
        image_path: str,
        layout: StaffLayout,
        margin_factor: float = 0.5,
    ) -> List[dict]:
        """Split only the first system into per-staff images.

        For single-page scores with one system, this is the same as split().
        For multi-system pages, this returns only the first system's staves,
        which defines the part structure.

        Args:
            image_path: Path to the full image
            layout: StaffLayout from detector
            margin_factor: Vertical margin factor

        Returns:
            List of cut info dicts (same format as split())
        """
        img = cv2.imread(image_path)
        if img is None:
            return []

        if not layout.systems:
            return self.split(image_path, layout, margin_factor)

        # Restrict to first system staves only
        first_system = layout.systems[0]
        first_staves = [s for s in layout.staves 
                        if s.index in first_system.staff_indices]

        restricted_layout = StaffLayout(
            staves=first_staves,
            groups=layout.groups,
            systems=[first_system],
            image_width=layout.image_width,
            image_height=layout.image_height,
        )

        return self.split(image_path, restricted_layout, margin_factor)
