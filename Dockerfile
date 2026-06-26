FROM python:3.10-slim

# Install system dependencies including Tesseract OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-pol \
    tesseract-ocr-eng \
    poppler-utils \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry

WORKDIR /app

# Copy only dependency manifests first (cache layer)
COPY pyproject.toml poetry.lock* ./

# In the container we don't need a virtualenv — install globally
RUN poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p data/uploads data/processed

# Expose NiceGUI port
EXPOSE 8080

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8080/ || exit 1

# Run the application (NiceGUI binds to 0.0.0.0 in container mode)
ENV CMO_NG_HOST=0.0.0.0
CMD ["python", "-m", "src.app_ng.main"]
