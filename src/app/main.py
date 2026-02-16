"""Streamlit application for church music organizer."""

import streamlit as st
import os
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import init_db, get_db_session, MusicPiece, MusicFile, Tag, FileType
from src.ocr import SheetMusicOCR, MusicXMLConverter
from datetime import datetime
import shutil

# Page configuration
st.set_page_config(
    page_title="Church Music Organizer",
    page_icon="🎵",
    layout="wide"
)

# Initialize database
init_db()

# Sidebar navigation
st.sidebar.title("🎵 Church Music Organizer")
page = st.sidebar.selectbox(
    "Navigation",
    ["Home", "Add Music", "Browse Music", "Upload Files", "OCR Processing", "Statistics"]
)

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
    
    if ext in ['.mscz', '.mscx']:
        return FileType.MUSESCORE
    elif ext == '.pdf':
        return FileType.PDF
    elif ext in ['.xml', '.musicxml']:
        return FileType.XML
    elif ext in ['.txt', '.ly']:
        return FileType.TEXT
    elif ext in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
        return FileType.SCAN
    else:
        return FileType.OTHER


# Main content based on selected page
if page == "Home":
    st.title("🎵 Welcome to Church Music Organizer")
    st.markdown("""
    This application helps you organize, archive, and process sheet music materials
    for church music activities.
    
    ## Features:
    - 📚 **Database Management**: Store and organize digital sheet music (scans, PDFs, MuseScore files)
    - 🔍 **OCR Processing**: Process scanned sheet music with advanced OCR
    - 📝 **Metadata Management**: Add and edit information about music pieces
    - 🏷️ **Tagging System**: Categorize music by occasion, season, and more
    - 📊 **Statistics**: View your music collection statistics
    
    ## Quick Start:
    1. Use **Add Music** to create a new music piece entry
    2. Use **Upload Files** to attach files to your music pieces
    3. Use **OCR Processing** to extract text from scanned music
    4. Use **Browse Music** to search and view your collection
    """)
    
    # Show statistics
    with get_db_session() as db:
        total_pieces = db.query(MusicPiece).count()
        total_files = db.query(MusicFile).count()
        total_tags = db.query(Tag).count()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Music Pieces", total_pieces)
    col2.metric("Files", total_files)
    col3.metric("Tags", total_tags)

