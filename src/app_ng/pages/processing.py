"""Przetwarzanie tab — OMR/OCR/LLM pipeline + reference comparison.

Ported from legacy ``src/app/_legacy/main.py``. Long-blocking engine work runs
off the event loop via ``run.io_bound`` (each wrapper opens its own DB session
inside the worker thread). The full-pipeline progress bar is driven by a
``ui.timer`` that polls a shared ``_run_state`` mutated by the on_progress
callback — safe across threads (no UI calls from the worker).
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path

from nicegui import run, ui

from src.database import FileType, MusicFile, MusicFileKind, MusicPiece, get_db_session
from src.evaluation.reference_compare import compare_musicxml
from src.services import (
    FileService,
    MusicPieceService,
    OCRService,
    OMRService,
    PipelineService,
    ProcessingStepService,
)
from src.services.pipeline_service import STEP_LABELS, STEP_SEQUENCE

from ..shared import get_file_type, is_reference_file, state

logger = logging.getLogger(__name__)

_STATUS_ICON = {"ok": "✅", "skipped": "⏭️", "error": "❌"}


def _file_kind_for_upload(filename: str) -> MusicFileKind:
    """Map an uploaded filename to the appropriate semantic MusicFileKind.

    PDF and image scans are source material; MuseScore files are editable scores;
    XML/MusicXML uploaded by the user are treated as raw OMR output.
    """
    file_type = get_file_type(filename)
    if file_type == FileType.PDF:
        return MusicFileKind.SOURCE_PDF
    if file_type == FileType.SCAN:
        return MusicFileKind.SOURCE_SCAN
    if file_type == FileType.MUSESCORE:
        return MusicFileKind.EDITABLE
    if file_type == FileType.XML:
        return MusicFileKind.OMR_RAW
    return MusicFileKind.OTHER


_ETA_FALLBACK_S = {
    "ocr": 5,
    "metadata": 8,
    "clean_text": 8,
    "omr": 90,
    "correct_score": 20,
    "underlay": 15,
}
_PIPELINE_STEP_KEYS = ["ocr", "metadata", "clean_text", "omr", "correct_score", "underlay"]
_LABEL_TO_KEY = {v: k for k, v in STEP_LABELS.items() if k in _PIPELINE_STEP_KEYS}

# Mutated by the worker-thread progress callback; polled by a ui.timer.
_run_state: dict = {"done": 0, "total": 6, "last": "", "remaining": [], "t0": 0.0, "est": {}}


def _fmt(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


# ---------------------------------------------------------------------------
# Worker-thread wrappers (each opens its own session; return plain dicts).
# ---------------------------------------------------------------------------


def _op_full(file_id: int) -> None:
    with get_db_session() as db:
        PipelineService().run_full(db, file_id, on_progress=_on_progress)
        db.commit()


def _op_ocr(file_id: int) -> dict:
    with get_db_session() as db:
        r = PipelineService().run_step1_ocr(db, file_id)
        db.commit()
    return r


def _op_omr(file_id: int) -> dict:
    with get_db_session() as db:
        r = PipelineService().run_step3_omr(db, file_id)
        db.commit()
    return r


def _op_clean(piece_id: int, text: str, file_id: int) -> dict:
    with get_db_session() as db:
        r = PipelineService().run_step2_clean_text(db, piece_id, text, source_file_id=file_id)
        db.commit()
    return r


def _op_metadata(piece_id: int, text: str, file_id: int) -> dict:
    with get_db_session() as db:
        r = PipelineService().run_step_metadata(db, piece_id, text, source_file_id=file_id)
        db.commit()
    return r


def _op_correct_underlay(piece_id: int, xml_path: str, xml_id: int, lyrics: str) -> dict:
    with get_db_session() as db:
        svc = PipelineService()
        r4 = svc.run_step4_correct_score(db, piece_id, xml_path, source_file_id=xml_id)
        underlaid = False
        if r4.get("status") == "ok" and (lyrics or "").strip():
            svc.run_step5_underlay(
                db,
                piece_id,
                lyrics,
                xml_path=xml_path,
                xml_content=r4.get("musicxml"),
                source_file_id=xml_id,
            )
            underlaid = True
        db.commit()
    return {"r4": r4, "underlaid": underlaid, "had_lyrics": bool((lyrics or "").strip())}


def _estimates(piece_id: int) -> dict:
    est: dict = {}
    with get_db_session() as db:
        for sk in _PIPELINE_STEP_KEYS:
            durs = [
                s.duration_ms
                for s in ProcessingStepService.history(db, piece_id, sk)
                if s.duration_ms
            ]
            est[sk] = (sum(durs) / len(durs) / 1000) if durs else _ETA_FALLBACK_S.get(sk, 10)
    return est


def _on_progress(name: str, status: str) -> None:
    """Runs in the worker thread — only mutate ``_run_state`` (no UI calls)."""
    _run_state["done"] += 1
    key = _LABEL_TO_KEY.get(name)
    if key and key in _run_state["remaining"]:
        _run_state["remaining"].remove(key)
    elapsed = time.perf_counter() - _run_state["t0"]
    eta = sum(_run_state["est"].get(k, 10) for k in _run_state["remaining"])
    icon = _STATUS_ICON.get(status, "•")
    _run_state["last"] = f"{icon} {name} — {status} | upłynęło {_fmt(elapsed)}, ETA ~{_fmt(eta)}"


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


# ---------------------------------------------------------------------------
# Async UI handlers
# ---------------------------------------------------------------------------


async def _run_full(piece_id: int, file_id: int, title: str) -> None:
    _run_state.update(
        done=0,
        total=6,
        last="Uruchamiam pipeline…",
        remaining=list(_PIPELINE_STEP_KEYS),
        t0=time.perf_counter(),
        est=_estimates(piece_id),
    )
    with ui.dialog().props("persistent") as dialog, ui.card().classes("w-96"):
        ui.label(f"Pełny pipeline: {title}").classes("font-bold")
        bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full")
        status_lbl = ui.label(_run_state["last"]).classes("text-sm")
    dialog.open()

    def _tick() -> None:
        bar.value = min(_run_state["done"] / _run_state["total"], 1.0)
        status_lbl.text = _run_state["last"]

    timer = ui.timer(0.3, _tick)
    try:
        await run.io_bound(_op_full, file_id)
        ui.notify("✅ Pełny pipeline zakończony — wyniki poniżej.", type="positive")
    except Exception as exc:  # pragma: no cover — UI guard
        logger.exception("Pipeline failed for file_id=%s", file_id)
        ui.notify(f"Błąd pipeline: {exc}", type="negative")
    finally:
        timer.cancel()
        dialog.close()
        _panel.refresh()


async def _run_single(label: str, fn, *args, ok_msg: str = "Gotowe.") -> None:
    async with _busy(label):
        try:
            result = await run.io_bound(fn, *args)
        except Exception as exc:  # pragma: no cover — UI guard
            logger.exception("Step failed: %s", label)
            ui.notify(f"Błąd: {exc}", type="negative")
            return
    status = result.get("status") if isinstance(result, dict) else "ok"
    if status == "ok":
        detail = result.get("detail", "") if isinstance(result, dict) else ""
        ui.notify(f"✅ {ok_msg} {detail}".strip(), type="positive")
    elif status == "skipped":
        ui.notify(result.get("detail", "Pominięto."), type="warning")
    else:
        ui.notify(result.get("detail", "Błąd kroku."), type="negative")
    _panel.refresh()


async def _run_correct(piece_id: int, xml_path: str, xml_id: int, lyrics: str) -> None:
    async with _busy("Korekta partytury (LLM) + algorytmiczny podkład tekstu…"):
        try:
            res = await run.io_bound(_op_correct_underlay, piece_id, xml_path, xml_id, lyrics)
        except Exception as exc:  # pragma: no cover — UI guard
            logger.exception("score correct/underlay failed")
            ui.notify(f"Błąd korekty/podkładu: {exc}", type="negative")
            return
    msg = "✅ Korekta partytury zakończona."
    if not res["had_lyrics"]:
        msg += " Podkład pominięto — brak tekstu (oczyść tekst lub uzupełnij w Edycji)."
    ui.notify(msg, type="positive")
    _panel.refresh()


# ---------------------------------------------------------------------------
# Data gathering + rendering
# ---------------------------------------------------------------------------


def _collect(piece_id: int) -> dict | None:
    with get_db_session() as db:
        piece = MusicPieceService.get_piece(db, piece_id)
        if piece is None:
            return None
        latest = ProcessingStepService.latest_by_key(db, piece_id)
        steps = []
        for key in STEP_SEQUENCE:
            step = latest.get(key)
            label = STEP_LABELS.get(key, key)
            if step is None:
                steps.append(("⬜", label, "nie uruchomiono", None))
            else:
                steps.append(
                    (
                        _STATUS_ICON.get(step.status, "•"),
                        label,
                        step.detail or "",
                        step.report,
                    )
                )
        # XML for correct/underlay: newest non-reference, non-final.
        xml_for_correct = next(
            (
                f
                for f in reversed(piece.files)
                if f.file_type == FileType.XML and not is_reference_file(f)
            ),
            None,
        )
        return {
            "title": piece.title,
            "lyrics": piece.lyrics or "",
            "steps": steps,
            "sources": [
                {
                    "id": f.id,
                    "name": f.original_filename,
                    "has_text": bool(f.extracted_text),
                    "text": f.extracted_text,
                }
                for f in piece.files
                if f.file_type in (FileType.PDF, FileType.SCAN)
            ],
            "xml_correct": (
                {"id": xml_for_correct.id, "path": xml_for_correct.file_path}
                if xml_for_correct
                else None
            ),
            "xml_all": sorted(
                (
                    {
                        "id": f.id,
                        "name": f.original_filename,
                        "path": f.file_path,
                        "desc": f.description or "",
                        "is_ref": is_reference_file(f),
                    }
                    for f in piece.files
                    if f.file_type == FileType.XML
                ),
                key=lambda x: x["id"],
            ),
        }


def _badges() -> None:
    with ui.row().classes("w-full gap-2 items-center"):
        for name, ok in (
            ("Audiveris (OMR)", OMRService.is_available()),
            ("Tesseract (OCR)", OCRService.is_available()),
            ("Gemini (LLM)", PipelineService.llm_available()),
        ):
            color = "positive" if ok else "warning"
            ui.badge(f"{'✅' if ok else '⚠️'} {name}").props(f"color={color}").classes(
                "p-2 text-sm"
            )


async def _upload_source(piece_id: int, e) -> None:
    """Save an uploaded source file (PDF / scan) to the piece's library folder."""
    data = e.content.read()
    kind = _file_kind_for_upload(e.name)
    with get_db_session() as db:
        piece = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            ui.notify("Nie znaleziono utworu.", type="negative")
            return
        path = FileService.save_uploaded_file(
            piece_id=piece_id,
            filename=e.name,
            file_data=data,
            use_library=True,
            piece=piece,
            kind=kind,
        )
        db.add(
            MusicFile(
                music_piece_id=piece_id,
                file_path=path,
                file_type=get_file_type(e.name),
                original_filename=e.name,
                file_size=len(data),
                kind=kind,
            )
        )
        db.commit()
    ui.notify(f"Wgrano: {e.name}", type="positive")
    _panel.refresh()


