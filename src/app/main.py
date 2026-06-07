"""Streamlit application for church music organizer."""

import os
import sys
from pathlib import Path

import streamlit as st

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import base64
from datetime import datetime

from sqlalchemy import func

from src.database import FileType, MusicFile, MusicPiece, Tag, UsageHistory, get_db_session, init_db

# Page configuration
st.set_page_config(page_title="Church Music Organizer", page_icon="🎵", layout="wide")

# Initialize database
init_db()


# Helper functions
def save_uploaded_file(uploaded_file, music_piece_id: int) -> str:
    """Save uploaded file and return the path."""
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectory for this piece
    piece_dir = upload_dir / str(music_piece_id)
    piece_dir.mkdir(exist_ok=True)

    file_path = piece_dir / uploaded_file.name
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return str(file_path)


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


# Initialize session state for navigation
if "selected_piece_id" not in st.session_state:
    st.session_state.selected_piece_id = None

# Sidebar navigation
st.sidebar.title("🎵 Church Music Organizer")
page = st.sidebar.selectbox("Navigation", ["Music Collection", "Song Details"])

# If a piece is selected, switch to details view
if st.session_state.selected_piece_id is not None and page == "Music Collection":
    # Allow user to stay on collection or go to details
    pass


# ============================================================
# TAB 1: Music Collection - Table of last 50 songs with CRUD
# ============================================================
if page == "Music Collection":
    st.title("📚 Music Collection")

    # --- ADD NEW PIECE SECTION ---
    with st.expander("➕ Add New Music Piece", expanded=False):
        with st.form("add_music_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                new_title = st.text_input("Song Title *", help="Required field")
                new_lyrics_author = st.text_input("Lyrics Author (autor słów)")
                new_music_author = st.text_input("Music Author (autor muzyki)")
                new_harmony_author = st.text_input("Harmony Author (autor harmonii)")

            with col2:
                new_key_signature = st.text_input(
                    "Key Signature (tonacja)", help="e.g., C major, D minor"
                )
                new_time_signature = st.text_input("Time Signature (metrum)", help="e.g., 4/4, 3/4")
                new_measures_count = st.number_input(
                    "Number of Measures (ilość taktów)", min_value=0, value=0, step=1
                )

            tags_input = st.text_input(
                "Tags (comma-separated)", help="e.g., festive, solemn, traditional"
            )

            submit = st.form_submit_button("Add Music Piece")

            if submit:
                if not new_title:
                    st.error("Title is required!")
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

                            # Add tags
                            if tags_input:
                                tag_names = [t.strip() for t in tags_input.split(",") if t.strip()]
                                for tag_name in tag_names:
                                    tag = db.query(Tag).filter_by(name=tag_name).first()
                                    if not tag:
                                        tag = Tag(name=tag_name)
                                        db.add(tag)
                                    piece.tags.append(tag)

                            db.commit()
                            st.success(
                                f"✅ Music piece '{new_title}' added successfully! (ID: {piece.id})"
                            )
                    except Exception as e:
                        st.error(f"Error adding music piece: {str(e)}")

    st.markdown("---")

    # --- TABLE OF LAST 50 PIECES ---
    st.subheader("Last 50 Music Pieces")

    with get_db_session() as db:
        pieces = db.query(MusicPiece).order_by(MusicPiece.updated_at.desc()).limit(50).all()

        if not pieces:
            st.info("No music pieces yet. Use the form above to add your first piece.")
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
            hdr_title.markdown("**Song Title**")
            hdr_lyrics.markdown("**Lyrics Author**")
            hdr_music.markdown("**Music Author**")
            hdr_harmony.markdown("**Harmony Author**")
            hdr_key.markdown("**Key**")
            hdr_time.markdown("**Time**")
            hdr_measures.markdown("**Measures**")
            hdr_actions.markdown("**Actions**")
            st.markdown("---")

            # Display rows
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
                    # Details button
                    if btn_col1.button("📋", key=f"detail_{piece.id}", help="View Details"):
                        st.session_state.selected_piece_id = piece.id
                        st.rerun()
                    # Delete button
                    if btn_col2.button("🗑️", key=f"delete_{piece.id}", help="Delete"):
                        try:
                            with get_db_session() as db2:
                                p = db2.query(MusicPiece).filter_by(id=piece.id).first()
                                if p:
                                    db2.delete(p)
                                    db2.commit()
                                    st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting: {str(e)}")

            # End of table
            st.markdown("---")

    # --- INLINE EDIT SECTION ---
    st.markdown("---")
    with st.expander("✏️ Edit Existing Music Piece", expanded=False):
        with get_db_session() as db:
            all_pieces_edit = db.query(MusicPiece).order_by(MusicPiece.title).all()
            edit_piece_list = [(p.id, p.title) for p in all_pieces_edit]

        if not edit_piece_list:
            st.info("No music pieces to edit.")
        else:
            piece_options = {f"{pid}: {ptitle}": pid for pid, ptitle in edit_piece_list}
            selected_edit_str = st.selectbox(
                "Select piece to edit", list(piece_options.keys()), key="edit_select"
            )
            selected_edit_id = piece_options[selected_edit_str]

            with get_db_session() as db:
                edit_piece = db.query(MusicPiece).filter_by(id=selected_edit_id).first()

                if edit_piece:
                    with st.form("edit_music_form"):
                        col1, col2 = st.columns(2)

                        with col1:
                            edit_title = st.text_input("Song Title *", value=edit_piece.title)
                            edit_lyrics_author = st.text_input(
                                "Lyrics Author", value=edit_piece.lyrics_author or ""
                            )
                            edit_music_author = st.text_input(
                                "Music Author", value=edit_piece.music_author or ""
                            )
                            edit_harmony_author = st.text_input(
                                "Harmony Author", value=edit_piece.harmony_author or ""
                            )

                        with col2:
                            edit_key = st.text_input(
                                "Key Signature", value=edit_piece.key_signature or ""
                            )
                            edit_time = st.text_input(
                                "Time Signature", value=edit_piece.time_signature or ""
                            )
                            edit_measures = st.number_input(
                                "Number of Measures",
                                min_value=0,
                                value=edit_piece.measures_count or 0,
                                step=1,
                            )

                        save_edit = st.form_submit_button("Save Changes")

                        if save_edit:
                            if not edit_title:
                                st.error("Title is required!")
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
                                            st.success("✅ Changes saved!")
                                            st.rerun()
                                except Exception as e:
                                    st.error(f"Error saving changes: {str(e)}")


# ============================================================
# TAB 2: Song Details
# ============================================================
elif page == "Song Details":
    st.title("🎵 Song Details")

    # Select a piece to view
    with get_db_session() as db:
        all_pieces_data = [
            (p.id, p.title) for p in db.query(MusicPiece).order_by(MusicPiece.title).all()
        ]

    if not all_pieces_data:
        st.info("No music pieces yet. Go to 'Music Collection' to add your first piece.")
    else:
        # If coming from table button, pre-select that piece
        piece_options = {f"{pid}: {ptitle}": pid for pid, ptitle in all_pieces_data}
        piece_keys = list(piece_options.keys())

        default_index = 0
        if st.session_state.selected_piece_id is not None:
            for i, key in enumerate(piece_keys):
                if piece_options[key] == st.session_state.selected_piece_id:
                    default_index = i
                    break

        selected_piece_str = st.selectbox(
            "Select Music Piece", piece_keys, index=default_index, key="detail_piece_select"
        )
        selected_piece_id = piece_options[selected_piece_str]
        # Clear the navigation state
        st.session_state.selected_piece_id = None

        with get_db_session() as db:
            piece = db.query(MusicPiece).filter_by(id=selected_piece_id).first()

            if piece:
                # --- DESCRIPTION & METADATA ---
                st.subheader("📝 Description & Metadata")
                col1, col2 = st.columns(2)

                with col1:
                    st.write(f"**Title:** {piece.title}")
                    st.write(f"**Lyrics Author:** {piece.lyrics_author or '—'}")
                    st.write(f"**Music Author:** {piece.music_author or '—'}")
                    st.write(f"**Harmony Author:** {piece.harmony_author or '—'}")
                    if piece.composer:
                        st.write(f"**Composer:** {piece.composer}")
                    if piece.arranger:
                        st.write(f"**Arranger:** {piece.arranger}")

                with col2:
                    st.write(f"**Key Signature:** {piece.key_signature or '—'}")
                    st.write(f"**Time Signature:** {piece.time_signature or '—'}")
                    st.write(f"**Measures:** {piece.measures_count or '—'}")
                    if piece.tempo:
                        st.write(f"**Tempo:** {piece.tempo}")
                    if piece.genre:
                        st.write(f"**Genre:** {piece.genre}")
                    if piece.language:
                        st.write(f"**Language:** {piece.language}")

                if piece.description:
                    st.markdown(f"**Description:** {piece.description}")
                if piece.notes:
                    st.markdown(f"**Notes:** {piece.notes}")

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
                st.subheader("📜 Lyrics")
                if piece.lyrics:
                    st.text(piece.lyrics)
                else:
                    st.info("No lyrics available for this piece.")

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
                                "Lyrics Author", value=piece.lyrics_author or "", key="ed_la"
                            )
                            ed_music_author = st.text_input(
                                "Music Author", value=piece.music_author or "", key="ed_ma"
                            )
                            ed_harmony_author = st.text_input(
                                "Harmony Author", value=piece.harmony_author or "", key="ed_ha"
                            )
                            ed_composer = st.text_input(
                                "Composer", value=piece.composer or "", key="ed_comp"
                            )
                            ed_arranger = st.text_input(
                                "Arranger", value=piece.arranger or "", key="ed_arr"
                            )

                        with col2:
                            ed_key = st.text_input(
                                "Key Signature", value=piece.key_signature or "", key="ed_key"
                            )
                            ed_time = st.text_input(
                                "Time Signature", value=piece.time_signature or "", key="ed_time"
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
                            "Lyrics", value=piece.lyrics or "", key="ed_lyrics", height=200
                        )
                        ed_musescore_link = st.text_input(
                            "MuseScore Link", value=piece.musescore_link or "", key="ed_ms_link"
                        )
                        ed_notes = st.text_area("Notes", value=piece.notes or "", key="ed_notes")

                        # Tags editing
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

                                            # Update tags
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
                                    st.error(f"Error: {str(e)}")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("**Church Music Organizer v1.0**")
st.sidebar.markdown("Manage your church music collection")