elif page == "Add Music":
    st.title("📝 Add New Music Piece")
    
    with st.form("add_music_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            title = st.text_input("Title *", help="Required field")
            composer = st.text_input("Composer")
            arranger = st.text_input("Arranger")
            genre = st.text_input("Genre", help="e.g., Hymn, Psalm, Anthem")
            language = st.text_input("Language", value="Polish")
        
        with col2:
            key_signature = st.text_input("Key Signature", help="e.g., C major, D minor")
            time_signature = st.text_input("Time Signature", help="e.g., 4/4, 3/4")
            tempo = st.text_input("Tempo", help="e.g., Allegro, Andante, 120 BPM")
            occasion = st.text_input("Occasion", help="e.g., Easter, Christmas, Wedding")
            liturgical_season = st.text_input("Liturgical Season", help="e.g., Advent, Lent")
        
        notes = st.text_area("Notes", help="Additional information about this piece")
        
        # Tags
        tags_input = st.text_input("Tags (comma-separated)", help="e.g., festive, solemn, traditional")
        
        submit = st.form_submit_button("Add Music Piece")
        
        if submit:
            if not title:
                st.error("Title is required!")
            else:
                try:
                    with get_db_session() as db:
                        # Create music piece
                        piece = MusicPiece(
                            title=title,
                            composer=composer or None,
                            arranger=arranger or None,
                            genre=genre or None,
                            key_signature=key_signature or None,
                            time_signature=time_signature or None,
                            tempo=tempo or None,
                            occasion=occasion or None,
                            liturgical_season=liturgical_season or None,
                            language=language or None,
                            notes=notes or None
                        )
                        db.add(piece)
                        db.flush()
                        
                        # Add tags
                        if tags_input:
                            tag_names = [t.strip() for t in tags_input.split(',') if t.strip()]
                            for tag_name in tag_names:
                                tag = db.query(Tag).filter_by(name=tag_name).first()
                                if not tag:
                                    tag = Tag(name=tag_name)
                                    db.add(tag)
                                piece.tags.append(tag)
                        
                        db.commit()
                        st.success(f"✅ Music piece '{title}' added successfully! (ID: {piece.id})")
                except Exception as e:
                    st.error(f"Error adding music piece: {str(e)}")

elif page == "Browse Music":
    st.title("📚 Browse Music Collection")
    
    # Filters
    col1, col2, col3 = st.columns(3)
    
    with col1:
        search_title = st.text_input("Search by title")
    with col2:
        search_composer = st.text_input("Search by composer")
    with col3:
        search_occasion = st.text_input("Search by occasion")
    
    # Query database
    with get_db_session() as db:
        query = db.query(MusicPiece)
        
        if search_title:
            query = query.filter(MusicPiece.title.contains(search_title))
        if search_composer:
            query = query.filter(MusicPiece.composer.contains(search_composer))
        if search_occasion:
            query = query.filter(MusicPiece.occasion.contains(search_occasion))
        
        pieces = query.order_by(MusicPiece.updated_at.desc()).all()
    
    st.write(f"Found {len(pieces)} music piece(s)")
    
    # Display results
    for piece in pieces:
        with st.expander(f"🎵 {piece.title} {f'- {piece.composer}' if piece.composer else ''}"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**ID:** {piece.id}")
                if piece.composer:
                    st.write(f"**Composer:** {piece.composer}")
                if piece.arranger:
                    st.write(f"**Arranger:** {piece.arranger}")
                if piece.genre:
                    st.write(f"**Genre:** {piece.genre}")
                if piece.language:
                    st.write(f"**Language:** {piece.language}")
            
            with col2:
                if piece.key_signature:
                    st.write(f"**Key:** {piece.key_signature}")
                if piece.time_signature:
                    st.write(f"**Time:** {piece.time_signature}")
                if piece.tempo:
                    st.write(f"**Tempo:** {piece.tempo}")
                if piece.occasion:
                    st.write(f"**Occasion:** {piece.occasion}")
                if piece.liturgical_season:
                    st.write(f"**Season:** {piece.liturgical_season}")
            
            if piece.notes:
                st.write(f"**Notes:** {piece.notes}")
            
            if piece.tags:
                tags_str = ", ".join([tag.name for tag in piece.tags])
                st.write(f"**Tags:** {tags_str}")
            
            if piece.files:
                st.write(f"**Files ({len(piece.files)}):**")
                for file in piece.files:
                    st.write(f"- {file.original_filename} ({file.file_type.value})")

elif page == "Upload Files":
    st.title("📤 Upload Files")
    
    # Select music piece
    with get_db_session() as db:
        pieces = db.query(MusicPiece).order_by(MusicPiece.title).all()
    
    if not pieces:
        st.warning("No music pieces found. Please add a music piece first.")
    else:
        piece_options = {f"{p.id}: {p.title} {f'- {p.composer}' if p.composer else ''}": p.id 
                        for p in pieces}
        
        selected_piece_str = st.selectbox("Select Music Piece", list(piece_options.keys()))
        selected_piece_id = piece_options[selected_piece_str]
        
        uploaded_files = st.file_uploader(
            "Upload files",
            accept_multiple_files=True,
            help="Supported: PDF, images, MuseScore files, MusicXML, text files"
        )
        
        description = st.text_area("Description (optional)")
        
        if st.button("Upload"):
            if uploaded_files:
                try:
                    with get_db_session() as db:
                        for uploaded_file in uploaded_files:
                            # Save file
                            file_path = save_uploaded_file(uploaded_file, selected_piece_id)
                            
                            # Create database entry
                            music_file = MusicFile(
                                music_piece_id=selected_piece_id,
                                file_path=file_path,
                                file_type=get_file_type(uploaded_file.name),
                                original_filename=uploaded_file.name,
                                file_size=uploaded_file.size,
                                description=description or None
                            )
                            db.add(music_file)
                        
                        db.commit()
                        st.success(f"✅ {len(uploaded_files)} file(s) uploaded successfully!")
                except Exception as e:
                    st.error(f"Error uploading files: {str(e)}")
            else:
                st.warning("Please select files to upload")

elif page == "OCR Processing":
    st.title("🔍 OCR Processing")
    
    st.markdown("""
    Process scanned sheet music to extract text and metadata.
    """)
    
    # Select file to process
    with get_db_session() as db:
        files = db.query(MusicFile, MusicPiece).join(MusicPiece).filter(
            MusicFile.file_type.in_([FileType.SCAN, FileType.PDF])
        ).all()
    
    if not files:
        st.warning("No scan or PDF files found. Please upload files first.")
    else:
        file_options = {
            f"{f.MusicPiece.title} - {f.MusicFile.original_filename}": f.MusicFile.id 
            for f in files
        }
        
        selected_file_str = st.selectbox("Select File to Process", list(file_options.keys()))
        selected_file_id = file_options[selected_file_str]
        
        if st.button("Process with OCR"):
            try:
                with get_db_session() as db:
                    music_file = db.query(MusicFile).filter_by(id=selected_file_id).first()
                    
                    if not music_file:
                        st.error("File not found")
                    else:
                        with st.spinner("Processing..."):
                            ocr = SheetMusicOCR()
                            
                            if music_file.file_type == FileType.PDF:
                                results = ocr.process_pdf(music_file.file_path)
                                
                                st.success("✅ Processing complete!")
                                
                                for i, result in enumerate(results):
                                    st.subheader(f"Page {result.get('page', i+1)}")
                                    st.write(f"**Confidence:** {result.get('confidence', 0):.2f}%")
                                    st.text_area(f"Extracted Text (Page {i+1})", 
                                               result.get('text', ''), height=200)
                            else:
                                result = ocr.extract_text(music_file.file_path)
                                
                                st.success("✅ Processing complete!")
                                st.write(f"**Confidence:** {result.get('confidence', 0):.2f}%")
                                st.text_area("Extracted Text", result.get('text', ''), height=300)
                                
                                # Check if contains music notation
                                has_notation = ocr.detect_music_notation(music_file.file_path)
                                if has_notation:
                                    st.info("✅ Music notation detected in this image")
                                else:
                                    st.warning("⚠️ No music notation detected")
                            
                            # Mark as processed
                            music_file.is_processed = 1
                            db.commit()
                            
            except Exception as e:
                st.error(f"Error processing file: {str(e)}")

elif page == "Statistics":
    st.title("📊 Collection Statistics")
    
    with get_db_session() as db:
        # Basic stats
        total_pieces = db.query(MusicPiece).count()
        total_files = db.query(MusicFile).count()
        total_tags = db.query(Tag).count()
        
        st.subheader("Overview")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Music Pieces", total_pieces)
        col2.metric("Total Files", total_files)
        col3.metric("Total Tags", total_tags)
        
        # Files by type
        st.subheader("Files by Type")
        from sqlalchemy import func
        file_counts = db.query(
            MusicFile.file_type, func.count(MusicFile.id)
        ).group_by(MusicFile.file_type).all()
        
        if file_counts:
            for file_type, count in file_counts:
                st.write(f"- **{file_type.value}**: {count}")
        else:
            st.write("No files yet")
        
        # Most used tags
        st.subheader("Most Used Tags")
        from sqlalchemy import func
        from src.database.models import MusicPieceTag
        
        tag_counts = db.query(
            Tag.name, func.count(MusicPieceTag.music_piece_id)
        ).join(MusicPieceTag).group_by(Tag.name).order_by(
            func.count(MusicPieceTag.music_piece_id).desc()
        ).limit(10).all()
        
        if tag_counts:
            for tag_name, count in tag_counts:
                st.write(f"- **{tag_name}**: {count} piece(s)")
        else:
            st.write("No tags yet")
        
        # Recent additions
        st.subheader("Recent Additions")
        recent_pieces = db.query(MusicPiece).order_by(
            MusicPiece.created_at.desc()
        ).limit(5).all()
        
        if recent_pieces:
            for piece in recent_pieces:
                st.write(f"- {piece.title} {f'({piece.composer})' if piece.composer else ''}")
        else:
            st.write("No music pieces yet")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("**Church Music Organizer v1.0**")
st.sidebar.markdown("Manage your church music collection")
