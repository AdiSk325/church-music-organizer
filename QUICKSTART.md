# Quick Start Guide

## 1. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Tesseract OCR
# Ubuntu/Debian:
sudo apt-get install tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng

# macOS:
brew install tesseract tesseract-lang
```

## 2. Run the Application

```bash
# Simple way
./run.sh

# Or directly
streamlit run src/app/main.py
```

The application will open at: http://localhost:8501

## 3. Quick Tutorial

### Add Your First Music Piece

1. Click **Add Music** in the sidebar
2. Enter the title (required)
3. Fill in other details (composer, key, etc.)
4. Add tags (comma-separated): "hymn, easter, traditional"
5. Click **Add Music Piece**

### Upload Files

1. Click **Upload Files**
2. Select the music piece from dropdown
3. Choose files to upload (PDF, scans, etc.)
4. Click **Upload**

### Process with OCR

1. Click **OCR Processing**
2. Select a scanned file or PDF
3. Click **Process with OCR**
4. View extracted text and confidence score

### Browse Your Collection

1. Click **Browse Music**
2. Use search filters to find pieces
3. Expand cards to see details

## Using Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## Troubleshooting

**Tesseract not found?**
- Make sure Tesseract is installed and in PATH
- Ubuntu: `sudo apt-get install tesseract-ocr`
- macOS: `brew install tesseract`

**Database errors?**
- Delete `church_music.db` and restart the app
- The database will be recreated automatically

**Import errors?**
- Run from project root directory
- Ensure all dependencies installed: `pip install -r requirements.txt`

## Next Steps

- Read [USAGE.md](USAGE.md) for detailed examples
- Check [FEATURES.md](FEATURES.md) for all features
- See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute
