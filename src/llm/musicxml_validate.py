"""Validate MusicXML produced by an LLM before it is persisted.

The LLM agents in steps 4 and 5 rewrite MusicXML, which is risky: a single broken
tag yields a file that no notation software can open.  Every LLM output is therefore
round-tripped through ``music21`` (already a project dependency) and only accepted
when it parses into a real score with at least one note — otherwise the caller keeps
the previous, known-good version.
"""

import logging
import zipfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def load_musicxml_text(path: str) -> str:
    """Return the plain MusicXML text for a file, decompressing ``.mxl`` if needed.

    Audiveris writes compressed ``.mxl`` (a zip containing the score plus ``META-INF``);
    the LLM agents need uncompressed MusicXML. Uncompressed ``.xml`` files are read as-is.

    Raises:
        ValueError: when a ``.mxl`` archive contains no MusicXML entry.
    """
    p = Path(path)
    if p.suffix.lower() != ".mxl":
        return p.read_text(encoding="utf-8")

    with zipfile.ZipFile(p) as zf:
        rootfile: Optional[str] = None
        # The container manifest names the primary score file.
        try:
            container = zf.read("META-INF/container.xml").decode("utf-8")
            import re

            match = re.search(r'full-path\s*=\s*"([^"]+)"', container)
            if match:
                rootfile = match.group(1)
        except KeyError:
            pass

        if rootfile is None:
            candidates = [
                n
                for n in zf.namelist()
                if not n.startswith("META-INF") and n.lower().endswith((".xml", ".musicxml"))
            ]
            if not candidates:
                raise ValueError(f"Archiwum .mxl nie zawiera pliku MusicXML: {path}")
            rootfile = candidates[0]

        return zf.read(rootfile).decode("utf-8")


def validate_musicxml(xml: str) -> Tuple[bool, Optional[str]]:
    """Parse ``xml`` with music21 and report whether it is usable.

    Args:
        xml: MusicXML document as a string.

    Returns:
        ``(True, None)`` when the document parses into a score containing at least
        one note; otherwise ``(False, "<reason>")``.
    """
    if not xml or not xml.strip():
        return False, "Pusty dokument MusicXML."

    # Imported lazily — music21 import is comparatively heavy.
    from music21 import converter

    try:
        score = converter.parseData(xml, format="musicxml")
    except Exception as exc:  # music21 raises a broad family of parse errors
        logger.warning("validate_musicxml: music21 nie sparsował dokumentu: %s", exc)
        return False, f"music21 nie sparsował dokumentu: {exc}"

    try:
        note_count = len(list(score.recurse().notes))
    except Exception as exc:
        return False, f"Dokument sparsowany, ale nieczytelny dla music21: {exc}"

    if note_count == 0:
        return False, "Dokument sparsowany, ale nie zawiera żadnych nut."

    return True, None
