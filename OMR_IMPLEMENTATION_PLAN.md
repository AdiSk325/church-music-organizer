# Comprehensive OMR Implementation Plan
## Converting Scanned Sheet Music (PDF/JPG) → Accurate MusicXML

---

## 1. RESEARCH SUMMARY: Open-Source OMR Libraries

### 1.1 Evaluated Libraries

| Library | Type | Stars | Output | Multi-voice | Polyphonic | Active | License |
|---------|------|-------|--------|-------------|------------|--------|---------|
| **Audiveris** | Java GUI+CLI | 2.3k | MusicXML 4.0 | ✅ Yes | ✅ Yes | ✅ v5.9.0 (Dec 2025) | AGPL-3.0 |
| **oemer** | Python, DL | 659 | MusicXML | ✅ Yes (2 tracks) | ⚠️ Limited | ⚠️ v0.1.8 (Nov 2024) | MIT |
| **homr** | Python, DL | 132 | MusicXML | ✅ Yes (grand staff) | ✅ Yes (TrOMR) | ✅ Active (Feb 2026) | AGPL-3.0 |
| **tf-end-to-end** | Python, TF | 153 | Semantic tokens | ❌ Monophonic only | ❌ No | ❌ Archived | MIT |
| **MusicObjectDetector-TF** | Python, TF1 | 92 | Object bboxes | ❌ Detection only | ❌ No | ❌ Archived (4yr) | Apache-2.0 |

### 1.2 Recommendation: Two-Engine Strategy

**Primary Engine: `homr`** (Python, pip-installable)
- Built on oemer's segmentation + Polyphonic-TrOMR transformer
- Better robustness, polyphonic support, actively maintained
- Pure Python, integrates directly into our project
- Outputs MusicXML directly

**Secondary Engine: `Audiveris`** (Java, CLI)
- Most mature and accurate OMR engine available
- Best for complex scores (orchestral, 4+ voices, figured bass)
- Exports MusicXML 4.0 with full musical detail
- Requires Java runtime, invoked via subprocess

**Fallback: `oemer`** (Python, pip-installable)
- Simpler than homr, good for single-staff/piano scores
- pip-installable, well documented
- Used internally by homr for segmentation models

---

## 2. ARCHITECTURE: Multi-Stage OMR Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                    INPUT: PDF / JPG / PNG / TIFF                  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 1: Preprocessing                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │ PDF→Images  │→ │ Deskew/Clean │→ │ Page Layout Analysis   │  │
│  │ (PyMuPDF)   │  │ (OpenCV)     │  │ (detect staves/text)   │  │
│  └─────────────┘  └──────────────┘  └────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 2: Music Recognition (OMR Engine)                         │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Engine Selection (auto or user choice):                  │    │
│  │                                                           │    │
│  │  Option A: homr (Python, polyphonic transformer)          │    │
│  │    • Segmentation → staff detection → TrOMR → MusicXML   │    │
│  │                                                           │    │
│  │  Option B: Audiveris (Java CLI, most accurate)            │    │
│  │    • Neural + template matching → full OMR → MusicXML     │    │
│  │                                                           │    │
│  │  Option C: oemer (Python, simpler pipeline)               │    │
│  │    • UNet segmentation → SVM classifiers → MusicXML       │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 3: Lyrics Extraction (parallel to Stage 2)                │
│  ┌─────────────────┐  ┌───────────────────────────────────────┐ │
│  │ Text extraction  │→ │ Lyrics alignment with notes           │ │
│  │ (PyMuPDF / OCR)  │  │ (position-based matching)             │ │
│  └─────────────────┘  └───────────────────────────────────────┘ │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 4: Metadata Extraction & Music Understanding              │
│  ┌────────────────┐ ┌───────────────┐ ┌────────────────────┐    │
│  │ Title/Composer │ │ Key/Time sig  │ │ Voices/Instruments │    │
│  │ Lyricist/Tempo │ │ from OMR data │ │ Clefs/Staves       │    │
│  │ (text OCR)     │ │               │ │ (from OMR data)    │    │
│  └────────────────┘ └───────────────┘ └────────────────────┘    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 5: MusicXML Construction & Validation                     │
│  ┌────────────────┐ ┌────────────────┐ ┌─────────────────────┐  │
│  │ Merge OMR +    │ │ Validate with  │ │ Export final         │  │
│  │ lyrics + meta  │ │ music21        │ │ MusicXML file        │  │
│  │ into score     │ │ (beat/measure  │ │ (.musicxml)          │  │
│  │                │ │  consistency)  │ │                      │  │
│  └────────────────┘ └────────────────┘ └─────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. DETAILED IMPLEMENTATION STEPS

### Phase 1: Core OMR Engine Integration (Priority: HIGH)

