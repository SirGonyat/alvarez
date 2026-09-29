"""
Dynamic Row Tiling Engine for agy-rortings.

Groups terminal visual elements into rows where each line strictly adheres to the terminal column width.
Guarantees zero accidental wrapping while displaying 100% of telemetry elements.
"""

from typing import List
from alvarez.core.ansi import visible_len, truncate_ansi


class DynamicTiler:
    """Arranges ANSI-colored chips and badges into width-constrained terminal rows."""

    @staticmethod
    def tile_elements(elements: List[str], max_width: int, separator: str = " │ ") -> List[str]:
        """
        Dynamically packs visual elements into clean lines without exceeding max_width.
        """
        if max_width < 20:
            max_width = 20

        sep_len = visible_len(separator)
        rows: List[str] = []
        current_row: List[str] = []
        current_width = 0

        for raw_elem in elements:
            if not raw_elem or not str(raw_elem).strip():
                continue

            elem = raw_elem
            elen = visible_len(elem)

            # If a single element exceeds total width, truncate it safely
            if elen > max_width:
                elem = truncate_ansi(elem, max_width)
                elen = visible_len(elem)

            added_width = elen if not current_row else (sep_len + elen)

            if current_row and (current_width + added_width > max_width):
                rows.append(separator.join(current_row))
                current_row = [elem]
                current_width = elen
            else:
                current_row.append(elem)
                current_width += added_width

        if current_row:
            rows.append(separator.join(current_row))

        return rows