@ui.refreshable
def _panel() -> None:
    _badges()
    ui.separator()

    if state.selected_piece_id is None:
        ui.label("Wybierz utwór w Bibliotece, aby uruchomić przetwarzanie.").classes(
            "text-grey italic"
        )
        return

    pid = state.selected_piece_id
    d = _collect(pid)
    if d is None:
        ui.label("Utwór nie istnieje.").classes("text-grey italic")
        return

    ui.label(f"🎼 Przetwarzanie — {d['title']}").classes("text-xl font-bold")

    # --- Status panel ---
    ui.label("🔄 Status pipeline'u:").classes("font-semibold mt-2")
    for icon, label, detail, report in d["steps"]:
        ui.label(f"{icon} {label} — {detail}").classes("text-sm")
        if report:
            with ui.expansion(f"📋 Raport: {label}").classes("w-full"):
                ui.markdown(report)

    # --- OCR text per source ---
    for s in d["sources"]:
        if s["has_text"]:
            with ui.expansion(f"📄 Tekst OCR — {s['name']}").classes("w-full"):
                ui.textarea(value=s["text"]).props("readonly autogrow").classes("w-full")

    ui.separator()

    # --- Source upload ---
    with ui.expansion("📤 Wgraj plik źródłowy (PDF / skan)", icon="upload").classes("w-full"):
        ui.upload(
            multiple=True,
            auto_upload=True,
            on_upload=lambda e: _upload_source(pid, e),
        ).props('accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp"').classes("w-full")

    # --- Processing buttons per source ---
    llm = PipelineService.llm_available()
    ocr_ok = OCRService.is_available()
    omr_ok = OMRService.is_available()
    if not d["sources"]:
        ui.label("Brak plików PDF / skanów. Wgraj plik powyżej.").classes("text-grey text-sm")
    for s in d["sources"]:
        with ui.card().classes("w-full"):
            ui.label(f"📄 {s['name']}").classes("font-medium")
            with ui.row().classes("gap-2 flex-wrap"):
                ui.button(
                    "🤖 Pełny pipeline (1→5)",
                    on_click=lambda sid=s["id"]: _run_full(pid, sid, d["title"]),
                ).props("color=primary").set_enabled(ocr_ok or omr_ok)
                ui.button(
                    "🎼 OMR → MusicXML",
                    on_click=lambda sid=s["id"]: _run_single(
                        "Konwersja PDF→MusicXML (Audiveris)…",
                        _op_omr,
                        sid,
                        ok_msg="OMR zakończony.",
                    ),
                ).props("flat").set_enabled(omr_ok)
                ui.button(
                    "📝 OCR → tekst",
                    on_click=lambda sid=s["id"]: _run_single(
                        "Ekstrakcja tekstu (Tesseract)…",
                        _op_ocr,
                        sid,
                        ok_msg="OCR zakończony.",
                    ),
                ).props("flat").set_enabled(ocr_ok)
                ui.button(
                    "🧹 Oczyść tekst (LLM)",
                    on_click=lambda sid=s["id"], tx=s["text"]: _run_single(
                        "Czyszczenie tekstu (Gemini)…",
                        _op_clean,
                        pid,
                        tx or "",
                        sid,
                        ok_msg="Tekst oczyszczony.",
                    ),
                ).props("flat").set_enabled(llm and s["has_text"])
                ui.button(
                    "🏷️ Metadane (LLM)",
                    on_click=lambda sid=s["id"], tx=s["text"]: _run_single(
                        "Ekstrakcja metadanych (Gemini)…",
                        _op_metadata,
                        pid,
                        tx or "",
                        sid,
                        ok_msg="Metadane zaktualizowane.",
                    ),
                ).props("flat").set_enabled(llm and s["has_text"])
                _xc = d["xml_correct"]
                ui.button(
                    "🎶 Korekta (LLM) + podkład",
                    on_click=lambda: (
                        _run_correct(pid, _xc["path"], _xc["id"], d["lyrics"]) if _xc else None
                    ),
                ).props("flat").set_enabled(llm and _xc is not None)

    # --- Reference comparison ---
    ui.separator()
    _comparison(pid, d["xml_all"])