#### Step 1.1: Install and integrate `homr` as primary engine
**Files to create/modify:**
- `src/ocr/omr_engine.py` — New unified OMR engine interface
- `src/ocr/engines/homr_engine.py` — homr wrapper
- `src/ocr/engines/oemer_engine.py` — oemer wrapper
- `src/ocr/engines/audiveris_engine.py` — Audiveris CLI wrapper
- `src/ocr/engines/__init__.py`

**What homr does internally:**
1. Image preprocessing (contrast, denoising)
2. UNet segmentation: separates staff lines from symbols
3. Staff detection: finds 5-line staves, groups into systems
4. Symbol detection: noteheads, clefs, accidentals, rests, barlines
5. Transformer model (Polyphonic-TrOMR): reads each staff image → outputs symbolic sequence
6. Cross-validation: compares transformer output with notehead positions
7. MusicXML generation

**Dependencies to add (Poetry):**
```bash
poetry add homr        # Primary OMR engine
poetry add oemer       # Fallback OMR engine  
# Audiveris: external Java app, no pip package
```

**Abstract interface:**
```python
class OMREngine(ABC):
    @abstractmethod
    def recognize(self, image_path: str) -> OMRResult:
        """Run OMR on an image, return structured result."""
        pass

@dataclass
class OMRResult:
    musicxml_path: str           # Path to generated MusicXML
    raw_musicxml: str            # MusicXML content as string
    staves_detected: int         # Number of staves found
    measures_detected: int       # Number of measures
    key_signature: str           # Detected key (e.g., "A major")
    time_signature: str          # Detected time sig (e.g., "4/4")
    clefs: List[str]             # Clefs per staff (e.g., ["treble", "bass"])
    voices: int                  # Number of detected voices
    confidence: float            # Overall confidence score
    warnings: List[str]          # Any issues detected
    engine_used: str             # Which engine was used
```

#### Step 1.2: Image preprocessing pipeline
**File: `src/ocr/preprocessing.py`**

Tasks:
1. **PDF to images** — Use PyMuPDF to render each page as a high-DPI image (300 DPI minimum)
2. **Deskew** — Detect and correct rotation using OpenCV Hough lines on staff lines
3. **Binarization** — Adaptive thresholding (Sauvola or Otsu) for clean black/white
4. **Denoising** — Remove scanner artifacts while preserving thin lines (staff lines, stems)
5. **Border removal** — Detect and crop to content area
6. **Resolution normalization** — Scale to consistent DPI for model input
7. **Page segmentation** — Detect if multiple pieces per page, split if needed

```python
class ImagePreprocessor:
    def pdf_to_images(self, pdf_path: str, dpi: int = 300) -> List[str]
    def deskew(self, image_path: str) -> str
    def binarize(self, image_path: str) -> str
    def denoise(self, image_path: str) -> str
    def crop_to_content(self, image_path: str) -> str
    def preprocess_for_omr(self, input_path: str) -> List[str]  # full pipeline
```

---

### Phase 2: Music Structure Understanding (Priority: HIGH)

#### Step 2.1: Score analysis from OMR output
**File: `src/ocr/score_analyzer.py`**

After OMR produces raw MusicXML, analyze it using `music21`:

```python
class ScoreAnalyzer:
    def analyze(self, musicxml_path: str) -> ScoreMetadata:
        """Parse MusicXML and extract complete musical structure."""
        
    @dataclass
    class ScoreMetadata:
        # Identity
        title: str
        composer: str
        lyricist: str
        
        # Structure
        parts: List[PartInfo]     # instruments/voices
        measures_count: int
        key_signatures: List[KeySigInfo]  # may change mid-piece
        time_signatures: List[TimeSigInfo]
        tempo_markings: List[str]
        
        # Musical content
        clefs: Dict[str, str]     # part_id -> clef type
        voices_per_part: Dict[str, int]
        note_range: Dict[str, Tuple[str, str]]  # per part: (lowest, highest)
        
        # Quality metrics
        incomplete_measures: List[int]   # measures with wrong beat count
        empty_measures: List[int]
        suspicious_intervals: List[str]  # e.g., augmented 7ths
```

**What to detect and extract:**

| Property | Source | Method |
|----------|--------|--------|
| Title | PDF text (OCR) + MusicXML `<work-title>` | PyMuPDF text extraction from top of page |
| Composer | PDF text + MusicXML `<creator>` | Pattern matching (name + dates) |
| Key signature | MusicXML `<key>` element | music21 `score.analyze('key')` for verification |
| Time signature | MusicXML `<time>` element | Direct parse |
| Clefs | MusicXML `<clef>` per staff | Direct parse |
| Number of voices | MusicXML `<voice>` elements per part | Count unique voice numbers |
| Instruments | MusicXML `<part-name>` | Infer from clef + range if missing |
| Tempo | PDF text + MusicXML `<direction>` | Expression marking detection |
| Dynamics | MusicXML `<dynamics>` | Direct parse |
| Measure count | MusicXML measure elements | Count |
| Note values | MusicXML `<note>` durations | Summarize distribution |

