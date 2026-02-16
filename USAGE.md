# Usage Examples

## Getting Started

### 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Tesseract OCR (Ubuntu/Debian)
sudo apt-get install tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng
```

### 2. Run the Application

```bash
# Using the run script
./run.sh

# Or directly with streamlit
streamlit run src/app/main.py
```

## Using the Application

### Adding a New Music Piece

1. Navigate to **Add Music** page
2. Fill in the required information:
   - Title (required)
   - Composer, arranger
   - Musical details (key, time signature, tempo)
   - Liturgical information (occasion, season)
   - Tags for categorization
3. Click "Add Music Piece"

Example:
- Title: "Ave Maria"
- Composer: "Franz Schubert"
- Genre: "Hymn"
- Key Signature: "Bb major"
- Occasion: "Wedding"
- Tags: "classical, wedding, marian"

### Uploading Files

1. Navigate to **Upload Files** page
2. Select the music piece from dropdown
3. Choose files to upload (PDF, scans, MuseScore files, etc.)
4. Optionally add description
5. Click "Upload"

Supported file types:
- PDF files (.pdf)
- Image scans (.jpg, .jpeg, .png, .tiff, .bmp)
- MuseScore files (.mscz, .mscx)
- MusicXML files (.xml, .musicxml)
- Text files (.txt, .ly)

### Processing Scanned Music with OCR

1. Navigate to **OCR Processing** page
2. Select a scanned image or PDF file from the dropdown
3. Click "Process with OCR"
4. View extracted text and confidence score
5. For scanned sheet music, the system will detect if music notation is present

The OCR module:
- Preprocesses images for better text recognition
- Extracts text from scans and PDFs
- Detects music notation (staff lines)
- Provides confidence scores
- Supports multiple languages (Polish, English by default)

### Browsing Your Collection

1. Navigate to **Browse Music** page
2. Use search filters:
   - Search by title
   - Search by composer
   - Search by occasion
3. View detailed information in expandable cards
4. See all associated files and tags

### Viewing Statistics

Navigate to **Statistics** page to see:
- Total number of music pieces
- Total number of files
- Files by type distribution
- Most used tags
- Recent additions

## Python API Usage

### Database Operations

```python
from src.database import init_db, get_db_session, MusicPiece, MusicFile, Tag, FileType

# Initialize database
init_db()

# Create a new music piece
with get_db_session() as db:
    piece = MusicPiece(
        title="Ave Maria",
        composer="Franz Schubert",
        genre="Hymn",
        key_signature="Bb major",
        occasion="Wedding"
    )
    db.add(piece)
    db.commit()
    print(f"Created piece with ID: {piece.id}")

# Query music pieces
with get_db_session() as db:
    pieces = db.query(MusicPiece).filter(
        MusicPiece.occasion == "Wedding"
    ).all()
    for piece in pieces:
        print(f"{piece.title} by {piece.composer}")

# Add tags
with get_db_session() as db:
    piece = db.query(MusicPiece).filter_by(title="Ave Maria").first()
    tag = Tag(name="wedding")
    piece.tags.append(tag)
    db.commit()
```

### OCR Processing

```python
from src.ocr import SheetMusicOCR

# Initialize OCR processor
ocr = SheetMusicOCR(output_dir="data/processed")

# Process a scanned image
result = ocr.extract_text("path/to/scan.jpg", lang='pol+eng')
print(f"Confidence: {result['confidence']:.2f}%")
print(f"Text: {result['text']}")

# Check if image contains music notation
has_notation = ocr.detect_music_notation("path/to/scan.jpg")
print(f"Music notation detected: {has_notation}")

# Process a PDF file
results = ocr.process_pdf("path/to/score.pdf")
for page_result in results:
    print(f"Page {page_result['page']}: {page_result['text']}")
```

### MusicXML Conversion

```python
from src.ocr import MusicXMLConverter

# Initialize converter
converter = MusicXMLConverter(output_dir="data/processed")

# Create a basic score from metadata
score = converter.create_from_metadata(
    title="Ave Maria",
    composer="Franz Schubert",
    key="Bb",
    time_sig="4/4"
)

# Save as MusicXML
converter.save_as_musicxml(score, "output/ave_maria.xml")

# Convert to MuseScore (requires MuseScore installed)
converter.convert_to_musescore("output/ave_maria.xml", "output/ave_maria.mscz")
```

## Advanced Features

### Custom Database Queries

```python
from src.database import get_db_session, MusicPiece
from sqlalchemy import func

# Find all pieces in a specific key
with get_db_session() as db:
    c_major_pieces = db.query(MusicPiece).filter(
        MusicPiece.key_signature.like("%C major%")
    ).all()

# Get statistics
with get_db_session() as db:
    count_by_composer = db.query(
        MusicPiece.composer,
        func.count(MusicPiece.id)
    ).group_by(MusicPiece.composer).all()
    
    for composer, count in count_by_composer:
        print(f"{composer}: {count} pieces")
```

### Batch Processing

```python
from src.database import get_db_session, MusicFile, FileType
from src.ocr import SheetMusicOCR
from pathlib import Path

# Process all unprocessed scans
ocr = SheetMusicOCR()

with get_db_session() as db:
    unprocessed_files = db.query(MusicFile).filter(
        MusicFile.file_type == FileType.SCAN,
        MusicFile.is_processed == 0
    ).all()
    
    for music_file in unprocessed_files:
        print(f"Processing {music_file.original_filename}...")
        result = ocr.extract_text(music_file.file_path)
        
        # Save extracted text
        text_path = Path(music_file.file_path).with_suffix('.txt')
        text_path.write_text(result['text'])
        
        # Mark as processed
        music_file.is_processed = 1
    
    db.commit()
```

## Troubleshooting

### Tesseract Not Found

If you get an error about Tesseract not being found:

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng

# macOS
brew install tesseract tesseract-lang

# Windows - Add Tesseract to PATH or set:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

### Database Issues

If you encounter database errors, try reinitializing:

```python
from src.database import init_db
init_db()
```

Or delete the database file and restart:

```bash
rm church_music.db
streamlit run src/app/main.py
```

### Import Errors

Make sure you're running from the project root directory and all dependencies are installed:

```bash
cd church-music-organizer
pip install -r requirements.txt
```
