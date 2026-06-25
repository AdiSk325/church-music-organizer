"""Edycja tab — full metadata edit + lyrics/translation editor + step-5 underlay.

Ported from legacy ``src/app/_legacy/main.py``. Network-bound LLM calls
(translation, underlay) run via ``run.io_bound``; each worker opens its own
session. After a save the sibling tabs (Przegląd/Przetwarzanie) are refreshed
via ``state.on_navigate``.
"""

from __future__ import annotations

import contextlib
import logging

from nicegui import run, ui

from src.database import FileType, MusicFileKind, Tag, get_db_session
from src.services import MusicPieceService, PipelineService, ProcessingStepService

from ..shared import is_reference_file, state

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _busy(label: str):
    with ui.dialog().props("persistent") as dialog, ui.card():
        with ui.row().classes("items-center gap-3"):
            ui.spinner(size="lg")
            ui.label(label)
    dialog.open()
    try:
        yield
    finally:
        dialog.close()


def _refresh_siblings() -> None:
    for name, refresh in state.on_navigate.items():
        if name != "edit":
            try:
                refresh()
            except Exception:  # pragma: no cover — UI guard
                pass


# ---------------------------------------------------------------------------
# Worker-thread wrappers
# ---------------------------------------------------------------------------


def _op_translate(piece_id: int, lyrics: str, source_lang: str | None) -> dict:
    from src.llm.translator import translate_to_polish

    tr = translate_to_polish(lyrics, source_language=source_lang)
    with get_db_session() as db:
        MusicPieceService.set_primary_translation_pl(db, piece_id, tr.translation_pl)
        db.commit()
    return {"translation": tr.translation_pl, "notes": tr.notes}


def _op_underlay(piece_id: int, lyrics: str, xml_path: str, xml_id: int) -> dict:
    with get_db_session() as db:
        r = PipelineService().run_step5_underlay(
            db, piece_id, lyrics, xml_path=xml_path, source_file_id=xml_id
        )
        db.commit()
    return r


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------


def _underlay_source(files) -> object | None:
    """Pick the best XML to underlay onto (port of legacy 3-tier priority)."""
    xmls = sorted(
        (f for f in files if f.file_type == FileType.XML), key=lambda x: x.id, reverse=True
    )
    src = next((f for f in xmls if f.kind == MusicFileKind.CORRECTED), None)
    if src is None:
        src = next(
            (f for f in xmls if (f.original_filename or "").lower().startswith("corrected_")), None
        )
    if src is None:
        src = next(
            (
                f
                for f in xmls
                if not is_reference_file(f)
                and f.kind != MusicFileKind.FINAL
                and not (f.original_filename or "").lower().startswith("final_")
            ),
            None,
        )
    return src


def _collect(piece_id: int) -> dict | None:
    with get_db_session() as db:
        piece = MusicPieceService.get_piece(db, piece_id)
        if piece is None:
            return None
        latest = ProcessingStepService.latest_by_key(db, piece_id)
        clean = latest.get("clean_text")
        clean_data = ProcessingStepService.data(clean)
        detected_lang = (clean_data or {}).get("language") or piece.language
        und = _underlay_source(piece.files)
        return {
            "fields": {
                "title": piece.title or "",
                "lyrics_author": piece.lyrics_author or "",
                "music_author": piece.music_author or "",
                "harmony_author": piece.harmony_author or "",
                "composer": piece.composer or "",
                "arranger": piece.arranger or "",
                "key_signature": piece.key_signature or "",
                "time_signature": piece.time_signature or "",
                "measures_count": piece.measures_count or 0,
                "tempo": piece.tempo or "",
                "genre": piece.genre or "",
                "language": piece.language or "",
                "description": piece.description or "",
                "musescore_link": piece.musescore_link or "",
                "notes": piece.notes or "",
            },
            "tags": ", ".join(t.name for t in piece.tags),
            "lyrics": piece.lyrics or "",
            "translation": piece.primary_translation_pl or "",
            "detected_lang": detected_lang,
            "clean_report": clean.report if clean else None,
            "clean_status": (clean.status, clean.detail or "") if clean else None,
            "underlay": {"id": und.id, "path": und.file_path} if und else None,
        }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@ui.refreshable
