"""Przegląd tab — read-only overview of the selected piece.

Ported from legacy ``src/app/_legacy/main.py`` (description/metadata, analysis
panel, PDF/scan preview, MusicXML downloads, MuseScore, usage history). All ORM
access is materialised into plain dicts inside the session so the panel can
render after the session closes (no lazy-load DetachedInstanceError).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from nicegui import ui

from src.database import FileType, MusicFileKind, UsageHistory, get_db_session
from src.services import MusicPieceService, ProcessingStepService

from ..files import open_in_app
from ..shared import is_reference_file, resolve_xml_kind, state

logger = logging.getLogger(__name__)

# Stable display order of the XML kinds (OMR → korekta → finalny).
_KIND_ORDER = ["📄 OMR (surowy)", "🛠️ Korekta partytury", "🎶 Finalny (z tekstem)"]


def _render_analysis(data: dict) -> None:
    """Render the ScoreDescriptor (analysis step ``data_json``). Port of legacy."""
    if not data:
        return
    with ui.row().classes("w-full gap-8"):
        with ui.column().classes("flex-1"):
            key = data.get("detected_key") or "—"
            conf = data.get("key_confidence")
            conf_txt = f" (pewność {conf:.0%})" if isinstance(conf, (int, float)) else ""
            ui.label(f"Tonacja: {key}{conf_txt}")
            ui.label(f"Tryb: {data.get('mode') or '—'}")
            ui.label(f"Metrum: {', '.join(data.get('time_signatures') or []) or '—'}")
            ui.label(f"Faktura: {data.get('texture_type') or '—'}")
            ui.label(f"Epoka harmoniczna: {data.get('harmony_epoch') or '—'}")
        with ui.column().classes("flex-1"):
            voices = ", ".join(data.get("voice_names") or []) or "—"
            ui.label(f"Głosy ({data.get('voice_count') or 0}): {voices}")
            ui.label(f"Forma: {data.get('form_type') or '—'}")
            grade = data.get("grade_label") or "—"
            ui.label(f"Trudność: {grade} (grade {data.get('estimated_grade') or '—'})")
            chrom = data.get("chromatic_complexity")
            if isinstance(chrom, (int, float)):
                ui.label(f"Złożoność chromatyczna: {chrom:.2f}")
            ui.label(f"Tekst: {data.get('text_setting_type') or '—'}")

    ranges = data.get("voice_ranges") or []
    factors = data.get("difficulty_factors") or []
    if ranges or factors:
        with ui.expansion("🔬 Szczegóły analizy").classes("w-full"):
            for vr in ranges:
                ui.label(
                    f"• {vr.get('name', '?')}: {vr.get('lowest_pitch', '?')}–"
                    f"{vr.get('highest_pitch', '?')} "
                    f"(zakres {vr.get('range_semitones', '?')} półtonów)"
                ).classes("text-sm")
            if factors:
                ui.label("Czynniki trudności: " + ", ".join(factors)).classes("text-sm")


def _pdf_preview(file_id: int) -> None:
    """Embed a PDF via the /file/<id> endpoint (browser-native inline rendering)."""
    ui.html(
        f'<iframe src="/file/{file_id}#view=FitH" width="100%" height="600" '
        f'style="border:none"></iframe>'
    ).classes("w-full")


def _collect(piece_id: int) -> dict | None:
    """Gather everything the panel needs into plain structures (inside session)."""
    with get_db_session() as db:
        piece = MusicPieceService.get_piece(db, piece_id)
        if piece is None:
            return None
        latest = ProcessingStepService.latest_by_key(db, piece_id)
        analysis_step = latest.get("analysis")
        analysis_data = ProcessingStepService.data(analysis_step)
        provenance = {s.output_file_id: s.step_label for s in latest.values() if s.output_file_id}
        files = [
            {
                "id": f.id,
                "name": f.original_filename,
                "path": f.file_path,
                "type": f.file_type,
                "kind": f.kind,
                "version": f.version,
                "created_at": f.created_at,
                "description": f.description,
                "xml_kind": resolve_xml_kind(f) if f.file_type == FileType.XML else None,
                "is_ref": is_reference_file(f),
            }
            for f in piece.files
        ]
        return {
            "title": piece.title,
            "lyrics_author": piece.lyrics_author,
            "music_author": piece.music_author,
            "harmony_author": piece.harmony_author,
            "composer": piece.composer,
            "arranger": piece.arranger,
            "key": piece.key_signature,
            "time": piece.time_signature,
            "measures": piece.measures_count,
            "tempo": piece.tempo,
            "genre": piece.genre,
            "language": piece.language,
            "description": piece.description,
            "notes": piece.notes,
            "musescore_link": piece.musescore_link,
            "tags": [t.name for t in piece.tags],
            "files": files,
            "analysis_data": analysis_data,
            "analysis_report": analysis_step.report if analysis_step else None,
            "provenance": provenance,
            "usage": sorted(
                (
                    {
                        "date": u.usage_date,
                        "event": u.event_name,
                        "notes": u.notes,
                    }
                    for u in piece.usage_history
                ),
                key=lambda u: u["date"],
                reverse=True,
            ),
        }


@ui.refreshable
def _panel() -> None:
    if state.selected_piece_id is None:
        ui.label("Wybierz utwór w Bibliotece, aby zobaczyć szczegóły.").classes("text-grey italic")
        return

    d = _collect(state.selected_piece_id)
    if d is None:
        ui.label("Utwór nie istnieje (mógł zostać usunięty).").classes("text-grey italic")
        return

    ui.label(f"🎵 {d['title']}").classes("text-2xl font-bold")

    # --- Metadata ---
    with ui.row().classes("w-full gap-8"):
        with ui.column().classes("flex-1"):
            ui.label(f"Autor słów: {d['lyrics_author'] or '—'}")
            ui.label(f"Autor muzyki: {d['music_author'] or '—'}")
            ui.label(f"Autor harmonii: {d['harmony_author'] or '—'}")
            if d["composer"]:
                ui.label(f"Kompozytor: {d['composer']}")
            if d["arranger"]:
                ui.label(f"Aranżer: {d['arranger']}")
        with ui.column().classes("flex-1"):
            ui.label(f"Tonacja: {d['key'] or '—'}")
            ui.label(f"Metrum: {d['time'] or '—'}")
            ui.label(f"Liczba taktów: {d['measures'] or '—'}")
            if d["tempo"]:
                ui.label(f"Tempo: {d['tempo']}")
            if d["genre"]:
                ui.label(f"Gatunek: {d['genre']}")
            if d["language"]:
                ui.label(f"Język: {d['language']}")
    if d["description"]:
        ui.label(f"Opis: {d['description']}")
    if d["notes"]:
        ui.label(f"Notatki: {d['notes']}")
    ui.label(f"Tagi: {', '.join(d['tags']) or '—'}")

    # --- Analysis ---
    if d["analysis_data"]:
        ui.separator()
        ui.label("🔎 Analiza muzyczna (automatyczna)").classes("font-semibold")
        _render_analysis(d["analysis_data"])
        if d["analysis_report"]:
            ui.label(d["analysis_report"]).classes("text-xs text-grey")

    # --- PDF / scan preview ---
    ui.separator()
    ui.label("📄 Podgląd skanu / PDF").classes("font-semibold")
    pdfs = [f for f in d["files"] if f["type"] == FileType.PDF]
    scans = [f for f in d["files"] if f["type"] == FileType.SCAN]
    if pdfs:
        for f in pdfs:
            ui.label(f["name"]).classes("text-sm")
            p = Path(f["path"])
            if p.exists():
                _pdf_preview(f["id"])
            else:
                ui.label(f"Brak pliku na dysku: {f['path']}").classes("text-warning text-sm")
    elif scans:
        for f in scans:
            ui.label(f["name"]).classes("text-sm")
            p = Path(f["path"])
            if p.exists():
                ui.image(f"/file/{f['id']}").classes("max-w-2xl")
            else:
                ui.label(f"Brak pliku na dysku: {f['path']}").classes("text-warning text-sm")
    else:
        ui.label("Brak plików PDF / skanów dla tego utworu.").classes("text-grey text-sm")

    # --- Generated MusicXML (freshest per kind) ---
    xml_files = [f for f in d["files"] if f["type"] == FileType.XML and not f["is_ref"]]
    if xml_files:
        ui.separator()
        ui.label("🎼 Aktualne pliki MusicXML (najnowsze wersje)").classes("font-semibold")
        newest_per_kind: dict = {}
        for f in xml_files:
            k = f["xml_kind"]
            cur = newest_per_kind.get(k)
            if cur is None or f["id"] > cur["id"]:
                newest_per_kind[k] = f
        for kind in [k for k in _KIND_ORDER if k in newest_per_kind]:
            f = newest_per_kind[kind]
            ver = f"v{f['version']}" if f["version"] else "—"
            when = f["created_at"].strftime("%Y-%m-%d %H:%M") if f["created_at"] else "—"
            with ui.row().classes("items-center gap-3"):
                ui.label(f"{kind} · {ver} · 🕒 {when}").classes("text-sm")
                prov = d["provenance"].get(f["id"])
                if prov:
                    ui.label(f"↳ {prov}").classes("text-xs text-grey")
                p = Path(f["path"])
                if p.exists():
                    ui.button(
                        "📂 Otwórz",
                        on_click=lambda pa=str(p): open_in_app(pa),
                    ).props("flat dense")
                    ui.button(
                        icon="download",
                        on_click=lambda pa=str(p), na=f["name"]: ui.download.file(pa, na),
                    ).props("flat dense").tooltip("Pobierz")
                else:
                    ui.label("brak pliku na dysku").classes("text-warning text-xs")

    # --- MuseScore ---
    ms_files = [f for f in d["files"] if f["type"] == FileType.MUSESCORE]
    if d["musescore_link"] or ms_files:
        ui.separator()
        ui.label("🎼 MuseScore").classes("font-semibold")
        if d["musescore_link"]:
            ui.link("Otwórz w MuseScore", d["musescore_link"], new_tab=True)
        for f in ms_files:
            p = Path(f["path"])
            if p.exists():
                with ui.row().classes("items-center gap-2"):
                    ui.button(
                        "📂 Otwórz w MuseScore",
                        on_click=lambda pa=str(p): open_in_app(pa),
                    ).props("flat dense")
                    ui.button(
                        icon="download",
                        on_click=lambda pa=str(p), na=f["name"]: ui.download.file(pa, na),
                    ).props("flat dense").tooltip("Pobierz")
            else:
                ui.label(f"Brak pliku na dysku: {f['path']}").classes("text-warning text-sm")

    # --- Usage history ---
    ui.separator()
    ui.label("📅 Historia wykonań").classes("font-semibold")
    if d["usage"]:
        for u in d["usage"]:
            parts = [f"**{u['date'].strftime('%Y-%m-%d')}**"]
            if u["event"]:
                parts.append(f"— {u['event']}")
            if u["notes"]:
                parts.append(f"({u['notes']})")
            ui.markdown("- " + " ".join(parts))
    else:
        ui.label("Brak zarejestrowanych wykonań.").classes("text-grey text-sm")
    _add_usage_form()


def _add_usage_form() -> None:
    pid = state.selected_piece_id
    with ui.expansion("➕ Dodaj wykonanie", icon="event").classes("w-full"):
        date_in = ui.input("Data", value=datetime.now().strftime("%Y-%m-%d")).classes("w-48")
        with date_in.add_slot("append"):
            ui.icon("event").on("click", lambda: menu.open()).classes("cursor-pointer")
        with ui.menu() as menu:
            ui.date().bind_value(date_in)
        event_in = ui.input("Nazwa wydarzenia", placeholder="np. Msza niedzielna, Ślub").classes(
            "w-full"
        )
        notes_in = ui.input("Notatki (opcjonalnie)").classes("w-full")

        def _add() -> None:
            try:
                dt = datetime.strptime((date_in.value or "").strip(), "%Y-%m-%d")
            except ValueError:
                ui.notify("Niepoprawna data (format RRRR-MM-DD).", type="negative")
                return
            try:
                with get_db_session() as db:
                    db.add(
                        UsageHistory(
                            music_piece_id=pid,
                            usage_date=dt,
                            event_name=(event_in.value or "").strip() or None,
                            notes=(notes_in.value or "").strip() or None,
                        )
                    )
                    db.commit()
                ui.notify("Dodano wykonanie.", type="positive")
                _panel.refresh()
            except Exception as exc:  # pragma: no cover — UI guard
                logger.exception("Error adding usage history")
                ui.notify(f"Błąd: {exc}", type="negative")

        ui.button("Dodaj", icon="save", on_click=_add).classes("mt-2")


def render() -> None:
    state.on_navigate["detail"] = _panel.refresh
    _panel()