#### Step 2.2: Multi-voice and instrument detection 
**File: `src/ocr/voice_detector.py`**

Specific logic for church music patterns:
- **SATB vocal scores:** 4 voices on 2 staves (Soprano+Alto on treble, Tenor+Bass on bass)
- **Piano + voice:** Vocal melody + piano accompaniment (2 hands)
- **Organ accompaniment:** 2-3 manual staves + pedal
- **Solo voice + figured bass**
- **Choir unison**

```python
class VoiceDetector:
    def detect_score_type(self, score: music21.stream.Score) -> ScoreType:
        """Classify the score arrangement type."""
        # Enum: SATB, PIANO_VOCAL, ORGAN, SOLO_VOICE, CHOIR_UNISON, etc.
    
    def split_voices(self, part: music21.stream.Part) -> List[music21.stream.Voice]:
        """Split a single part into separate voices where stems diverge."""
    
    def assign_voice_names(self, score_type: ScoreType, parts: List) -> Dict:
        """Assign S/A/T/B or instrument names based on clef and range."""
```

---

### Phase 3: Lyrics Integration (Priority: MEDIUM)

#### Step 3.1: Enhanced lyrics extraction
**File: `src/ocr/lyrics_extractor.py`** (enhance existing `pdf_text_extractor.py`)

1. **Text-layer extraction** (PyMuPDF) — for digital PDFs with embedded text
2. **OCR-based extraction** (Tesseract via pytesseract) — for scanned PDFs
3. **Position-aware extraction** — get bounding boxes for each text element
4. **Lyrics vs. non-lyrics classification** — separate title/composer/dynamics from actual lyrics

#### Step 3.2: Lyrics-to-note alignment
**File: `src/ocr/lyrics_aligner.py`**

```python
class LyricsAligner:
    def align_by_position(self, notes_with_positions, lyrics_with_positions):
        """Match lyrics to notes based on x-coordinate proximity."""
    
    def align_by_syllable_count(self, syllables: List[str], notes: List):
        """Align syllables to notes sequentially within each measure."""
    
    def merge_lyrics_into_score(self, score: music21.stream.Score, lyrics: LyricsData):
        """Add aligned lyrics to the music21 Score object."""
```

---

### Phase 4: MusicXML Validation & Export (Priority: HIGH)

#### Step 4.1: Music theory validation
**File: `src/ocr/musicxml_validator.py`**

```python
class MusicXMLValidator:
    def validate(self, score: music21.stream.Score) -> ValidationReport:
        """Comprehensive validation of the MusicXML score."""
    
    def check_measure_completeness(self, score) -> List[MeasureIssue]:
        """Verify each measure has correct beat count for its time signature."""
    
    def check_key_consistency(self, score) -> List[KeyIssue]:
        """Check if notes are consistent with declared key signature."""
    
    def check_voice_ranges(self, score) -> List[RangeIssue]:
        """Verify note ranges are reasonable for each voice/instrument."""
        # Soprano: C4-C6, Alto: F3-F5, Tenor: C3-C5, Bass: E2-E4
    
    def check_enharmonic_spelling(self, score) -> List[SpellingIssue]:
        """Check for common OMR errors in accidental interpretation."""
    
    def fix_common_errors(self, score) -> music21.stream.Score:
        """Auto-fix known OMR error patterns."""
        # - Missing rests to fill measures
        # - Tied notes across barlines
        # - Incorrect enharmonic spellings
        # - Beam grouping fixes

@dataclass
class ValidationReport:
    is_valid: bool
    total_issues: int
    critical_issues: List[str]    # Must fix (wrong measure lengths)
    warnings: List[str]           # Suspicious but might be correct
    suggestions: List[str]        # Style improvements
    measure_issues: List[MeasureIssue]
    range_issues: List[RangeIssue]
```

#### Step 4.2: Final MusicXML export
**File: Enhanced `src/ocr/musicxml_converter.py`**

```python
class MusicXMLExporter:
    def export(self, score, metadata, lyrics, output_path) -> ExportResult:
        """Create final validated MusicXML file."""
        # 1. Merge OMR score + metadata + lyrics
        # 2. Run validation
        # 3. Auto-fix what we can
        # 4. Write MusicXML 4.0
        # 5. Verify file opens in music21
        # 6. Report quality metrics
```

---

### Phase 5: Streamlit UI Integration (Priority: LOW)