def _comparison(piece_id: int, xml_all: list) -> None:
    ui.label("📊 Porównanie z referencją (metryki)").classes("font-semibold")
    refs = [f for f in xml_all if f["is_ref"]]
    cands = [f for f in xml_all if not f["is_ref"]]

    with ui.expansion("📂 Wgraj plik referencyjny (target MusicXML)", icon="upload").classes(
        "w-full"
    ):

        async def _save_ref(e) -> None:
            """Save a reference MusicXML into the piece's library ``scores/`` folder."""
            data = e.content.read()
            with get_db_session() as db:
                piece = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
                if piece is None:
                    ui.notify("Nie znaleziono utworu.", type="negative")
                    return
                path = FileService.save_uploaded_file(
                    piece_id=piece_id,
                    filename=e.name,
                    file_data=data,
                    use_library=True,
                    piece=piece,
                    kind=MusicFileKind.REFERENCE,
                )
                db.add(
                    MusicFile(
                        music_piece_id=piece_id,
                        file_path=path,
                        file_type=FileType.XML,
                        original_filename=e.name,
                        file_size=len(data),
                        kind=MusicFileKind.REFERENCE,
                        description=f"[REFERENCJA] {e.name}",
                    )
                )
                db.commit()
            ui.notify(f"Zapisano referencję: {e.name}", type="positive")
            _panel.refresh()

        ui.upload(
            auto_upload=True,
            on_upload=_save_ref,
        ).props(
            'accept=".musicxml,.mxl,.xml"'
        ).classes("w-full")

    if not xml_all:
        ui.label("Brak plików MusicXML. Uruchom OMR lub wgraj referencję.").classes(
            "text-grey text-sm"
        )
        return

    def _flabel(f: dict) -> str:
        d = f["desc"][:50]
        return f"[{f['id']}] {f['name']}" + (f" — {d}" if d else "")

    cand_opts = {_flabel(f): f for f in cands}
    ref_opts = {_flabel(f): f for f in refs}
    if not cand_opts or not ref_opts:
        ui.label("Wymagany co najmniej jeden plik kandydata i jeden referencyjny.").classes(
            "text-grey text-sm"
        )
        return

    cand_sel = ui.select(
        list(cand_opts), value=list(cand_opts)[-1], label="Plik wygenerowany (kandydat)"
    ).classes("w-full")
    ref_sel = ui.select(
        list(ref_opts), value=list(ref_opts)[-1], label="Plik referencyjny (target)"
    ).classes("w-full")
    result_area = ui.column().classes("w-full")

    async def _compare() -> None:
        cf = cand_opts.get(cand_sel.value)
        rf = ref_opts.get(ref_sel.value)
        result_area.clear()
        if not cf or not rf:
            return
        async with _busy("Porównuję pliki MusicXML…"):
            res = await run.io_bound(compare_musicxml, rf["path"], cf["path"])
        with result_area:
            _render_comparison(res)

    ui.button("📊 Porównaj", icon="compare", on_click=_compare).classes("mt-2")


