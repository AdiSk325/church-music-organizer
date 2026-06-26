"""File-serving endpoint and local-app opener for the NiceGUI UI.

Registers a FastAPI route ``GET /file/{file_id}`` on the NiceGUI ``app``
object so that PDF/scan files can be served inline in an ``<iframe>`` without
the browser blocking a ``data:``-URI.  Also exposes ``open_in_app`` for
cross-platform "open with associated application" behaviour (server-side,
because this is a local single-user desktop app).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from fastapi.responses import FileResponse, Response
from nicegui import app, ui

from src.database import MusicFile, get_db_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTTP endpoint — serves a MusicFile by database id
# ---------------------------------------------------------------------------


@app.get("/file/{file_id}")
def _serve_file(file_id: int, download: bool = False) -> Response:
    """Return the file at ``MusicFile.file_path`` as an HTTP response.

    Pass ``?download=1`` to force ``Content-Disposition: attachment``; the
    default is ``inline`` so browsers/iframes render PDFs natively.
    """
    with get_db_session() as db:
        f = db.get(MusicFile, file_id)
        if f is None:
            return Response(status_code=404)
        path_str: str = f.file_path
        name: str | None = f.original_filename

    path = Path(path_str)
    if not path.exists():
        return Response(status_code=404)

    media_type: str | None = "application/pdf" if path.suffix.lower() == ".pdf" else None
    return FileResponse(
        path,
        media_type=media_type,
        filename=name or path.name,
        content_disposition_type="attachment" if download else "inline",
    )


# ---------------------------------------------------------------------------
# Server-side "open with associated application" helper
# ---------------------------------------------------------------------------


def open_in_app(path: str) -> None:
    """Open ``path`` in the associated desktop application (server-side).

    Works on Windows (``os.startfile``), macOS (``open``), and Linux
    (``xdg-open``).  Shows a ``ui.notify`` on success or failure.
    """
    p = Path(path)
    if not p.exists():
        ui.notify(f"Plik nie istnieje: {p}", type="negative")
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        ui.notify(f"Otwieram: {p.name}")
    except Exception:
        logger.exception("Błąd otwierania pliku %s", p)
        ui.notify(f"Nie można otworzyć pliku: {p.name}", type="negative")
