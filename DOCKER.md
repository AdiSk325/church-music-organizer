# Docker Deployment

## Quick Start with Docker

### Using Docker Compose (Recommended)

```bash
# Build and run the application
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the application
docker-compose down
```

The application will be available at: http://localhost:8501

### Using Docker Directly

```bash
# Build the image
docker build -t church-music-organizer .

# Run the container
docker run -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/church_music.db:/app/church_music.db \
  church-music-organizer
```

## Docker Features

The Docker image includes:
- Python 3.10
- Tesseract OCR with Polish and English language support
- All required Python dependencies
- Streamlit application server
- Automatic health checks

## Persistent Data

The following directories and files are mounted as volumes:
- `./data` - Uploaded and processed files
- `./church_music.db` - SQLite database

This ensures your data persists even if you recreate the container.

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose down
docker-compose up -d --build
```