def _render_comparison(res: dict) -> None:
    if "error" in res:
        ui.label(f"Błąd porównania: {res['error']}").classes("text-negative")
        return
    r, c = res["ref"], res["conv"]
    ok, nok = "✅", "❌"
    recall, ratio = res["note_recall"], res["note_ratio"]
    recall_icon = ok if recall >= 0.9 else ("⚠️" if recall >= 0.7 else nok)
    ratio_icon = ok if 0.9 <= ratio <= 1.1 else nok
    rows = [
        {
            "m": "Poprawny MusicXML",
            "ref": "—",
            "cand": "tak" if res["valid_musicxml"] else "NIE",
            "res": ok if res["valid_musicxml"] else nok,
        },
        {
            "m": "Recall nut",
            "ref": str(r["notes"]),
            "cand": str(c["notes"]),
            "res": f"{recall:.1%} {recall_icon}",
        },
        {
            "m": "Stosunek nut (>1 = nadmiar)",
            "ref": str(r["notes"]),
            "cand": str(c["notes"]),
            "res": f"{ratio:.2f} {ratio_icon}",
        },
        {
            "m": "Takty",
            "ref": str(r["measures"]),
            "cand": str(c["measures"]),
            "res": f"{ok} zgodne (±1)" if res["measure_match"] else f"{nok} różne",
        },
        {
            "m": "Partie / głosy",
            "ref": str(r["parts"]),
            "cand": str(c["parts"]),
            "res": f"{ok} zgodne" if res["part_match"] else f"{nok} różne",
        },
        {
            "m": "Tonacja (kwinty)",
            "ref": str(r["fifths"]) if r["fifths"] is not None else "—",
            "cand": str(c["fifths"]) if c["fifths"] is not None else "—",
            "res": f"{ok} zgodna" if res["key_match"] else f"{nok} różna",
        },
        {
            "m": "Metrum",
            "ref": str(r["first_ts"] or "—"),
            "cand": str(c["first_ts"] or "—"),
            "res": f"{ok} zgodne" if res["ts_match"] else f"{nok} różne",
        },
    ]
    ui.table(
        columns=[
            {"name": "m", "label": "Metryka", "field": "m", "align": "left"},
            {"name": "ref", "label": "Referencja", "field": "ref", "align": "right"},
            {"name": "cand", "label": "Kandydat", "field": "cand", "align": "right"},
            {"name": "res", "label": "Wynik", "field": "res", "align": "left"},
        ],
        rows=rows,
    ).classes("w-full")
    ui.label(f"OVERALL (0–1): {res['overall_score']:.3f}").classes("text-lg font-bold")
    if res.get("valid_reason"):
        ui.label(f"Walidacja: {res['valid_reason']}").classes("text-xs text-grey")


def render() -> None:
    state.on_navigate["processing"] = _panel.refresh
    _panel()