#### Step 5.1: OMR processing page in the app
**Modify: `src/app/main.py`**

Add a new page/section:
- Upload PDF/image
- Select OMR engine (auto/homr/oemer/audiveris)
- Show preprocessing preview
- Run OMR with progress bar
- Display results: detected staves, key, time sig, voices
- Show validation report
- Download MusicXML button
- Option to save to database with extracted metadata

---

## 4. FILE STRUCTURE (proposed new/modified files)

```
src/
  ocr/
    __init__.py                    # Updated exports
    preprocessing.py               # NEW: Image preprocessing pipeline
    omr_engine.py                  # NEW: Abstract OMR engine interface
    score_analyzer.py              # NEW: Music structure analysis
    voice_detector.py              # NEW: Voice/instrument detection
    lyrics_extractor.py            # NEW: Enhanced lyrics pipeline
    lyrics_aligner.py              # NEW: Lyrics-to-note alignment
    musicxml_validator.py          # NEW: MusicXML validation
    musicxml_converter.py          # MODIFIED: Enhanced export
    pdf_text_extractor.py          # EXISTING: PyMuPDF text extraction
    sheet_music_ocr.py             # EXISTING: Keep for Tesseract OCR
    engines/
      __init__.py                  # NEW
      homr_engine.py               # NEW: homr integration
      oemer_engine.py              # NEW: oemer integration
      audiveris_engine.py          # NEW: Audiveris CLI wrapper
  app/
    main.py                        # MODIFIED: Add OMR page
convert_pdf_to_musicxml.py         # MODIFIED: Use new pipeline
```

---

## 5. DEPENDENCIES TO ADD

```bash
# Primary OMR engine (recommended)
poetry add homr                # Polyphonic OMR with transformer model

# Alternative OMR engine
poetry add oemer               # End-to-end OMR (UNet + SVM)

# Already installed (keep)
# PyMuPDF, music21, opencv-python, pytesseract, pdf2image, Pillow

# Audiveris: Install externally
# Download from https://github.com/Audiveris/audiveris/releases
# Requires Java 21+ runtime
```

---

## 6. IMPLEMENTATION PRIORITY & TIMELINE

| Phase | Description | Effort | Priority |
|-------|-------------|--------|----------|
| **1.1** | Install homr + create engine interface | 2-3 hours | 🔴 Critical |
| **1.2** | Image preprocessing pipeline | 2-3 hours | 🔴 Critical |
| **2.1** | Score analyzer (music21-based) | 3-4 hours | 🔴 Critical |
| **2.2** | Voice/instrument detector | 2-3 hours | 🟡 High |
| **4.1** | MusicXML validator | 3-4 hours | 🔴 Critical |
| **4.2** | Final MusicXML exporter | 2-3 hours | 🔴 Critical |
| **3.1** | Enhanced lyrics extraction | 2-3 hours | 🟡 High |
| **3.2** | Lyrics-note alignment | 3-4 hours | 🟡 High |
| **5.1** | Streamlit UI for OMR | 4-5 hours | 🟢 Medium |

**Recommended start order:** 1.1 → 1.2 → 4.1 → 2.1 → 4.2 → 2.2 → 3.1 → 3.2 → 5.1

---

## 7. EXPECTED RESULTS FOR `Panis.pdf`

After full implementation, processing `Panis.pdf` should produce:

```
Input: data/uploads/1/Panis.pdf (4 pages, Panis Angelicus by Cesar Franck)

Expected MusicXML output:
  - Title: "Panis Angelicus"
  - Composer: Cesar Franck (1822-1890)
  - Lyricist: St. Thomas Aquinas
  - Key: A major (3 sharps)
  - Time: 4/4
  - Tempo: Poco lento, dolce
  - Staves: 4 (Voice + Piano RH + Piano LH, or SATB depending on arrangement)
  - Measures: ~60
  - All notes with correct pitches, durations, and rhythms
  - Lyrics aligned to vocal melody with proper syllabic markup
  - Dynamics: dolce, cresc., dim., rall.
  - Ready to open and play in MuseScore 4
```

---

## 8. KEY RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|------|--------|------------|
| homr/oemer accuracy < 90% | Notes wrong | Use Audiveris as fallback; add manual correction UI |
| Complex scores (4+ voices) | Voices merged | Use ScoreAnalyzer to split; train on church music |
| Lyrics misaligned | Wrong syllables on notes | Position-based + sequential alignment; manual review |
| GPU required for speed | Slow on CPU | oemer supports CPU via ONNX; batch processing UI |
| Large PDFs (100+ pages) | Memory/time | Process page-by-page; async with progress |
| Handwritten scores | Very low accuracy | Detect and warn user; suggest typed scores |
