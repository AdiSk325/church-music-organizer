"""Streamlit application for church music organizer."""

import base64
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import func  # noqa: F401 — kept for future use

from src.database import FileType, MusicFile, MusicPiece, Tag, UsageHistory, get_db_session, init_db
from src.services import (
    FileService,
    OCRService,
    OMRService,
    PipelineService,
    ProcessingStepService,
)
from src.evaluation.reference_compare import compare_musicxml
from src.llm.translator import translate_to_polish
from src.services.pipeline_service import STEP_LABELS, STEP_SEQUENCE

logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(page_title="Church Music Organizer", page_icon="🎵", layout="wide")

# Initialize database
init_db()


# ---------------------------------------------------------------------------
# Liturgical domain constants
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


# ---------------------------------------------------------------------------
# Query helper — replace body with MusicPieceService.list() when ready
# ---------------------------------------------------------------------------


def query_pieces(
    db,
    search: str = "",
    occasion: str = "",
    season: str = "",
    page: int = 0,
    per_page: int = PER_PAGE,
):
    """Centralna funkcja zapytań — łatwa do zastąpienia serwisem."""
    q = db.query(MusicPiece)
    if search:
        term = f"%{search}%"
        q = q.filter(
            MusicPiece.title.ilike(term)
            | MusicPiece.composer.ilike(term)
            | MusicPiece.lyrics_author.ilike(term)
        )
    if occasion:
        q = q.filter(MusicPiece.occasion == occasion)
    if season:
        q = q.filter(MusicPiece.liturgical_season == season)
    total = q.count()
    items = q.order_by(MusicPiece.created_at.desc()).offset(page * per_page).limit(per_page).all()
    return items, total


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def save_uploaded_file(uploaded_file, music_piece_id: int) -> str:
    """Save uploaded file via FileService (sanitised path) and return the path."""
    return FileService.save_uploaded_file(
        piece_id=music_piece_id,
        filename=uploaded_file.name,
        file_data=uploaded_file.getbuffer(),
    )


def get_file_type(filename: str) -> FileType:
    """Determine file type from filename."""
    ext = Path(filename).suffix.lower()

    if ext in [".mscz", ".mscx"]:
        return FileType.MUSESCORE
    elif ext == ".pdf":
        return FileType.PDF
    elif ext in [".xml", ".musicxml"]:
        return FileType.XML
    elif ext in [".txt", ".ly"]:
        return FileType.TEXT
    elif ext in [".jpg", ".jpeg", ".png", ".tiff", ".bmp"]:
        return FileType.SCAN
    else:
        return FileType.OTHER


def attach_files(db, piece_id: int, uploaded_files, description: str = "") -> list:
    """Persist uploaded files for a piece and return the created MusicFile records."""
    created = []
    for uploaded_file in uploaded_files:
        file_path = save_uploaded_file(uploaded_file, piece_id)
        music_file = MusicFile(
            music_piece_id=piece_id,
            file_path=file_path,
            file_type=get_file_type(uploaded_file.name),
            original_filename=uploaded_file.name,
            file_size=uploaded_file.size,
            description=description or None,
        )
        db.add(music_file)
        created.append(music_file)
    return created


# File extensions accepted for scan/score uploads across the app
UPLOAD_TYPES = ["pdf", "png", "jpg", "jpeg", "tiff", "bmp", "mscz", "mscx", "xml", "musicxml"]
# File types that OCR / OMR can process
OCR_TYPES = {FileType.SCAN, FileType.PDF}


# ---------------------------------------------------------------------------
# Processing-status rendering (reads persisted ProcessingStep rows)
# ---------------------------------------------------------------------------

_STATUS_ICON = {"ok": "✅", "skipped": "⏭️", "error": "❌"}


def _fmt_duration(ms) -> str:
    """Human-readable wall-clock time for a step."""
    if not ms:
        return ""
    seconds = ms / 1000
    return f"{seconds:.1f}s" if seconds >= 0.1 else f"{ms} ms"


# Static fallback durations (seconds) for ETA when no run history exists per step key.
_ETA_FALLBACK_S = {
    "ocr": 5,
    "metadata": 8,
    "clean_text": 8,
    "omr": 90,
    "correct_score": 20,
    "underlay": 15,
}
_PIPELINE_STEP_KEYS = ["ocr", "metadata", "clean_text", "omr", "correct_score", "underlay"]
# Reverse mapping: step label → step key (used inside the ETA progress callback).
_LABEL_TO_KEY = {v: k for k, v in STEP_LABELS.items() if k in _PIPELINE_STEP_KEYS}


def _fmt_elapsed(seconds: float) -> str:
    """Format a duration (seconds) as 'm:ss' or 'Xs' for inline progress display."""
    s = max(0, int(seconds))
    if s >= 60:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s}s"


def render_processing_panel(latest_steps: dict) -> None:
    """Render the persistent pipeline-status panel from the newest step per key."""
    if not latest_steps:
        st.info(
            "Ten utwór nie był jeszcze przetwarzany. Uruchom pełny pipeline lub pojedyncze "
            "kroki (OCR / OMR) poniżej."
        )
        return

    for key in STEP_SEQUENCE:
        step = latest_steps.get(key)
        label = STEP_LABELS.get(key, key)
        if step is None:
            st.markdown(f"⬜ **{label}** — _nie uruchomiono_")
            continue
        icon = _STATUS_ICON.get(step.status, "•")
        dur = _fmt_duration(step.duration_ms)
        dur_txt = f" · ⏱ {dur}" if dur else ""
        st.markdown(f"{icon} **{label}** — {step.detail or ''}{dur_txt}")
        if step.report:
            with st.expander(f"📋 Raport: {label}"):
                st.markdown(step.report)


def render_analysis(data: dict) -> None:
    """Render the full ScoreDescriptor (analysis step ``data_json``)."""
    if not data:
        return

    col1, col2 = st.columns(2)
    with col1:
        key = data.get("detected_key") or "—"
        conf = data.get("key_confidence")
        conf_txt = f" (pewność {conf:.0%})" if isinstance(conf, (int, float)) else ""
        st.write(f"**Tonacja:** {key}{conf_txt}")
        st.write(f"**Tryb:** {data.get('mode') or '—'}")
        ts = ", ".join(data.get("time_signatures") or []) or "—"
        st.write(f"**Metrum:** {ts}")
        st.write(f"**Faktura:** {data.get('texture_type') or '—'}")
        st.write(f"**Epoka harmoniczna:** {data.get('harmony_epoch') or '—'}")
    with col2:
        voices = ", ".join(data.get("voice_names") or []) or "—"
        st.write(f"**Głosy ({data.get('voice_count') or 0}):** {voices}")
        st.write(f"**Forma:** {data.get('form_type') or '—'}")
        grade = data.get("grade_label") or "—"
        st.write(f"**Trudność:** {grade} (grade {data.get('estimated_grade') or '—'})")
        chrom = data.get("chromatic_complexity")
        if isinstance(chrom, (int, float)):
            st.write(f"**Złożoność chromatyczna:** {chrom:.2f}")
        st.write(f"**Tekst:** {data.get('text_setting_type') or '—'}")

    ranges = data.get("voice_ranges") or []
    factors = data.get("difficulty_factors") or []
    if ranges or factors:
        with st.expander("🔬 Szczegóły analizy"):
            for vr in ranges:
                st.write(
                    f"- **{vr.get('name', '?')}:** {vr.get('lowest_pitch', '?')}–"
                    f"{vr.get('highest_pitch', '?')} "
                    f"(zakres {vr.get('range_semitones', '?')} półtonów)"
                )
            if factors:
                st.write("**Czynniki trudności:** " + ", ".join(factors))


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "selected_piece_id" not in st.session_state:
    st.session_state.selected_piece_id = None

