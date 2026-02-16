# Church Music Organizer 🎵

A comprehensive application for organizing, archiving, and processing sheet music materials, especially for church musicians.

## Features

- **📚 Database Management**: Store and organize digital sheet music (scans, PDFs, MuseScore files, MusicXML, texts)
- **🔍 OCR Processing**: Advanced OCR for processing scanned sheet music with text extraction and music notation detection
- **📝 Metadata Management**: Comprehensive metadata fields including composer, arranger, genre, key, tempo, occasion, liturgical season
- **🏷️ Tagging System**: Flexible tagging system to categorize music pieces
- **📊 Statistics**: View collection statistics and insights
- **🖥️ Web Interface**: User-friendly Streamlit web application

## Requirements

- Python 3.8+
- Tesseract OCR (for OCR functionality)
- MuseScore (optional, for MusicXML to MuseScore conversion)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/AdiSk325/church-music-organizer.git
cd church-music-organizer
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Install Tesseract OCR:

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng
```

**macOS:**
```bash
brew install tesseract tesseract-lang
```

**Windows:**
Download and install from: https://github.com/UB-Mannheim/tesseract/wiki

4. (Optional) Install MuseScore for advanced conversion:
Download from: https://musescore.org/

## Usage

### Run the Streamlit Application

```bash
streamlit run src/app/main.py
```

The application will open in your default web browser at `http://localhost:8501`.

### Application Features

1. **Home**: Overview and quick statistics
2. **Add Music**: Create new music piece entries with metadata
3. **Browse Music**: Search and filter your music collection
4. **Upload Files**: Attach files (PDFs, scans, MuseScore files) to music pieces
5. **OCR Processing**: Extract text from scanned music and detect music notation
6. **Statistics**: View detailed collection statistics

## Project Structure

```
church-music-organizer/
├── src/
│   ├── database/          # Database models and management
│   │   ├── models.py      # SQLAlchemy models
│   │   └── database.py    # Database initialization
│   ├── ocr/              # OCR and music processing
│   │   ├── sheet_music_ocr.py    # OCR functionality
│   │   └── musicxml_converter.py # MusicXML conversion
│   └── app/              # Streamlit application
│       └── main.py       # Main application
├── data/
│   ├── uploads/          # Uploaded files storage
│   └── processed/        # Processed OCR outputs
├── tests/                # Test files
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Database Schema

The application uses SQLite database with the following main tables:

- **music_pieces**: Main music piece metadata (title, composer, genre, key, tempo, etc.)
- **music_files**: Files associated with music pieces (PDFs, scans, MuseScore files)
- **tags**: Tags for categorization
- **music_piece_tags**: Many-to-many relationship between pieces and tags

## Development

### Adding New Features

The application is designed to be extensible. Key areas for enhancement:

1. **Database**: Add models in `src/database/models.py`
2. **OCR**: Enhance processing in `src/ocr/`
3. **UI**: Add pages in `src/app/main.py`

### Testing

```bash
# Run tests (when implemented)
pytest tests/
```

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on GitHub.