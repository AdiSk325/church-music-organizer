"""Biblioteka tab — searchable, filtered, paginated list of pieces + add/delete.

Full port of the legacy Streamlit "Music Collection" view. Uses
``MusicPieceService`` for queries (server-side filter + pagination) and
``FileService`` for uploads, so no DB query logic lives in the UI.
"""

from __future__ import annotations

import logging

from nicegui import ui

from src.database import MusicFile, MusicPiece, Tag, get_db_session
from src.services import FileService, MusicPieceService

from ..shared import OCCASIONS, PER_PAGE, SEASONS, get_file_type, state

logger = logging.getLogger(__name__)

# Local view state for the list (search term, filters, page index).
_view = {"search": "", "occasion": "", "season": "", "page": 0}


def _save_uploaded(piece_id: int, upload) -> None:
    """Persist one NiceGUI upload (``events.UploadEventArguments``) as a MusicFile."""
    data = upload.content.read()
    file_path = FileService.save_uploaded_file(
        piece_id=piece_id, filename=upload.name, file_data=data
    )
    with get_db_session() as db:
        db.add(
            MusicFile(
                music_piece_id=piece_id,
                file_path=file_path,
                file_type=get_file_type(upload.name),
                original_filename=upload.name,
                file_size=len(data),
            )
        )
        db.commit()


