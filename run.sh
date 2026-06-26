#!/bin/bash
# Run the Church Music Organizer (NiceGUI desktop-first UI)

echo "Starting Church Music Organizer (NiceGUI)..."
echo "The application will open in your browser at http://localhost:8080"
echo "Set CMO_NG_NATIVE=1 for a native desktop window (requires pywebview)."
echo ""

# Navigate to the correct directory
cd "$(dirname "$0")"

# Run the NiceGUI app via Poetry
poetry run python -m src.app_ng.main
