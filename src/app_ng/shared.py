"""Shared state, constants and helpers for the NiceGUI app.

Ported from the legacy Streamlit ``src/app/main.py`` so the new tab-based UI
keeps identical domain behaviour (file-type detection, kind resolution,
liturgical vocab). The Streamlit-specific rendering was dropped; only the
pure helpers live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from src.database import FileType, MusicFileKind

# ---------------------------------------------------------------------------
# Liturgical domain constants (verbatim from the legacy app)
# ---------------------------------------------------------------------------

OCCASIONS = [
    "",
    "Niedziela",
    "Wielkanoc",
    "Boże Narodzenie",
    "Ślub",
    "Pogrzeb",
    "Bierzmowanie",
    "Pierwsza Komunia",
    "Adwent",
    "Wielki Post",
    "Uroczystość NMP",
]

SEASONS = [
    "",
    "Adwent",
    "Boże Narodzenie",
    "Zwykły",
    "Wielki Post",
    "Wielkanoc",
    "Zielone Świątki",
]

PER_PAGE = 20

# File extensions accepted for scan/score uploads across the app.
UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "tiff", "bmp", "mscz", "mscx", "xml", "musicxml"]
# File types that OCR / OMR can process.
OCR_TYPES = {FileType.SCAN, FileType.PDF}


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def get_file_type(filename: str) -> FileType:
    """Determine file type from filename extension."""
    ext = Path(filename).suffix.lower()
    if ext in (".mscz", ".mscx"):
        return FileType.MUSESCORE
    if ext == ".pdf":
        return FileType.PDF
    if ext in (".xml", ".musicxml"):
        return FileType.XML
    if ext in (".txt", ".ly"):
        return FileType.TEXT
    if ext in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return FileType.SCAN
    return FileType.OTHER


# ---------------------------------------------------------------------------
# MusicFileKind helpers — kind-first, filename-prefix fallback for kind=None.
# (Mirrors the legacy resolution so unmigrated records still display correctly.)
# ---------------------------------------------------------------------------

_KIND_DISPLAY: Dict[MusicFileKind, str] = {
    MusicFileKind.FINAL: "🎶 Finalny (z tekstem)",
    MusicFileKind.CORRECTED: "🛠️ Korekta partytury",
    MusicFileKind.OMR_RAW: "📄 OMR (surowy)",
    MusicFileKind.SOURCE_SCAN: "📄 OMR (surowy)",
    MusicFileKind.SOURCE_PDF: "📄 OMR (surowy)",
    MusicFileKind.EDITABLE: "📄 OMR (surowy)",
    MusicFileKind.OTHER: "📄 OMR (surowy)",
    MusicFileKind.REFERENCE: "📄 OMR (surowy)",
}


def resolve_xml_kind(f) -> str:
    """Display-kind label for an XML MusicFile (kind-first, prefix fallback)."""
    if f.kind is not None:
        return _KIND_DISPLAY.get(f.kind, "📄 OMR (surowy)")
    name = (f.original_filename or "").lower()
    if name.startswith("final_"):
        return "🎶 Finalny (z tekstem)"
    if name.startswith("corrected_"):
        return "🛠️ Korekta partytury"
    return "📄 OMR (surowy)"


def is_reference_file(f) -> bool:
    """True when a MusicFile is a reference / ground-truth score."""
    if f.kind is not None:
        return f.kind == MusicFileKind.REFERENCE
    return (f.description or "").startswith("[REFERENCJA]")


# ---------------------------------------------------------------------------
# Application state — shared across tabs (single-user desktop session).
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    """Cross-tab UI state for a single desktop session.

    ``tabs`` is the NiceGUI ``ui.tabs`` element; ``tab_refs`` maps a logical
    name ("przeglad", "edycja", …) to its ``ui.tab`` so handlers can switch
    tabs programmatically. ``on_navigate`` is registered by the panels that
    need to re-render when ``selected_piece_id`` changes.
    """

    selected_piece_id: Optional[int] = None
    tabs: object = None
    tab_refs: Dict[str, object] = field(default_factory=dict)
    on_navigate: Dict[str, Callable[[], None]] = field(default_factory=dict)

    def open_piece(self, piece_id: int, tab: str = "przeglad") -> None:
        """Select a piece and switch to ``tab``, refreshing dependent panels."""
        self.selected_piece_id = piece_id
        for refresh in self.on_navigate.values():
            try:
                refresh()
            except Exception:  # pragma: no cover — defensive UI guard
                pass
        target = self.tab_refs.get(tab)
        if self.tabs is not None and target is not None:
            self.tabs.set_value(target)


# Module-level singleton — imported by every page module.
state = AppState()