@ui.refreshable
def _piece_list() -> None:
    """Render the table of pieces for the current search/filter/page."""
    with get_db_session() as db:
        pieces, total = MusicPieceService.list_pieces(
            db,
            search=_view["search"] or None,
            occasion=_view["occasion"] or None,
            liturgical_season=_view["season"] or None,
            page=_view["page"],
            per_page=PER_PAGE,
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
        # Materialise plain dicts so the session can close before rendering.
        rows = [
            {
                "id": p.id,
                "title": p.title,
                "lyrics_author": p.lyrics_author or "—",
                "music_author": p.music_author or "—",
                "harmony_author": p.harmony_author or "—",
                "key": p.key_signature or "—",
                "time": p.time_signature or "—",
                "measures": str(p.measures_count) if p.measures_count else "—",
            }
            for p in pieces
        ]

    if not rows:
        if _view["search"] or _view["occasion"] or _view["season"]:
            ui.label("Brak utworów pasujących do kryteriów wyszukiwania.").classes(
                "text-grey italic"
            )
        else:
            ui.label("Brak utworów w kolekcji. Dodaj pierwszy utwór powyżej.").classes(
                "text-grey italic"
            )
        return

    columns = [
        {"name": "title", "label": "Tytuł", "field": "title", "align": "left", "sortable": True},
        {"name": "lyrics_author", "label": "Autor słów", "field": "lyrics_author", "align": "left"},
        {"name": "music_author", "label": "Autor muzyki", "field": "music_author", "align": "left"},
        {"name": "harmony_author", "label": "Autor harmonii", "field": "harmony_author",
         "align": "left"},
        {"name": "key", "label": "Tonacja", "field": "key", "align": "left"},
        {"name": "time", "label": "Metrum", "field": "time", "align": "left"},
        {"name": "measures", "label": "Takty", "field": "measures", "align": "right"},
        {"name": "actions", "label": "Akcje", "field": "actions", "align": "center"},
    ]
    table = ui.table(columns=columns, rows=rows, row_key="id").classes("w-full")
    # Custom action cell with per-row buttons (Quasar slot).
    table.add_slot(
        "body-cell-actions",
        r"""
        <q-td :props="props" class="text-center">
            <q-btn flat dense round icon="visibility" color="primary"
                   @click="$parent.$emit('open', props.row)">
                <q-tooltip>Przegląd</q-tooltip>
            </q-btn>
            <q-btn flat dense round icon="edit" color="secondary"
                   @click="$parent.$emit('edit', props.row)">
                <q-tooltip>Edycja</q-tooltip>
            </q-btn>
            <q-btn flat dense round icon="delete" color="negative"
                   @click="$parent.$emit('remove', props.row)">
                <q-tooltip>Usuń</q-tooltip>
            </q-btn>
        </q-td>
        """,
    )
    table.on("open", lambda e: state.open_piece(e.args["id"], "przeglad"))
    table.on("edit", lambda e: state.open_piece(e.args["id"], "edycja"))
    table.on("remove", lambda e: _delete_piece(e.args["id"], e.args["title"]))

    # Pagination footer.
    with ui.row().classes("w-full items-center justify-center gap-4 mt-2"):
        ui.button(icon="chevron_left", on_click=_prev_page).props("flat dense") \
            .set_enabled(_view["page"] > 0)
        ui.label(
            f"Strona {_view['page'] + 1} / {total_pages}  ({total} utworów)"
        ).classes("text-sm")
        ui.button(icon="chevron_right", on_click=_next_page).props("flat dense") \
            .set_enabled(_view["page"] < total_pages - 1)


def _prev_page() -> None:
    _view["page"] = max(0, _view["page"] - 1)
    _piece_list.refresh()


def _next_page() -> None:
    _view["page"] += 1
    _piece_list.refresh()


def _on_filter_change() -> None:
    """Reset to first page whenever a search/filter value changes."""
    _view["page"] = 0
    _piece_list.refresh()


def _delete_piece(piece_id: int, title: str) -> None:
    """Delete a piece (cascade) after confirmation."""

    def _do_delete() -> None:
        try:
            with get_db_session() as db:
                MusicPieceService.delete_piece(db, piece_id)
                db.commit()
            ui.notify(f"Usunięto: {title}", type="warning")
            _piece_list.refresh()
        except Exception as exc:  # pragma: no cover — UI guard
            logger.exception("Error deleting piece id=%s", piece_id)
            ui.notify(f"Błąd usuwania: {exc}", type="negative")
        dialog.close()

    with ui.dialog() as dialog, ui.card():
        ui.label(f"Usunąć utwór „{title}”? Pliki i historia zostaną skasowane.")
        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Usuń", on_click=_do_delete, color="negative")
    dialog.open()


def _add_piece_form() -> None:
    """Collapsible 'add new piece' form. Mirrors legacy fields + optional upload."""
    inputs: dict = {}
    pending_uploads: list = []

    with ui.expansion("➕ Dodaj nowy utwór", icon="add").classes("w-full"):
        with ui.row().classes("w-full gap-4"):
            with ui.column().classes("flex-1"):
                inputs["title"] = ui.input("Tytuł *").classes("w-full")
                inputs["lyrics_author"] = ui.input("Autor słów").classes("w-full")
                inputs["music_author"] = ui.input("Autor muzyki").classes("w-full")
                inputs["harmony_author"] = ui.input("Autor harmonii").classes("w-full")
            with ui.column().classes("flex-1"):
                inputs["key"] = ui.input("Tonacja", placeholder="np. C-dur, d-moll").classes(
                    "w-full"
                )
                inputs["time"] = ui.input("Metrum", placeholder="np. 4/4, 3/4").classes("w-full")
                inputs["measures"] = ui.number("Ilość taktów", value=0, min=0, precision=0).classes(
                    "w-full"
                )
        inputs["tags"] = ui.input(
            "Tagi (oddzielone przecinkiem)", placeholder="np. uroczyste, tradycyjne"
        ).classes("w-full")

        ui.label("Skan / plik nutowy (opcjonalnie)").classes("text-sm text-grey mt-2")
        ui.upload(
            multiple=True,
            auto_upload=True,
            on_upload=pending_uploads.append,
        ).props('accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp,.mscz,.mscx,.xml,.musicxml"').classes(
            "w-full"
        )

        def _submit() -> None:
            title = (inputs["title"].value or "").strip()
            if not title:
                ui.notify("Tytuł jest wymagany!", type="negative")
                return
            try:
                measures = int(inputs["measures"].value or 0)
                with get_db_session() as db:
                    piece = MusicPieceService.create_piece(
                        db,
                        title=title,
                        lyrics_author=(inputs["lyrics_author"].value or "").strip() or None,
                        music_author=(inputs["music_author"].value or "").strip() or None,
                        harmony_author=(inputs["harmony_author"].value or "").strip() or None,
                        key_signature=(inputs["key"].value or "").strip() or None,
                        time_signature=(inputs["time"].value or "").strip() or None,
                        measures_count=measures if measures > 0 else None,
                    )
                    tags_raw = (inputs["tags"].value or "").strip()
                    if tags_raw:
                        for name in [t.strip() for t in tags_raw.split(",") if t.strip()]:
                            tag = db.query(Tag).filter_by(name=name).first() or Tag(name=name)
                            piece.tags.append(tag)
                    piece_id = piece.id
                    db.commit()
                for upload in pending_uploads:
                    _save_uploaded(piece_id, upload)
                msg = f"Dodano „{title}” (ID {piece_id})."
                if pending_uploads:
                    msg += f" {len(pending_uploads)} plik(ów) — uruchom OCR/OMR w Przetwarzaniu."
                ui.notify(msg, type="positive")
                # Reset the form and refresh the list.
                for k in ("title", "lyrics_author", "music_author", "harmony_author",
                          "key", "time", "tags"):
                    inputs[k].value = ""
                inputs["measures"].value = 0
                pending_uploads.clear()
                _view["page"] = 0
                _piece_list.refresh()
            except Exception as exc:  # pragma: no cover — UI guard
                logger.exception("Error adding music piece")
                ui.notify(f"Błąd dodawania utworu: {exc}", type="negative")

        ui.button("Dodaj utwór", icon="save", on_click=_submit).classes("mt-2")


def render() -> None:
    """Render the whole Biblioteka tab."""
    ui.label("📚 Biblioteka").classes("text-2xl font-bold")

    _add_piece_form()
    ui.separator()

    ui.label("Kolekcja muzyczna").classes("text-lg font-semibold")
    with ui.row().classes("w-full gap-4 items-end"):
        search = ui.input(
            "Szukaj", placeholder="Tytuł, kompozytor, autor słów..."
        ).classes("flex-1")
        search.on(
            "blur", lambda: (_view.update(search=search.value or ""), _on_filter_change())
        )
        search.on(
            "keydown.enter",
            lambda: (_view.update(search=search.value or ""), _on_filter_change()),
        )
        occasion = ui.select(
            OCCASIONS, value="", label="Okazja"
        ).classes("w-48")
        occasion.on_value_change(
            lambda e: (_view.update(occasion=e.value or ""), _on_filter_change())
        )
        season = ui.select(
            SEASONS, value="", label="Okres liturgiczny"
        ).classes("w-48")
        season.on_value_change(
            lambda e: (_view.update(season=e.value or ""), _on_filter_change())
        )

    _piece_list()