def _panel() -> None:
    if state.selected_piece_id is None:
        ui.label("Wybierz utwór w Bibliotece, aby edytować.").classes("text-grey italic")
        return

    pid = state.selected_piece_id
    d = _collect(pid)
    if d is None:
        ui.label("Utwór nie istnieje.").classes("text-grey italic")
        return

    ui.label(f"✏️ Edycja — {d['fields']['title']}").classes("text-xl font-bold")

    # --- Full metadata form ---
    f: dict = {}
    with ui.expansion("📝 Metadane", icon="edit", value=True).classes("w-full"):
        with ui.row().classes("w-full gap-4"):
            with ui.column().classes("flex-1"):
                f["title"] = ui.input("Tytuł *", value=d["fields"]["title"]).classes("w-full")
                f["lyrics_author"] = ui.input(
                    "Autor słów", value=d["fields"]["lyrics_author"]
                ).classes("w-full")
                f["music_author"] = ui.input(
                    "Autor muzyki", value=d["fields"]["music_author"]
                ).classes("w-full")
                f["harmony_author"] = ui.input(
                    "Autor harmonii", value=d["fields"]["harmony_author"]
                ).classes("w-full")
                f["composer"] = ui.input("Kompozytor", value=d["fields"]["composer"]).classes(
                    "w-full"
                )
                f["arranger"] = ui.input("Aranżer", value=d["fields"]["arranger"]).classes("w-full")
            with ui.column().classes("flex-1"):
                f["key_signature"] = ui.input(
                    "Tonacja", value=d["fields"]["key_signature"]
                ).classes("w-full")
                f["time_signature"] = ui.input(
                    "Metrum", value=d["fields"]["time_signature"]
                ).classes("w-full")
                f["measures_count"] = ui.number(
                    "Ilość taktów", value=d["fields"]["measures_count"], min=0, precision=0
                ).classes("w-full")
                f["tempo"] = ui.input("Tempo", value=d["fields"]["tempo"]).classes("w-full")
                f["genre"] = ui.input("Gatunek", value=d["fields"]["genre"]).classes("w-full")
                f["language"] = ui.input("Język", value=d["fields"]["language"]).classes("w-full")
        f["description"] = ui.textarea("Opis", value=d["fields"]["description"]).classes("w-full")
        f["musescore_link"] = ui.input(
            "Link MuseScore", value=d["fields"]["musescore_link"]
        ).classes("w-full")
        f["notes"] = ui.textarea("Notatki", value=d["fields"]["notes"]).classes("w-full")
        f["tags"] = ui.input("Tagi (po przecinku)", value=d["tags"]).classes("w-full")

        def _save_meta() -> None:
            title = (f["title"].value or "").strip()
            if not title:
                ui.notify("Tytuł jest wymagany!", type="negative")
                return
            try:
                measures = int(f["measures_count"].value or 0)
                with get_db_session() as db:
                    piece = MusicPieceService.update_piece(
                        db,
                        pid,
                        title=title,
                        lyrics_author=(f["lyrics_author"].value or "").strip() or None,
                        music_author=(f["music_author"].value or "").strip() or None,
                        harmony_author=(f["harmony_author"].value or "").strip() or None,
                        composer=(f["composer"].value or "").strip() or None,
                        arranger=(f["arranger"].value or "").strip() or None,
                        key_signature=(f["key_signature"].value or "").strip() or None,
                        time_signature=(f["time_signature"].value or "").strip() or None,
                        measures_count=measures if measures > 0 else None,
                        tempo=(f["tempo"].value or "").strip() or None,
                        genre=(f["genre"].value or "").strip() or None,
                        language=(f["language"].value or "").strip() or None,
                        description=(f["description"].value or "").strip() or None,
                        musescore_link=(f["musescore_link"].value or "").strip() or None,
                        notes=(f["notes"].value or "").strip() or None,
                    )
                    if piece is not None:
                        piece.tags.clear()
                        tags_raw = (f["tags"].value or "").strip()
                        if tags_raw:
                            for name in [t.strip() for t in tags_raw.split(",") if t.strip()]:
                                tag = db.query(Tag).filter_by(name=name).first() or Tag(name=name)
                                piece.tags.append(tag)
                    db.commit()
                ui.notify("✅ Zapisano zmiany.", type="positive")
                _refresh_siblings()
                _panel.refresh()
            except Exception as exc:  # pragma: no cover — UI guard
                logger.exception("Error saving metadata for piece id=%s", pid)
                ui.notify(f"Błąd zapisu: {exc}", type="negative")

        ui.button("💾 Zapisz metadane", icon="save", on_click=_save_meta).classes("mt-2")

    # --- Lyrics + translation editor ---
    ui.separator()
    ui.label("📜 Tekst pieśni").classes("font-semibold")
    with ui.row().classes("w-full gap-4"):
        orig = (
            ui.textarea("Tekst oryginalny", value=d["lyrics"]).props("autogrow").classes("flex-1")
        )
        transl = (
            ui.textarea("Tłumaczenie (PL)", value=d["translation"])
            .props("autogrow")
            .classes("flex-1")
        )

    def _save_lyrics() -> None:
        try:
            with get_db_session() as db:
                MusicPieceService.update_piece(
                    db,
                    pid,
                    lyrics=(orig.value or "").strip() or None,
                )
                MusicPieceService.set_primary_translation_pl(
                    db, pid, (transl.value or "").strip() or None
                )
                db.commit()
            ui.notify(
                "✅ Teksty zapisane. Możesz ponownie podłożyć tekst (krok 5).", type="positive"
            )
            _refresh_siblings()
            _panel.refresh()
        except Exception as exc:  # pragma: no cover — UI guard
            logger.exception("save lyrics failed")
            ui.notify(f"Błąd zapisu tekstów: {exc}", type="negative")

    llm = PipelineService.llm_available()
    und = d["underlay"]

    async def _translate() -> None:
        async with _busy("Tłumaczenie przez Gemini…"):
            try:
                res = await run.io_bound(_op_translate, pid, d["lyrics"], d["detected_lang"])
            except Exception as exc:  # pragma: no cover — UI guard
                logger.exception("translate_to_polish failed")
                ui.notify(f"Błąd tłumaczenia: {exc}", type="negative")
                return
        if res.get("notes"):
            ui.notify(f"Uwagi tłumacza: {res['notes']}", type="info")
        ui.notify("✅ Tłumaczenie zapisane.", type="positive")
        _refresh_siblings()
        _panel.refresh()

    async def _underlay() -> None:
        async with _busy("Algorytmiczny podkład tekstu pod nuty…"):
            try:
                res = await run.io_bound(_op_underlay, pid, d["lyrics"], und["path"], und["id"])
            except Exception as exc:  # pragma: no cover — UI guard
                logger.exception("standalone underlay failed")
                ui.notify(f"Błąd podkładu tekstu: {exc}", type="negative")
                return
        status = res.get("status")
        msg = res.get("detail", "Podkład tekstu zakończony.")
        ui.notify(
            ("✅ " if status == "ok" else "") + msg,
            type="positive" if status == "ok" else "warning",
        )
        _refresh_siblings()
        _panel.refresh()

    with ui.row().classes("gap-2 flex-wrap mt-2"):
        ui.button("💾 Zapisz teksty", icon="save", on_click=_save_lyrics)
        ui.button("🎶 Podłóż tekst do nut (krok 5)", on_click=_underlay).props("flat").set_enabled(
            bool(d["lyrics"].strip()) and und is not None
        )
        translate_label = (
            "🔁 Przetłumacz ponownie" if d["translation"] else "🌐 Przetłumacz na polski (Gemini)"
        )
        ui.button(translate_label, on_click=_translate).props("flat").set_enabled(
            bool(d["lyrics"].strip()) and llm
        )

    if d["clean_report"]:
        with ui.expansion("🧹 Raport czyszczenia tekstu (LLM)").classes("w-full"):
            if d["clean_status"]:
                ui.label(f"Status: {d['clean_status'][0]} · {d['clean_status'][1]}").classes(
                    "text-xs text-grey"
                )
            ui.markdown(d["clean_report"])


def render() -> None:
    state.on_navigate["edit"] = _panel.refresh
    _panel()
