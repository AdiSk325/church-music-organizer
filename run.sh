#!/bin/bash
# Run the Streamlit application

echo "Starting Church Music Organizer..."
echo "The application will open in your browser at http://localhost:8501"
echo ""

# Navigate to the correct directory
cd "$(dirname "$0")"

# Run the Streamlit app via Poetry
poetry run streamlit run src/app/main.py
