# Installation Guide — Church Music Organizer

Dependencies split into two groups: **Python packages** (managed by Poetry) and
**system binaries** that must be installed separately.

---

## System Dependencies

### Audiveris (OMR engine — PDF → MusicXML)

Audiveris is required for the OMR pipeline (`src/ocr/pdf_to_musicxml.py`).

**Windows (recommended)**

1. Download the latest installer from <https://audiveris.github.io/audiveris/>  
   (choose the `.exe` installer — it bundles its own JRE).
2. Run the installer; the default target is `D:\Audiveris\` or
   `C:\Program Files\Audiveris\`.
3. The application discovers the launcher automatically at the following paths
   (checked in order):
   - `%AUDIVERIS_PATH%` environment variable ← set this for a non-default install
   - `%AUDIVERIS_JAR%` environment variable  ← set this if you have only the jar
   - `Audiveris` on `%PATH%`
   - `D:\Audiveris\Audiveris.exe`
   - `C:\Program Files\Audiveris\Audiveris.exe`
   - `%LOCALAPPDATA%\Programs\Audiveris\Audiveris.exe`
   - `~/Audiveris/bin/Audiveris.bat`

**Setting `AUDIVERIS_PATH` (non-default install location)**

```powershell
# PowerShell — permanent (current user)
[System.Environment]::SetEnvironmentVariable(
    "AUDIVERIS_PATH",
    "E:\Tools\Audiveris\Audiveris.exe",
    "User"
)
```

Or add to `.env` / shell profile:

```bash
export AUDIVERIS_PATH="/opt/audiveris/bin/Audiveris"
```

**Linux / macOS**

```bash
# Debian / Ubuntu — build from source or use the provided .deb if available
# See https://github.com/Audiveris/audiveris/wiki/Installation

# Homebrew (macOS, unofficial)
brew install audiveris   # if available in tap
```

**Java requirement**  
The bundled Windows `.exe` launcher ships with its own JRE (OpenJDK).  If you
are using the fat-jar (`audiveris.jar`) directly, Java 11 or later must be
available on `PATH`.

**Verify**

```bash
Audiveris -help        # Windows
audiveris -help        # Linux / macOS
```

---

### Tesseract OCR (text OCR inside sheet music)

**Windows**

Download the installer from <https://github.com/UB-Mannheim/tesseract/wiki>.
Install language packs **pol** (Polish) and **eng** (English) during setup.

If Tesseract is not on `PATH`, set:

```powershell
[System.Environment]::SetEnvironmentVariable(
    "TESSERACT_CMD",
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "User"
)
```

**Linux**

```bash
sudo apt install tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng
```

**Verify**

```bash
tesseract --list-langs   # should include pol, eng
```

---

### Poppler (pdf2image — PDF page rendering)

Required by `src/ocr/sheet_music_ocr.py` for multi-page PDF scanning.

**Windows**  
Download from <https://github.com/oschwartz10612/poppler-windows/releases>,
extract, and add the `bin/` folder to `%PATH%`.

**Linux**

```bash
sudo apt install poppler-utils
```

---

### libmagic (MIME type detection)

Required by the Streamlit upload UI.

**Windows**  
Bundled with `python-magic-bin` (installed automatically by Poetry on Windows).

**Linux**

```bash
sudo apt install libmagic1
```

---

### MuseScore (optional — `.mscz` export)

Required only if you use `MusicXMLConverter.convert_to_musescore()`.

Download from <https://musescore.org/>.  On Windows the CLI is accessible as
`mscore` or `MuseScore4.exe`; add its `bin/` folder to `%PATH%`.

---

## Python Setup

```bash
pip install poetry          # once, if Poetry is not installed
poetry install              # creates .venv, installs all packages
```

All Python packages are declared in `pyproject.toml` and resolved in
`poetry.lock`.  No manual `pip install` should be needed.

---

## Quick Verification

```python
from src.ocr.sheet_music_ocr import tesseract_available
from src.ocr.pdf_to_musicxml import audiveris_available

print("Tesseract:", tesseract_available())   # True / False
print("Audiveris:", audiveris_available())   # True / False
```
