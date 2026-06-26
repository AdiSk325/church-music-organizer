"""NiceGUI entry point for Church Music Organizer.

Run with::

    poetry run python -m src.app_ng.main      # browser at http://localhost:8080
    CMO_NG_NATIVE=1 poetry run python -m src.app_ng.main   # native window (needs pywebview)

Replaces the legacy Streamlit app. Four tabs: Biblioteka (full),
Przegląd / Przetwarzanie / Edycja (stubs being ported from src/app/_legacy/).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path so ``src.*`` imports resolve when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nicegui import ui  # noqa: E402

from src.database import init_db  # noqa: E402

from src.app_ng import files  # noqa: F401, E402  — registers GET /file/{file_id}
from src.app_ng.pages import detail, edit, library, processing  # noqa: E402
from src.app_ng.shared import state  # noqa: E402

# Create tables on first run (same contract as the legacy app).
init_db()


@ui.page("/")
def main_page() -> None:
    """Single-page app with a header and four content tabs."""
    with ui.header().classes("items-center justify-between"):
        ui.label("🎵 Church Music Organizer").classes("text-xl font-bold")
        ui.label("v2 · NiceGUI").classes("text-sm opacity-70")

    with ui.tabs().classes("w-full") as tabs:
        tab_lib = ui.tab("Biblioteka", icon="library_music")
        tab_prev = ui.tab("Przegląd", icon="visibility")
        tab_proc = ui.tab("Przetwarzanie", icon="auto_fix_high")
        tab_edit = ui.tab("Edycja", icon="edit")

    # Register navigation handles so any tab can switch context to a piece.
    state.tabs = tabs
    state.tab_refs = {
        "biblioteka": tab_lib,
        "przeglad": tab_prev,
        "przetwarzanie": tab_proc,
        "edycja": tab_edit,
    }

    with ui.tab_panels(tabs, value=tab_lib).classes("w-full"):
        with ui.tab_panel(tab_lib):
            library.render()
        with ui.tab_panel(tab_prev):
            detail.render()
        with ui.tab_panel(tab_proc):
            processing.render()
        with ui.tab_panel(tab_edit):
            edit.render()


def _run() -> None:
    native = os.getenv("CMO_NG_NATIVE", "").lower() in ("1", "true", "yes")
    ui.run(
        title="Church Music Organizer",
        host=os.getenv("CMO_NG_HOST", "127.0.0.1"),
        port=int(os.getenv("CMO_NG_PORT", "8080")),
        native=native,
        reload=False,
        show=not native,
    )


# ``ui.run`` must execute at import time under ``python -m`` (NiceGUI quirk):
# it forks/reloads the module, so guarding with ``__main__`` alone is enough.
if __name__ in {"__main__", "__mp_main__"}:
    _run()