if "page" not in st.session_state:
    st.session_state.page = 0

if "translation_notes" not in st.session_state:
    st.session_state.translation_notes = None

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

st.sidebar.title("🎵 Church Music Organizer")
page = st.sidebar.selectbox("Navigation", ["Music Collection", "Song Details"])

# If a piece is selected, switch to details view
if st.session_state.selected_piece_id is not None and page == "Music Collection":
    # Allow user to stay on collection or go to details
    pass


# ============================================================
# TAB 1: Music Collection - searched, filtered, paginated list
# ============================================================
if page == "Music Collection":
    st.title("📚 Music Collection")

    # --- ADD NEW PIECE SECTION ---
    with st.expander("➕ Dodaj nowy utwór", expanded=False):
        with st.form("add_music_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                new_title = st.text_input("Tytuł *", help="Pole wymagane")
                new_lyrics_author = st.text_input("Autor słów")
                new_music_author = st.text_input("Autor muzyki")
                new_harmony_author = st.text_input("Autor harmonii")

            with col2:
                new_key_signature = st.text_input("Tonacja", help="np. C-dur, d-moll")
                new_time_signature = st.text_input("Metrum", help="np. 4/4, 3/4")
                new_measures_count = st.number_input("Ilość taktów", min_value=0, value=0, step=1)

            tags_input = st.text_input(
                "Tagi (oddzielone przecinkiem)",
                help="np. uroczyste, tradycyjne, wielogłosowe",
            )

            new_files = st.file_uploader(
                "Skan / plik nutowy (opcjonalnie)",
                accept_multiple_files=True,
                type=UPLOAD_TYPES,
                help="PDF, obraz skanu, MuseScore lub MusicXML. OCR/OMR uruchomisz w szczegółach utworu.",
            )

            submit = st.form_submit_button("Dodaj utwór")

            if submit:
                if not new_title:
                    st.error("Tytuł jest wymagany!")
                else:
                    try:
                        with get_db_session() as db:
                            piece = MusicPiece(
                                title=new_title,
                                lyrics_author=new_lyrics_author or None,
                                music_author=new_music_author or None,
                                harmony_author=new_harmony_author or None,
                                key_signature=new_key_signature or None,
                                time_signature=new_time_signature or None,
                                measures_count=(
                                    new_measures_count if new_measures_count > 0 else None
                                ),
                            )
                            db.add(piece)
                            db.flush()

                            if tags_input:
                                tag_names = [t.strip() for t in tags_input.split(",") if t.strip()]
                                for tag_name in tag_names:
                                    tag = db.query(Tag).filter_by(name=tag_name).first()
                                    if not tag:
                                        tag = Tag(name=tag_name)
                                        db.add(tag)
                                    piece.tags.append(tag)

                            if new_files:
                                attach_files(db, piece.id, new_files)

                            piece_id = piece.id
                            db.commit()
                            msg = f"Utwór '{new_title}' został dodany pomyślnie! (ID: {piece_id})"
                            if new_files:
                                msg += (
                                    f" Dodano {len(new_files)} plik(ów) — "
                                    "przejdź do 'Song Details', aby uruchomić OCR/OMR."
                                )
                            st.success(msg)
                    except Exception as e:
                        logger.exception("Error adding music piece")
                        st.error(f"Błąd podczas dodawania utworu: {str(e)}")

    st.markdown("---")

    # --- SEARCH AND FILTERS ---
    st.subheader("Kolekcja muzyczna")

    col_search, col_occasion, col_season = st.columns([3, 2, 2])
    search = col_search.text_input(
        "Szukaj",
        placeholder="Tytuł, kompozytor, autor słów...",
        key="search",
    )
    occasion = col_occasion.selectbox("Okazja", OCCASIONS, key="filter_occasion")
    season = col_season.selectbox("Okres liturgiczny", SEASONS, key="filter_season")

    # Reset page when any filter changes
    for _key in ["search", "filter_occasion", "filter_season"]:
        prev_key = f"prev_{_key}"
        if prev_key not in st.session_state:
            st.session_state[prev_key] = ""
        current_val = st.session_state.get(_key, "")
        if current_val != st.session_state[prev_key]:
            st.session_state.page = 0
        st.session_state[prev_key] = current_val

    # Defaults used by pagination controls rendered after the with-block
    total_pages = 1
    total = 0

    # --- TABLE OF PIECES ---
    with get_db_session() as db:
        pieces, total = query_pieces(
            db,
            search=search,
            occasion=occasion,
            season=season,
            page=st.session_state.page,
            per_page=PER_PAGE,
        )
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

        if not pieces and total == 0:
            if search or occasion or season:
                st.info("Brak utworów pasujących do podanych kryteriów wyszukiwania.")
            else:
                st.info(
                    "Brak utworów w kolekcji. Użyj formularza powyżej, aby dodać pierwszy utwór."
                )
        else:
            # Column headers
            (
                hdr_title,
                hdr_lyrics,
                hdr_music,
                hdr_harmony,
                hdr_key,
                hdr_time,
                hdr_measures,
                hdr_actions,
            ) = st.columns([3, 2, 2, 2, 1.5, 1, 1, 2.5])
            hdr_title.markdown("**Tytuł**")
            hdr_lyrics.markdown("**Autor słów**")
            hdr_music.markdown("**Autor muzyki**")
            hdr_harmony.markdown("**Autor harmonii**")
            hdr_key.markdown("**Tonacja**")
            hdr_time.markdown("**Metrum**")
            hdr_measures.markdown("**Takty**")
            hdr_actions.markdown("**Akcje**")
            st.markdown("---")

            for piece in pieces:
                (
                    col_title,
                    col_lyrics,
                    col_music,
                    col_harmony,
                    col_key,
                    col_time,
                    col_measures,
                    col_actions,
                ) = st.columns([3, 2, 2, 2, 1.5, 1, 1, 2.5])

                col_title.write(piece.title)
                col_lyrics.write(piece.lyrics_author or "—")
                col_music.write(piece.music_author or "—")
                col_harmony.write(piece.harmony_author or "—")
                col_key.write(piece.key_signature or "—")
                col_time.write(piece.time_signature or "—")
                col_measures.write(str(piece.measures_count) if piece.measures_count else "—")

                with col_actions:
                    btn_col1, btn_col2 = st.columns(2)
                    if btn_col1.button("📋", key=f"detail_{piece.id}", help="Zobacz szczegóły"):
                        st.session_state.selected_piece_id = piece.id
                        st.rerun()
                    if btn_col2.button("🗑️", key=f"delete_{piece.id}", help="Usuń"):
                        try:
                            with get_db_session() as db2:
                                p = db2.query(MusicPiece).filter_by(id=piece.id).first()
                                if p:
                                    db2.delete(p)
                                    db2.commit()
                                    st.rerun()
                        except Exception as e:
                            logger.exception("Error deleting piece id=%s", piece.id)
                            st.error(f"Błąd podczas usuwania: {str(e)}")

            st.markdown("---")

    # --- PAGINATION ---
    col_prev, col_info, col_next = st.columns([1, 3, 1])
    if col_prev.button("← Poprzednia", disabled=(st.session_state.page == 0)):
        st.session_state.page = max(0, st.session_state.page - 1)
        st.rerun()
    col_info.markdown(
        f"<div style='text-align:center'>Strona {st.session_state.page + 1} / "
        f"{total_pages} ({total} utworów)</div>",
        unsafe_allow_html=True,
    )
    if col_next.button("Następna →", disabled=(st.session_state.page >= total_pages - 1)):
        st.session_state.page += 1
        st.rerun()

    # --- INLINE EDIT SECTION ---
    st.markdown("---")
    with st.expander("✏️ Edytuj istniejący utwór", expanded=False):
        with get_db_session() as db:
            all_pieces_edit = db.query(MusicPiece).order_by(MusicPiece.title).limit(500).all()
            edit_piece_list = [(p.id, p.title) for p in all_pieces_edit]

        if not edit_piece_list:
            st.info("Brak utworów do edycji.")
        else:
            piece_options = {f"{pid}: {ptitle}": pid for pid, ptitle in edit_piece_list}
            selected_edit_str = st.selectbox(
                "Wybierz utwór do edycji", list(piece_options.keys()), key="edit_select"
            )
            selected_edit_id = piece_options[selected_edit_str]

            with get_db_session() as db:
                edit_piece = db.query(MusicPiece).filter_by(id=selected_edit_id).first()

                if edit_piece:
                    with st.form("edit_music_form"):
                        col1, col2 = st.columns(2)

                        with col1:
                            edit_title = st.text_input("Tytuł *", value=edit_piece.title)
                            edit_lyrics_author = st.text_input(
                                "Autor słów", value=edit_piece.lyrics_author or ""
                            )
                            edit_music_author = st.text_input(
                                "Autor muzyki", value=edit_piece.music_author or ""
                            )
                            edit_harmony_author = st.text_input(
                                "Autor harmonii", value=edit_piece.harmony_author or ""
                            )

                        with col2:
                            edit_key = st.text_input(
                                "Tonacja", value=edit_piece.key_signature or ""
                            )
                            edit_time = st.text_input(
                                "Metrum", value=edit_piece.time_signature or ""
                            )
                            edit_measures = st.number_input(
                                "Ilość taktów",
                                min_value=0,
                                value=edit_piece.measures_count or 0,
                                step=1,
                            )

                        save_edit = st.form_submit_button("Zapisz zmiany")

                        if save_edit:
                            if not edit_title:
                                st.error("Tytuł jest wymagany!")
                            else:
                                try:
                                    with get_db_session() as db2:
                                        p = (
                                            db2.query(MusicPiece)
                                            .filter_by(id=selected_edit_id)
                                            .first()
                                        )
                                        if p:
                                            p.title = edit_title
                                            p.lyrics_author = edit_lyrics_author or None
                                            p.music_author = edit_music_author or None
                                            p.harmony_author = edit_harmony_author or None
                                            p.key_signature = edit_key or None
                                            p.time_signature = edit_time or None
                                            p.measures_count = (
                                                edit_measures if edit_measures > 0 else None
                                            )
                                            db2.commit()
                                            st.success("Zmiany zostały zapisane!")
                                            st.rerun()
                                except Exception as e:
                                    logger.exception("Error saving inline edit for piece")
                                    st.error(f"Błąd podczas zapisywania zmian: {str(e)}")


# ============================================================
# TAB 2: Song Details
# ============================================================
elif page == "Song Details":
    st.title("🎵 Song Details")

    with get_db_session() as db:
        all_pieces_data = [
            (p.id, p.title)
            for p in db.query(MusicPiece).order_by(MusicPiece.title).limit(500).all()
        ]

    if not all_pieces_data:
        st.info("Brak utworów w kolekcji. Przejdź do 'Music Collection', aby dodać pierwszy utwór.")
    else:
        piece_options = {f"{pid}: {ptitle}": pid for pid, ptitle in all_pieces_data}
        piece_keys = list(piece_options.keys())

        default_index = 0
        if st.session_state.selected_piece_id is not None:
            for i, key in enumerate(piece_keys):
                if piece_options[key] == st.session_state.selected_piece_id:
                    default_index = i
                    break

        selected_piece_str = st.selectbox(
            "Wybierz utwór",
            piece_keys,
            index=default_index,
            key="detail_piece_select",
        )
        selected_piece_id = piece_options[selected_piece_str]
        # Clear the navigation state
        st.session_state.selected_piece_id = None

        with get_db_session() as db:
            piece = db.query(MusicPiece).filter_by(id=selected_piece_id).first()

            if piece:
                # Persisted pipeline results (newest per step) — drives the status panel
                # and per-section intermediate results below; survives page reloads.
                latest_steps = ProcessingStepService.latest_by_key(db, selected_piece_id)

                # --- DESCRIPTION & METADATA ---
                st.subheader("📝 Opis i metadane")
                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Tytuł:** {piece.title}")
                    st.write(f"**Autor słów:** {piece.lyrics_author or '—'}")
                    st.write(f"**Autor muzyki:** {piece.music_author or '—'}")
                    st.write(f"**Autor harmonii:** {piece.harmony_author or '—'}")
                    if piece.composer:
                        st.write(f"**Kompozytor:** {piece.composer}")
                    if piece.arranger:
                        st.write(f"**Aranżer:** {piece.arranger}")

                with col2:
                    st.write(f"**Tonacja:** {piece.key_signature or '—'}")
                    st.write(f"**Metrum:** {piece.time_signature or '—'}")
                    st.write(f"**Liczba taktów:** {piece.measures_count or '—'}")
                    if piece.tempo:
                        st.write(f"**Tempo:** {piece.tempo}")
                    if piece.genre:
                        st.write(f"**Gatunek:** {piece.genre}")
                    if piece.language:
                        st.write(f"**Język:** {piece.language}")

                if piece.description:
                    st.markdown(f"**Opis:** {piece.description}")
                if piece.notes:
                    st.markdown(f"**Notatki:** {piece.notes}")

                # Full automatic score analysis (persisted from the OMR analysis step).
                _analysis_step = latest_steps.get("analysis")
                _analysis_data = ProcessingStepService.data(_analysis_step)
                if _analysis_data:
                    st.markdown("**🔎 Analiza muzyczna (automatyczna):**")
                    render_analysis(_analysis_data)
                    if _analysis_step.report:
                        st.caption(_analysis_step.report)

                st.markdown("---")

                # --- PDF SCAN PREVIEW ---
                st.subheader("📄 PDF Scan Preview")
                pdf_files = [f for f in piece.files if f.file_type == FileType.PDF]
                scan_files = [f for f in piece.files if f.file_type == FileType.SCAN]

                if pdf_files:
                    for pdf_file in pdf_files:
                        st.write(f"**File:** {pdf_file.original_filename}")
                        file_path = Path(pdf_file.file_path)
                        if file_path.exists():
                            with open(file_path, "rb") as f:
                                pdf_data = f.read()
                            b64_pdf = base64.b64encode(pdf_data).decode("utf-8")
                            pdf_display = (
                                f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
                                f'width="100%" height="600" type="application/pdf"></iframe>'
                            )
                            st.markdown(pdf_display, unsafe_allow_html=True)
                        else:
                            st.warning(f"File not found on disk: {pdf_file.file_path}")
                elif scan_files:
                    for scan_file in scan_files:
                        st.write(f"**Scan:** {scan_file.original_filename}")
                        file_path = Path(scan_file.file_path)
                        if file_path.exists():
                            st.image(str(file_path))
                        else:
                            st.warning(f"File not found on disk: {scan_file.file_path}")
                else:
                    st.info("No PDF or scan files uploaded for this piece.")

                st.markdown("---")

                # --- OMR / OCR PROCESSING ---
                st.subheader("🎼 OMR / OCR Processing")

                # Brief toast after a just-finished run (the durable results render below).
                _flash = st.session_state.pop("processing_flash", None)
                if _flash and _flash.get("piece_id") == selected_piece_id:
                    st.success(_flash.get("message", "✅ Przetwarzanie zakończone."))

                # Persistent processing-status panel (reads ProcessingStep rows — survives
                # reloads, unlike the old transient flash).
                st.markdown("**🔄 Status przetwarzania:**")
                render_processing_panel(latest_steps)

                # Persisted OCR text per source file (read from the DB, not just after a run).
                for _src in pdf_files + scan_files:
                    if _src.extracted_text:
                        with st.expander(f"📄 Tekst OCR — {_src.original_filename}"):
                            st.text_area(
                                "Tekst OCR",
                                value=_src.extracted_text,
                                height=180,
                                key=f"ocrtext_{_src.id}",
                                disabled=True,
                            )

                st.markdown("---")

                _omr_avail = OMRService.is_available()
                _ocr_avail = OCRService.is_available()
                _llm_avail = PipelineService.llm_available()
                _status_col1, _status_col2, _status_col3 = st.columns(3)
                with _status_col1:
                    if _omr_avail:
                        st.success("✅ Audiveris dostępny")
                    else:
                        st.warning(
                            "⚠️ Audiveris niedostępny — " "patrz docs/knowledge/installation.md"
                        )
                with _status_col2:
                    if _ocr_avail:
                        st.success("✅ Tesseract OCR dostępny")
                    else:
                        st.warning(
                            "⚠️ Tesseract niedostępny — zainstaluj tesseract-ocr "
                            "z pakietami językowymi pol i eng"
                        )
                with _status_col3:
                    if _llm_avail:
                        st.success("✅ Gemini LLM dostępny")
                    else:
                        st.warning(
                            "⚠️ Gemini LLM niedostępny — zainstaluj 'google-genai' i ustaw "
                            "GEMINI_API_KEY w pliku .env"
                        )

                st.info(
                    "**Jak przetworzyć ten utwór:**  \n"
                    "1. Wgraj plik PDF lub skan w sekcji **Upload** (na dole strony).  \n"
                    "2. Kliknij **🤖 Pełny pipeline (1→5)** — OCR wyciągnie tekst, OMR "
                    "skonwertuje nuty na MusicXML, LLM oczyści i podłoży tekst.  \n"
                    "3. Pobierz gotowy plik MusicXML lub sprawdź wyniki w panelu statusu."
                )
                processable_files = pdf_files + scan_files
                if processable_files:
                    st.write("**Pliki do przetworzenia (PDF / skan):**")
                    for proc_file in processable_files:
                        st.write(f"📄 `{proc_file.original_filename}`")

                        # Full cascade pipeline (steps 1→5: OCR→LLM→OMR→LLM→LLM)
                        if st.button(
                            "🤖 Pełny pipeline (1→5)",
                            key=f"pipe_{proc_file.id}",
                            disabled=not (_ocr_avail or _omr_avail),
                            type="primary",
                            help="OCR → czyszczenie tekstu (LLM) → OMR → korekta partytury "
                            "(LLM) → podkład tekstu (LLM). Kroki bez dostępnego silnika są "
                            "pomijane.",
                        ):
                            # Pobierz historyczne średnie czasy kroków do wyznaczenia ETA.
                            _hist_avgs: dict = {}
                            for _sk in _PIPELINE_STEP_KEYS:
                                _skh = ProcessingStepService.history(
                                    db, selected_piece_id, _sk
                                )
                                _durs = [
                                    s.duration_ms for s in _skh
                                    if s.duration_ms is not None and s.duration_ms > 0
                                ]
                                if _durs:
                                    _hist_avgs[_sk] = sum(_durs) / len(_durs) / 1000
                            _estimates: dict = {
                                _sk: _hist_avgs.get(_sk, _ETA_FALLBACK_S.get(_sk, 10))
                                for _sk in _PIPELINE_STEP_KEYS
                            }
                            # Pasek postępu z pomiarem upłyniętego czasu i ETA.
                            _total = 6  # ocr, metadata, clean_text, omr, correct_score, underlay
                            _prog = st.progress(0.0, text="Uruchamiam pipeline…")
                            _state = {"n": 0, "remaining": list(_PIPELINE_STEP_KEYS)}
                            _t_start = time.perf_counter()

                            def _on_progress(
                                name,
                                status,
                                _p=_prog,
                                _s=_state,
                                _t=_total,
                                _start=_t_start,
                                _est=_estimates,
                            ):
                                _s["n"] += 1
                                _ico = _STATUS_ICON.get(status, "•")
                                _el = time.perf_counter() - _start
                                _key = _LABEL_TO_KEY.get(name)
                                if _key and _key in _s["remaining"]:
                                    _s["remaining"].remove(_key)
                                _eta = sum(_est.get(k, 10) for k in _s["remaining"])
                                _p.progress(
                                    min(_s["n"] / _t, 1.0),
                                    text=(
                                        f"{_ico} {name} — {status} | "
                                        f"upłynęło: {_fmt_elapsed(_el)}, "
                                        f"ETA: ~{_fmt_elapsed(_eta)}"
                                    ),
                                )

                            try:
                                with get_db_session() as db2:
                                    PipelineService().run_full(
                                        db2, proc_file.id, on_progress=_on_progress
                                    )
                                    db2.commit()
                                _prog.progress(1.0, text="✅ Zakończono.")
                                st.session_state["processing_flash"] = {
                                    "piece_id": selected_piece_id,
                                    "message": "✅ Pełny pipeline zakończony — wyniki poniżej.",
                                }
                                st.rerun()
                            except Exception as _exc:
                                logger.exception("Pipeline failed for file_id=%s", proc_file.id)
                                st.error(f"Błąd pipeline: {str(_exc)}")

                        _btn_omr, _btn_ocr = st.columns(2)

                        # OMR button — converts PDF/scan to MusicXML via Audiveris (persisted)
                        if _btn_omr.button(
                            "🎼 Uruchom OMR → MusicXML",
                            key=f"omr_{proc_file.id}",
                            disabled=not _omr_avail,
                        ):
                            with st.spinner(
                                "Konwersja PDF→MusicXML przez Audiveris... "
                                "(może potrwać kilka minut)"
                            ):
                                try:
                                    with get_db_session() as db2:
                                        r3 = PipelineService().run_step3_omr(db2, proc_file.id)
                                        db2.commit()
                                    if r3.get("status") == "ok":
                                        st.session_state["processing_flash"] = {
                                            "piece_id": selected_piece_id,
                                            "message": "✅ OMR zakończony — MusicXML i analiza "
                                            "zapisane.",
                                        }
                                        st.rerun()
                                    else:
                                        st.error("Błąd OMR: " + r3.get("detail", "nieznany błąd"))
                                except Exception as _exc:
                                    logger.exception("OMR failed for file_id=%s", proc_file.id)
                                    st.error(f"Błąd przetwarzania OMR: {str(_exc)}")

                        # OCR button — extracts text via Tesseract (persisted)
                        if _btn_ocr.button(
                            "📝 Uruchom OCR → tekst",
                            key=f"ocr_{proc_file.id}",
                            disabled=not _ocr_avail,
                        ):
                            with st.spinner(
                                "Ekstrakcja tekstu przez Tesseract OCR... " "(może potrwać chwilę)"
                            ):
                                try:
                                    with get_db_session() as db2:
                                        r1 = PipelineService().run_step1_ocr(db2, proc_file.id)
                                        db2.commit()
                                    if r1.get("status") == "ok":
                                        st.session_state["processing_flash"] = {
                                            "piece_id": selected_piece_id,
                                            "message": f"✅ OCR zakończony — {r1.get('detail', '')}",
                                        }
                                        st.rerun()
                                    else:
                                        st.error(
                                            "Błąd OCR: nie udało się przetworzyć pliku "
                                            f"'{proc_file.original_filename}'. Sprawdź logi."
                                        )
                                except Exception as _exc:
                                    logger.exception("OCR failed for file_id=%s", proc_file.id)
                                    st.error(f"Błąd przetwarzania OCR: {str(_exc)}")

                        # --- Individual LLM steps (operate on existing artefacts) ---
                        _btn_clean, _btn_score = st.columns(2)
                        _has_ocr_text = bool(proc_file.extracted_text)
                        if _btn_clean.button(
                            "🧹 Oczyść tekst (LLM)",
                            key=f"clean_{proc_file.id}",
                            disabled=not (_llm_avail and _has_ocr_text),
                            help=None if _has_ocr_text else "Najpierw uruchom OCR.",
                        ):
                            with st.spinner("Czyszczenie tekstu przez Gemini..."):
                                try:
                                    with get_db_session() as db2:
                                        r2 = PipelineService().run_step2_clean_text(
                                            db2,
                                            selected_piece_id,
                                            proc_file.extracted_text or "",
                                            source_file_id=proc_file.id,
                                        )
                                        db2.commit()
                                    if r2.get("status") == "ok":
                                        st.session_state["processing_flash"] = {
                                            "piece_id": selected_piece_id,
                                            "message": "✅ Tekst oczyszczony (język: "
                                            f"{r2.get('language')}).",
                                        }
                                        st.rerun()
                                    else:
                                        st.info(r2.get("detail", "Pominięto."))
                                except Exception as _exc:
                                    logger.exception("clean text failed")
                                    st.error(f"Błąd czyszczenia tekstu: {str(_exc)}")

                        # Metadata extraction — fills empty title/author fields from OCR header.
                        if st.button(
                            "🏷️ Wyciągnij metadane (LLM)",
                            key=f"meta_{proc_file.id}",
                            disabled=not (_llm_avail and _has_ocr_text),
                            help=None if _has_ocr_text else "Najpierw uruchom OCR.",
                        ):
                            with st.spinner("Ekstrakcja metadanych (autorzy, tytuł) przez LLM..."):
                                try:
                                    with get_db_session() as db2:
                                        rm = PipelineService().run_step_metadata(
                                            db2,
                                            selected_piece_id,
                                            proc_file.extracted_text or "",
                                            source_file_id=proc_file.id,
                                        )
                                        db2.commit()
                                    if rm.get("status") == "ok":
                                        _applied = rm.get("applied") or []
                                        _msg = (
                                            f"✅ Metadane: uzupełniono pola {', '.join(_applied)}."
                                            if _applied
                                            else "ℹ️ Nie znaleziono nowych metadanych "
                                            "(pola już wypełnione lub brak danych w nagłówku)."
                                        )
                                        st.session_state["processing_flash"] = {
                                            "piece_id": selected_piece_id,
                                            "message": _msg,
                                        }
                                        st.rerun()
                                    else:
                                        st.info(rm.get("detail", "Pominięto."))
                                except Exception as _exc:
                                    logger.exception("metadata extraction failed")
                                    st.error(f"Błąd ekstrakcji metadanych: {str(_exc)}")

                        # Correct + underlay — needs an existing MusicXML file for this piece.
                        _piece_xml = next(
                            (f for f in reversed(piece.files) if f.file_type == FileType.XML),
                            None,
                        )
                        if _btn_score.button(
                            "🎶 Korekta (LLM) + podkład tekstu",
                            key=f"score_{proc_file.id}",
                            disabled=not (_llm_avail and _piece_xml is not None),
                            help=None if _piece_xml else "Najpierw uruchom OMR.",
                        ):
                            with st.spinner(
                                "Korekta partytury (LLM) + algorytmiczny podkład tekstu..."
                            ):
                                try:
                                    with get_db_session() as db2:
                                        svc = PipelineService()
                                        r4 = svc.run_step4_correct_score(
                                            db2,
                                            selected_piece_id,
                                            _piece_xml.file_path,
                                            source_file_id=_piece_xml.id,
                                        )
                                        _has_lyrics = bool((piece.lyrics or "").strip())
                                        if r4.get("status") == "ok" and _has_lyrics:
                                            svc.run_step5_underlay(
                                                db2,
                                                selected_piece_id,
                                                piece.lyrics,
                                                xml_path=_piece_xml.file_path,
                                                xml_content=r4.get("musicxml"),
                                                source_file_id=_piece_xml.id,
                                            )
                                        db2.commit()
                                    _msg = "✅ Korekta partytury zakończona."
                                    if not _has_lyrics:
                                        _msg += " Podkład pominięto — brak tekstu (oczyść tekst)."
                                    st.session_state["processing_flash"] = {
                                        "piece_id": selected_piece_id,
                                        "message": _msg,
                                    }
                                    st.rerun()
                                except Exception as _exc:
                                    logger.exception("score correct/underlay failed")
                                    st.error(f"Błąd korekty/podkładu: {str(_exc)}")
                else:
                    st.info(
                        "Brak plików PDF lub skanów do przetworzenia. "
                        "Wgraj plik w sekcji 'Upload Files' poniżej."
                    )

                # Generated MusicXML — show ONLY the freshest version of each kind (OMR / korekta
                # / finalny), so the user sees the current artefacts, not the whole history.
                xml_files = [
                    f for f in piece.files
                    if f.file_type == FileType.XML
                    and not (f.description or "").startswith("[REFERENCJA]")
                ]
                if xml_files:
                    st.write("**Aktualne pliki MusicXML (najnowsze wersje):**")
                    # Map produced-file id → the step that created it (provenance).
                    _provenance = {
                        s.output_file_id: s.step_label
                        for s in latest_steps.values()
                        if s.output_file_id
                    }

                    # Stable display order of the kinds (OMR → korekta → finalny).
                    _KIND_ORDER = ["📄 OMR (surowy)", "🛠️ Korekta partytury", "🎶 Finalny (z tekstem)"]

                    def _file_kind(f) -> str:
                        name = (f.original_filename or "").lower()
                        if name.startswith("final_"):
                            return "🎶 Finalny (z tekstem)"
                        if name.startswith("corrected_"):
                            return "🛠️ Korekta partytury"
                        return "📄 OMR (surowy)"

                    # Keep only the newest file per kind.
                    _newest_per_kind: dict = {}
                    for f in xml_files:
                        k = _file_kind(f)
                        cur = _newest_per_kind.get(k)
                        if cur is None or (f.id > cur.id):
                            _newest_per_kind[k] = f

                    for _kind in [k for k in _KIND_ORDER if k in _newest_per_kind]:
                        xml_file = _newest_per_kind[_kind]
                        _ver = f"v{xml_file.version}" if xml_file.version else "—"
                        _when = (
                            xml_file.created_at.strftime("%Y-%m-%d %H:%M")
                            if xml_file.created_at
                            else "—"
                        )
                        st.markdown(f"**{_kind}** · {_ver} · 🕒 {_when}")
                        _prov = _provenance.get(xml_file.id)
                        if _prov:
                            st.caption(f"↳ pochodzi z kroku: {_prov}")
                        _xml_disk = Path(xml_file.file_path)
                        if _xml_disk.exists():
                            st.download_button(
                                label=f"⬇️ Pobierz {xml_file.original_filename}",
                                data=_xml_disk.read_bytes(),
                                file_name=xml_file.original_filename,
                                mime="application/xml",
                                key=f"dl_xml_{xml_file.id}",
                            )
                        else:
                            st.warning(
                                "Plik MusicXML nie znaleziony na dysku: " f"{xml_file.file_path}"
                            )

                st.markdown("---")

                # --- MUSESCORE LINK ---
                st.subheader("🎼 MuseScore")
                musescore_files = [f for f in piece.files if f.file_type == FileType.MUSESCORE]
                if piece.musescore_link:
                    st.markdown(f"[Open in MuseScore]({piece.musescore_link})")
                if musescore_files:
                    for ms_file in musescore_files:
                        st.write(f"**File:** {ms_file.original_filename}")
                        file_path = Path(ms_file.file_path)
                        if file_path.exists():
                            with open(file_path, "rb") as f:
                                st.download_button(
                                    label=f"Download {ms_file.original_filename}",
                                    data=f.read(),
                                    file_name=ms_file.original_filename,
                                    key=f"dl_mscz_{ms_file.id}",
                                )
                        else:
                            st.warning(f"File not found on disk: {ms_file.file_path}")
                if not piece.musescore_link and not musescore_files:
                    st.info("No MuseScore link or files available.")

                st.markdown("---")

                # --- LYRICS ---
                st.subheader("📜 Tekst pieśni")
                _clean_step = latest_steps.get("clean_text")
                _detected_lang = (
                    (ProcessingStepService.data(_clean_step) or {}).get("language")
                    or piece.language
                )
                # Uwagi tłumacza z poprzedniego uruchomienia (zapisane przez flash).
                _transl_notes = st.session_state.pop("translation_notes", None)
                if _transl_notes:
                    st.caption(f"Uwagi tłumacza: {_transl_notes}")

                # Editable lyrics + translation: fix text quickly, save, then re-run underlay.
                with st.form(f"edit_lyrics_form_{selected_piece_id}"):
                    _col_orig, _col_transl = st.columns(2)
                    with _col_orig:
                        st.markdown("**Tekst oryginalny** (edytowalny)")
                        _edit_orig = st.text_area(
                            "tekst_orig",
                            value=piece.lyrics or "",
                            height=220,
                            label_visibility="collapsed",
                            key=f"orig_{selected_piece_id}",
                        )
                    with _col_transl:
                        st.markdown("**Tłumaczenie (PL)** (edytowalne)")
                        _edit_transl = st.text_area(
                            "tekst_transl",
                            value=piece.lyrics_translation_pl or "",
                            height=220,
                            label_visibility="collapsed",
                            key=f"transl_{selected_piece_id}",
                        )
                    if st.form_submit_button("💾 Zapisz teksty"):
                        try:
                            with get_db_session() as db2:
                                _p2 = (
                                    db2.query(MusicPiece)
                                    .filter_by(id=selected_piece_id)
                                    .first()
                                )
                                if _p2:
                                    _p2.lyrics = _edit_orig.strip() or None
                                    _p2.lyrics_translation_pl = _edit_transl.strip() or None
                                    db2.commit()
                            st.session_state["processing_flash"] = {
                                "piece_id": selected_piece_id,
                                "message": "✅ Teksty zapisane. Możesz teraz ponownie podłożyć "
                                "tekst (krok 5).",
                            }
                            st.rerun()
                        except Exception as _exc:
                            logger.exception("save lyrics failed")
                            st.error(f"Błąd zapisu tekstów: {str(_exc)}")

                # Underlay the (possibly edited) lyrics onto the latest corrected / OMR score.
                _under_src = next(
                    (
                        f for f in sorted(piece.files, key=lambda x: x.id, reverse=True)
                        if f.file_type == FileType.XML
                        and (f.original_filename or "").lower().startswith("corrected_")
                    ),
                    None,
                ) or next(
                    (
                        f for f in sorted(piece.files, key=lambda x: x.id, reverse=True)
                        if f.file_type == FileType.XML
                        and not (f.description or "").startswith("[REFERENCJA]")
                        and not (f.original_filename or "").lower().startswith("final_")
                    ),
                    None,
                )
                _can_underlay = bool((piece.lyrics or "").strip()) and _under_src is not None
                if st.button(
                    "🎶 Podłóż tekst do nut (krok 5)",
                    key=f"underlay_only_{selected_piece_id}",
                    disabled=not _can_underlay,
                    help=(
                        None if _can_underlay
                        else "Wymagany tekst pieśni oraz partytura MusicXML (uruchom OMR/korektę)."
                    ),
                ):
                    with st.spinner("Algorytmiczny podkład tekstu pod nuty..."):
                        try:
                            with get_db_session() as db2:
                                _r5 = PipelineService().run_step5_underlay(
                                    db2,
                                    selected_piece_id,
                                    piece.lyrics,
                                    xml_path=_under_src.file_path,
                                    source_file_id=_under_src.id,
                                )
                                db2.commit()
                            st.session_state["processing_flash"] = {
                                "piece_id": selected_piece_id,
                                "message": "✅ " + _r5.get("detail", "Podkład tekstu zakończony."),
                            }
                            st.rerun()
                        except Exception as _exc:
                            logger.exception("standalone underlay failed")
                            st.error(f"Błąd podkładu tekstu: {str(_exc)}")

                _btn_transl_lbl = (
                    "🔁 Przetłumacz ponownie"
                    if piece.lyrics_translation_pl
                    else "🌐 Przetłumacz na polski (Gemini)"
                )
                _can_translate = bool(piece.lyrics) and _llm_avail
                if st.button(
                    _btn_transl_lbl,
                    key=f"translate_{selected_piece_id}",
                    disabled=not _can_translate,
                    help=(
                        None
                        if _can_translate
                        else "Wymagany tekst pieśni i dostępny Gemini LLM."
                    ),
                ):
                    with st.spinner("Tłumaczenie przez Gemini…"):
                        try:
                            _tr = translate_to_polish(
                                piece.lyrics, source_language=_detected_lang
                            )
                            with get_db_session() as db2:
                                _p2 = (
                                    db2.query(MusicPiece)
                                    .filter_by(id=selected_piece_id)
                                    .first()
                                )
                                if _p2:
                                    _p2.lyrics_translation_pl = _tr.translation_pl
                                    db2.commit()
                            if _tr.notes:
                                st.session_state["translation_notes"] = _tr.notes
                            st.session_state["processing_flash"] = {
                                "piece_id": selected_piece_id,
                                "message": "✅ Tłumaczenie zapisane.",
                            }
                            st.rerun()
                        except Exception as _exc:
                            logger.exception("translate_to_polish failed")
                            st.error(f"Błąd tłumaczenia: {str(_exc)}")

                if _clean_step and _clean_step.report:
                    with st.expander("🧹 Raport czyszczenia tekstu (LLM)"):
                        st.caption(
                            f"Status: {_clean_step.status} · {_clean_step.detail or ''}"
                        )
                        st.markdown(_clean_step.report)

                st.markdown("---")

                # --- PORÓWNANIE Z REFERENCJĄ ---
                st.subheader("📊 Porównanie z referencją (metryki)")
                _xml_all_sorted = sorted(
                    [f for f in piece.files if f.file_type == FileType.XML],
                    key=lambda f: f.id,
                )
                _ref_files_cmp = [
                    f for f in _xml_all_sorted
                    if (f.description or "").startswith("[REFERENCJA]")
                ]
                _cand_files_cmp = [
                    f for f in _xml_all_sorted
                    if not (f.description or "").startswith("[REFERENCJA]")
                ]

                with st.expander("📂 Wgraj plik referencyjny (target MusicXML)", expanded=False):
                    _ref_upload = st.file_uploader(
                        "Plik referencyjny (.musicxml / .mxl / .xml)",
                        type=["musicxml", "mxl", "xml"],
                        key=f"ref_upload_{selected_piece_id}",
                    )
                    if st.button(
                        "Zapisz jako referencję",
                        key=f"save_ref_{selected_piece_id}",
                        disabled=_ref_upload is None,
                    ):
                        try:
                            _rpath = FileService.save_uploaded_file(
                                piece_id=selected_piece_id,
                                filename=_ref_upload.name,
                                file_data=_ref_upload.getbuffer(),
                            )
                            with get_db_session() as db2:
                                _rmf = MusicFile(
                                    music_piece_id=selected_piece_id,
                                    file_path=_rpath,
                                    file_type=FileType.XML,
                                    original_filename=_ref_upload.name,
                                    file_size=_ref_upload.size,
                                    description=f"[REFERENCJA] {_ref_upload.name}",
                                )
                                db2.add(_rmf)
                                db2.commit()
                            st.session_state["processing_flash"] = {
                                "piece_id": selected_piece_id,
                                "message": (
                                    f"✅ Plik referencyjny '{_ref_upload.name}' zapisany."
                                ),
                            }
                            st.rerun()
                        except Exception as _exc:
                            logger.exception("save reference file failed")
                            st.error(f"Błąd zapisu pliku referencyjnego: {str(_exc)}")

                if not _xml_all_sorted:
                    st.info(
                        "Brak plików MusicXML. Uruchom pipeline (krok OMR) lub wgraj "
                        "plik referencyjny powyżej."
                    )
                else:
                    _pref_kw = ("krok 5", "krok 4", "final", "corrected")
                    _def_cand = next(
                        (
                            f for f in reversed(_cand_files_cmp)
                            if any(kw in (f.description or "").lower() for kw in _pref_kw)
                        ),
                        _cand_files_cmp[-1] if _cand_files_cmp else None,
                    )

                    def _flabel(f) -> str:
                        _d = (f.description or "")[:50]
                        return f"[{f.id}] {f.original_filename}" + (f" — {_d}" if _d else "")

                    _cand_dict = {_flabel(f): f for f in _cand_files_cmp}
                    _ref_dict = {_flabel(f): f for f in _ref_files_cmp}
                    _cand_keys = list(_cand_dict.keys())
                    _ref_keys = list(_ref_dict.keys())

                    _cand_def_idx = max(
                        0,
                        next(
                            (
                                i for i, k in enumerate(_cand_keys)
                                if _def_cand and _cand_dict[k].id == _def_cand.id
                            ),
                            len(_cand_keys) - 1,
                        ),
                    )
                    _sel_c, _sel_r = st.columns(2)
                    with _sel_c:
                        _cand_sel = st.selectbox(
                            "Plik wygenerowany (kandydat)",
                            _cand_keys if _cand_keys else ["— brak —"],
                            index=_cand_def_idx,
                            key=f"cmp_cand_{selected_piece_id}",
                            disabled=not bool(_cand_keys),
                        )
                    with _sel_r:
                        _ref_sel = st.selectbox(
                            "Plik referencyjny (target)",
                            _ref_keys if _ref_keys else ["— brak —"],
                            index=max(0, len(_ref_keys) - 1),
                            key=f"cmp_ref_{selected_piece_id}",
                            disabled=not bool(_ref_keys),
                        )

                    _cmp_ok = bool(_cand_keys) and bool(_ref_keys)
                    if st.button(
                        "📊 Porównaj",
                        key=f"cmp_btn_{selected_piece_id}",
                        disabled=not _cmp_ok,
                        help=(
                            None
                            if _cmp_ok
                            else "Wymagany co najmniej jeden plik kandydata i referencyjny."
                        ),
                    ):
                        _cf = _cand_dict.get(_cand_sel)
                        _rf = _ref_dict.get(_ref_sel)
                        if _cf and _rf:
                            with st.spinner("Porównuję pliki MusicXML…"):
                                _cmp_res = compare_musicxml(_rf.file_path, _cf.file_path)
                            if "error" in _cmp_res:
                                st.error(f"Błąd porównania: {_cmp_res['error']}")
                            else:
                                _r = _cmp_res["ref"]
                                _c2 = _cmp_res["conv"]
                                _ok = "✅"
                                _nok = "❌"
                                _recall = _cmp_res["note_recall"]
                                _ratio = _cmp_res["note_ratio"]
                                _recall_icon = (
                                    _ok
                                    if _recall >= 0.9
                                    else ("⚠️" if _recall >= 0.7 else _nok)
                                )
                                _ratio_icon = _ok if 0.9 <= _ratio <= 1.1 else _nok
                                _r_fifths = (
                                    str(_r["fifths"])
                                    if _r["fifths"] is not None
                                    else "—"
                                )
                                _c_fifths = (
                                    str(_c2["fifths"])
                                    if _c2["fifths"] is not None
                                    else "—"
                                )
                                _rows = [
                                    {
                                        "Metryka": "Poprawny MusicXML",
                                        "Referencja": "—",
                                        "Kandydat": (
                                            "tak" if _cmp_res["valid_musicxml"] else "NIE"
                                        ),
                                        "Wynik": (
                                            _ok if _cmp_res["valid_musicxml"] else _nok
                                        ),
                                    },
                                    {
                                        "Metryka": "Format .mxl",
                                        "Referencja": "—",
                                        "Kandydat": (
                                            ".mxl" if _cmp_res["is_mxl"] else ".xml"
                                        ),
                                        "Wynik": "—",
                                    },
                                    {
                                        "Metryka": "Recall nut",
                                        "Referencja": str(_r["notes"]),
                                        "Kandydat": str(_c2["notes"]),
                                        "Wynik": f"{_recall:.1%} {_recall_icon}",
                                    },
                                    {
                                        "Metryka": "Stosunek nut (>1 = nadmiar)",
                                        "Referencja": str(_r["notes"]),
                                        "Kandydat": str(_c2["notes"]),
                                        "Wynik": f"{_ratio:.2f} {_ratio_icon}",
                                    },
                                    {
                                        "Metryka": "Takty (ref / kand)",
                                        "Referencja": str(_r["measures"]),
                                        "Kandydat": str(_c2["measures"]),
                                        "Wynik": (
                                            f"{_ok} zgodne (±1)"
                                            if _cmp_res["measure_match"]
                                            else f"{_nok} różne"
                                        ),
                                    },
                                    {
                                        "Metryka": "Partie / głosy",
                                        "Referencja": str(_r["parts"]),
                                        "Kandydat": str(_c2["parts"]),
                                        "Wynik": (
                                            f"{_ok} zgodne"
                                            if _cmp_res["part_match"]
                                            else f"{_nok} różne"
                                        ),
                                    },
                                    {
                                        "Metryka": "Tonacja (kwinty)",
                                        "Referencja": _r_fifths,
                                        "Kandydat": _c_fifths,
                                        "Wynik": (
                                            f"{_ok} zgodna"
                                            if _cmp_res["key_match"]
                                            else f"{_nok} różna"
                                        ),
                                    },
                                    {
                                        "Metryka": "Metrum",
                                        "Referencja": str(_r["first_ts"] or "—"),
                                        "Kandydat": str(_c2["first_ts"] or "—"),
                                        "Wynik": (
                                            f"{_ok} zgodne"
                                            if _cmp_res["ts_match"]
                                            else f"{_nok} różne"
                                        ),
                                    },
                                ]
                                st.table(_rows)
                                st.metric(
                                    "OVERALL (0–1)",
                                    f"{_cmp_res['overall_score']:.3f}",
                                    help=(
                                        "Ważony wynik: recall nut ×0.50 + tonacja ×0.20"
                                        " + metrum ×0.15 + partie ×0.15"
                                    ),
                                )
                                if _cmp_res.get("valid_reason"):
                                    st.caption(f"Walidacja: {_cmp_res['valid_reason']}")

                st.markdown("---")

                # --- TAGS ---
                st.subheader("🏷️ Tags")
                if piece.tags:
                    tags_str = ", ".join([tag.name for tag in piece.tags])
                    st.write(tags_str)
                else:
                    st.info("No tags assigned.")

                st.markdown("---")

                # --- USAGE HISTORY ---
                st.subheader("📅 Usage History")
                if piece.usage_history:
                    for usage in sorted(
                        piece.usage_history, key=lambda u: u.usage_date, reverse=True
                    ):
                        st.write(
                            f"- **{usage.usage_date.strftime('%Y-%m-%d')}** "
                            f"{'— ' + usage.event_name if usage.event_name else ''} "
                            f"{'(' + usage.notes + ')' if usage.notes else ''}"
                        )
                else:
                    st.info("No usage history recorded.")

                # Add usage entry
                with st.expander("➕ Add Usage Entry"):
                    with st.form("add_usage_form"):
                        usage_date = st.date_input("Date", value=datetime.now().date())
                        usage_event = st.text_input("Event Name", help="e.g., Sunday Mass, Wedding")
                        usage_notes = st.text_input("Notes (optional)")
                        submit_usage = st.form_submit_button("Add Usage")

                        if submit_usage:
                            try:
                                with get_db_session() as db2:
                                    entry = UsageHistory(
                                        music_piece_id=selected_piece_id,
                                        usage_date=datetime.combine(
                                            usage_date, datetime.min.time()
                                        ),
                                        event_name=usage_event or None,
                                        notes=usage_notes or None,
                                    )
                                    db2.add(entry)
                                    db2.commit()
                                    st.success("✅ Usage entry added!")
                                    st.rerun()
                            except Exception as e:
                                logger.exception("Error adding usage history")
                                st.error(f"Error: {str(e)}")

                st.markdown("---")

                # --- FILE UPLOAD ---
                st.subheader("📤 Upload Files")
                uploaded_files = st.file_uploader(
                    "Upload scan (PDF/image) or MuseScore file (.mscz)",
                    accept_multiple_files=True,
                    type=["pdf", "png", "jpg", "jpeg", "tiff", "bmp", "mscz", "mscx"],
                    key=f"upload_{selected_piece_id}",
                )

                file_description = st.text_input("File Description (optional)", key="file_desc")

                if st.button("Upload Files", key="upload_btn"):
                    if uploaded_files:
                        try:
                            with get_db_session() as db2:
                                for uploaded_file in uploaded_files:
                                    file_path = save_uploaded_file(uploaded_file, selected_piece_id)

                                    music_file = MusicFile(
                                        music_piece_id=selected_piece_id,
                                        file_path=file_path,
                                        file_type=get_file_type(uploaded_file.name),
                                        original_filename=uploaded_file.name,
                                        file_size=uploaded_file.size,
                                        description=file_description or None,
                                    )
                                    db2.add(music_file)

                                db2.commit()
                                st.success(f"✅ {len(uploaded_files)} file(s) uploaded!")
                                st.rerun()
                        except Exception as e:
                            logger.exception(
                                "Error uploading files for piece id=%s", selected_piece_id
                            )
                            st.error(f"Error uploading: {str(e)}")
                    else:
                        st.warning("Please select files to upload.")

                st.markdown("---")

                # --- EDIT DETAILS ---
                with st.expander("✏️ Edit Song Details"):
                    with st.form("edit_details_form"):
                        col1, col2 = st.columns(2)

                        with col1:
                            ed_title = st.text_input("Title *", value=piece.title, key="ed_title")
                            ed_lyrics_author = st.text_input(
                                "Lyrics Author",
                                value=piece.lyrics_author or "",
                                key="ed_la",
                            )
                            ed_music_author = st.text_input(
                                "Music Author",
                                value=piece.music_author or "",
                                key="ed_ma",
                            )
                            ed_harmony_author = st.text_input(
                                "Harmony Author",
                                value=piece.harmony_author or "",
                                key="ed_ha",
                            )
                            ed_composer = st.text_input(
                                "Composer", value=piece.composer or "", key="ed_comp"
                            )
                            ed_arranger = st.text_input(
                                "Arranger", value=piece.arranger or "", key="ed_arr"
                            )

                        with col2:
                            ed_key = st.text_input(
                                "Key Signature",
                                value=piece.key_signature or "",
                                key="ed_key",
                            )
                            ed_time = st.text_input(
                                "Time Signature",
                                value=piece.time_signature or "",
                                key="ed_time",
                            )
                            ed_measures = st.number_input(
                                "Measures",
                                min_value=0,
                                value=piece.measures_count or 0,
                                key="ed_meas",
                            )
                            ed_tempo = st.text_input(
                                "Tempo", value=piece.tempo or "", key="ed_tempo"
                            )
                            ed_genre = st.text_input(
                                "Genre", value=piece.genre or "", key="ed_genre"
                            )
                            ed_language = st.text_input(
                                "Language", value=piece.language or "", key="ed_lang"
                            )

                        ed_description = st.text_area(
                            "Description", value=piece.description or "", key="ed_desc"
                        )
                        ed_lyrics = st.text_area(
                            "Lyrics",
                            value=piece.lyrics or "",
                            key="ed_lyrics",
                            height=200,
                        )
                        ed_musescore_link = st.text_input(
                            "MuseScore Link",
                            value=piece.musescore_link or "",
                            key="ed_ms_link",
                        )
                        ed_notes = st.text_area("Notes", value=piece.notes or "", key="ed_notes")

                        current_tags = ", ".join([t.name for t in piece.tags]) if piece.tags else ""
                        ed_tags = st.text_input(
                            "Tags (comma-separated)", value=current_tags, key="ed_tags"
                        )

                        save_details = st.form_submit_button("Save All Changes")

                        if save_details:
                            if not ed_title:
                                st.error("Title is required!")
                            else:
                                try:
                                    with get_db_session() as db2:
                                        p = (
                                            db2.query(MusicPiece)
                                            .filter_by(id=selected_piece_id)
                                            .first()
                                        )
                                        if p:
                                            p.title = ed_title
                                            p.lyrics_author = ed_lyrics_author or None
                                            p.music_author = ed_music_author or None
                                            p.harmony_author = ed_harmony_author or None
                                            p.composer = ed_composer or None
                                            p.arranger = ed_arranger or None
                                            p.key_signature = ed_key or None
                                            p.time_signature = ed_time or None
                                            p.measures_count = (
                                                ed_measures if ed_measures > 0 else None
                                            )
                                            p.tempo = ed_tempo or None
                                            p.genre = ed_genre or None
                                            p.language = ed_language or None
                                            p.description = ed_description or None
                                            p.lyrics = ed_lyrics or None
                                            p.musescore_link = ed_musescore_link or None
                                            p.notes = ed_notes or None

                                            p.tags.clear()
                                            if ed_tags:
                                                tag_names = [
                                                    t.strip()
                                                    for t in ed_tags.split(",")
                                                    if t.strip()
                                                ]
                                                for tag_name in tag_names:
                                                    tag = (
                                                        db2.query(Tag)
                                                        .filter_by(name=tag_name)
                                                        .first()
                                                    )
                                                    if not tag:
                                                        tag = Tag(name=tag_name)
                                                        db2.add(tag)
                                                    p.tags.append(tag)

                                            db2.commit()
                                            st.success("✅ All changes saved!")
                                            st.rerun()
                                except Exception as e:
                                    logger.exception(
                                        "Error saving full edit for piece id=%s", selected_piece_id
                                    )
                                    st.error(f"Error: {str(e)}")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("**Church Music Organizer v1.0**")
st.sidebar.markdown("Manage your church music collection")
