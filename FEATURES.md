# Church Music Organizer - Features Overview

## Implemented Features

### 1. Database Module (✅ Complete)

#### SQLAlchemy Models
- **MusicPiece**: Main entity for storing music piece information
  - Metadata: title, composer, arranger, genre, language
  - Musical properties: key signature, time signature, tempo
  - Liturgical context: occasion, liturgical season
  - Notes field for additional information
  - Timestamps: created_at, updated_at
  
- **MusicFile**: Files associated with music pieces
  - Support for multiple file types: SCAN, PDF, MUSESCORE, XML, TEXT, OTHER
  - File metadata: path, size, MIME type, original filename
  - Processing status tracking
  - Relationships to parent music piece
  
- **Tag**: Flexible tagging system
  - Tag name and description
  - Many-to-many relationship with music pieces
  
- **MusicPieceTag**: Association table for tags

#### Database Features
- SQLite database (can be configured for other SQL databases)
- Automatic table creation
- Session management with context managers
- Support for complex queries and relationships

### 2. OCR Module (✅ Complete)

#### Sheet Music OCR (`sheet_music_ocr.py`)
- **Image Preprocessing**
  - Grayscale conversion
  - Adaptive thresholding
  - Noise reduction
  - Optimized for sheet music scans
  
- **Text Extraction**
  - Tesseract OCR integration
  - Multi-language support (Polish + English by default)
  - Confidence scoring
  - Block-level text extraction with coordinates
  
- **PDF Processing**
  - Convert PDF pages to images
  - Extract text from each page
  - Batch processing support
  
- **Music Notation Detection**
  - Hough line detection for staff lines
  - Automatic detection of music notation presence
  - Useful for categorizing scanned materials

#### MusicXML Converter (`musicxml_converter.py`)
- **Score Creation**
  - Create MusicXML scores from metadata
  - Integration with music21 library
  - Support for title, composer, key, time signature
  
- **Format Conversion**
  - Save as MusicXML format
  - Convert to MuseScore format (when MuseScore is installed)
  - Extensible for other music notation formats

### 3. Streamlit Application (✅ Complete)

#### User Interface Pages

**1. Home Page**
- Welcome message with feature overview
- Quick statistics dashboard
- Getting started guide

**2. Add Music Page**
- Comprehensive form for adding new music pieces
- Fields for all metadata (composer, genre, key, tempo, etc.)
- Tag management (comma-separated input)
- Form validation
- Success/error feedback

**3. Browse Music Page**
- Search and filter functionality
  - Search by title
  - Search by composer
  - Search by occasion
- Expandable cards for each piece
- Display all metadata and associated files
- Show tags and file counts

**4. Upload Files Page**
- Select music piece from dropdown
- Multiple file upload support
- Automatic file type detection
- Optional description field
- File size and metadata tracking

**5. OCR Processing Page**
- Select scanned files or PDFs
- Process with advanced OCR
- Display extracted text
- Show confidence scores
- Music notation detection
- Mark files as processed

**6. Statistics Page**
- Collection overview (total pieces, files, tags)
- Files by type distribution
- Most used tags
- Recent additions

#### Application Features
- Responsive layout (wide mode)
- Intuitive navigation
- Real-time database updates
- Error handling and user feedback
- File management (upload, storage, organization)

## Technical Stack

### Backend
- **SQLAlchemy**: ORM for database management
- **SQLite**: Default database (configurable)
- **Pytesseract**: OCR engine wrapper
- **OpenCV**: Image processing
- **Pillow**: Image handling
- **pdf2image**: PDF to image conversion
- **music21**: Music notation library

### Frontend
- **Streamlit**: Web application framework
- Simple, intuitive interface
- No JavaScript required
- Automatic updates and reactivity

### Testing
- **pytest**: Testing framework
- Unit tests for database models
- Integration test script
- Relationship testing

## File Organization

### Data Storage
```
data/
├── uploads/          # Uploaded files organized by music piece ID
│   └── {piece_id}/
│       ├── scan1.pdf
│       ├── score.mscz
│       └── ...
└── processed/        # OCR output and processed files
```

### Database
- SQLite database file: `church_music.db`
- Tables: music_pieces, music_files, tags, music_piece_tags

## Deployment Options

### 1. Local Development
```bash
pip install -r requirements.txt
streamlit run src/app/main.py
```

### 2. Docker
```bash
docker-compose up -d
```

### 3. Production
- Can be deployed on any platform supporting Streamlit
- Streamlit Cloud
- AWS, GCP, Azure
- Self-hosted servers

## Requirements Met

Based on the problem statement, here's how each requirement is addressed:

### ✅ Database for Digital Sheet Music
- Comprehensive database schema
- Support for all mentioned file types:
  - ✅ Scans (JPEG, PNG, TIFF, BMP)
  - ✅ PDFs
  - ✅ MuseScore files (.mscz, .mscx)
  - ✅ Texts
  - ✅ Metadata (extensive metadata fields)
- File organization and tracking
- Tag-based categorization

### ✅ Advanced OCR for Sheet Music
- Image preprocessing for better OCR results
- Text extraction with confidence scoring
- PDF processing (multi-page support)
- Music notation detection
- MusicXML conversion capability
- Integration with music21 for further processing
- Support for importing to MuseScore

### ✅ Application for Managing Materials
- Streamlit web interface
- User-friendly forms for data entry
- Search and filtering capabilities
- File upload and management
- OCR processing interface
- Statistics and reporting

## Future Enhancements (Not in Scope)

Potential areas for future development:
1. Advanced music notation OCR (e.g., using Audiveris)
2. Audio file support and playback
3. Automatic metadata extraction from files
4. Export functionality (CSV, Excel)
5. Advanced search with filters
6. User authentication and multi-user support
7. Cloud storage integration
8. Mobile app version
9. Automated backup system
10. Music analysis features

## Security Considerations

- Input validation on all forms
- File type validation
- SQL injection protection (via SQLAlchemy ORM)
- Path traversal protection
- File size limits (configurable in Streamlit)

## Performance

- Efficient database queries with proper indexing
- Lazy loading of relationships
- Pagination support in browse functionality
- Async file processing capability
- Optimized image processing

## Documentation

- ✅ README.md - Project overview and installation
- ✅ USAGE.md - Detailed usage examples
- ✅ DOCKER.md - Docker deployment guide
- ✅ Inline code documentation
- ✅ Type hints where applicable

## Testing

- ✅ Unit tests for database models
- ✅ Integration test script
- ✅ Test fixtures and test database
- Tests can be run with: `pytest tests/`
- Integration test: `python test_integration.py`
