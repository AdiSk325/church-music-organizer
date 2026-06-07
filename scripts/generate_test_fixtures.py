#!/usr/bin/env python3
"""Generate MusicXML test fixtures and render them to PDF via verovio + cairosvg.

Usage:
    python3 scripts/generate_test_fixtures.py

Outputs:
    tests/functional/fixtures/musicxml/*.xml  — MusicXML source files
    tests/functional/fixtures/scans/*.pdf     — Rendered PDFs (one per piece)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import music21
from music21 import chord, clef, corpus, duration, instrument, key, meter, note, stream, tempo
import verovio
import cairosvg

MUSICXML_DIR = PROJECT_ROOT / "tests/functional/fixtures/musicxml"
PDF_DIR = PROJECT_ROOT / "tests/functional/fixtures/scans"

MUSICXML_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_note(pitch: str, dur: float = 1.0) -> note.Note:
    n = note.Note(pitch)
    n.duration = duration.Duration(dur)
    return n


def make_rest(dur: float = 1.0) -> note.Rest:
    r = note.Rest()
    r.duration = duration.Duration(dur)
    return r


def add_time_signature(part: stream.Part, ts: str) -> None:
    part.append(meter.TimeSignature(ts))


def add_key_signature(part: stream.Part, ks: str) -> None:
    part.append(key.Key(ks))


def add_tempo(part: stream.Part, bpm: int) -> None:
    part.append(tempo.MetronomeMark(number=bpm))


# ---------------------------------------------------------------------------
# Piece 1: Kyrie eleison — C major, 4/4, 8 bars
# Simple homophonic SATB prayer for mercy
# ---------------------------------------------------------------------------

def build_kyrie() -> stream.Score:
    sc = stream.Score()
    sc.metadata = music21.metadata.Metadata()
    sc.metadata.title = "Kyrie eleison"
    sc.metadata.composer = "Trad. / Test Fixture"

    # Define SATB voices with pitches per measure (8 measures)
    satb_data = {
        "Soprano": [
            ["E5", "D5", "C5", "E5"],  # m1
            ["F5", "E5", "D5", "C5"],  # m2
            ["E5", "G5", "F5", "E5"],  # m3
            ["D5", "C5", "B4", "C5"],  # m4
            ["E5", "D5", "C5", "E5"],  # m5
            ["F5", "E5", "D5", "C5"],  # m6
            ["G5", "F5", "E5", "D5"],  # m7
            ["C5", "C5", "C5", "C5"],  # m8 (last = whole)
        ],
        "Alto": [
            ["C5", "B4", "G4", "G4"],
            ["A4", "G4", "F4", "E4"],
            ["C5", "E5", "D5", "C5"],
            ["B4", "A4", "G4", "A4"],
            ["C5", "B4", "G4", "G4"],
            ["A4", "G4", "F4", "E4"],
            ["E5", "D5", "C5", "B4"],
            ["G4", "G4", "G4", "G4"],
        ],
        "Tenor": [
            ["G4", "G4", "E4", "C4"],
            ["F4", "C4", "B3", "C4"],
            ["G4", "C5", "A4", "G4"],
            ["G4", "F4", "D4", "F4"],
            ["G4", "G4", "E4", "C4"],
            ["F4", "C4", "B3", "C4"],
            ["C5", "A4", "G4", "G4"],
            ["E4", "E4", "E4", "E4"],
        ],
        "Bass": [
            ["C3", "G3", "C4", "C4"],
            ["F3", "C3", "G3", "A3"],
            ["C4", "C4", "D4", "C4"],
            ["G3", "F3", "G3", "F3"],
            ["C3", "G3", "C4", "C4"],
            ["F3", "C3", "G3", "A3"],
            ["C4", "F3", "C4", "G3"],
            ["C3", "C3", "C3", "C3"],
        ],
    }

    clef_map = {
        "Soprano": clef.TrebleClef(),
        "Alto": clef.TrebleClef(),
        "Tenor": clef.Treble8vbClef(),
        "Bass": clef.BassClef(),
    }
    instr_map = {
        "Soprano": instrument.Soprano(),
        "Alto": instrument.Alto(),
        "Tenor": instrument.Tenor(),
        "Bass": instrument.Bass(),
    }

    for voice_name, measures in satb_data.items():
        part = stream.Part()
        part.partName = voice_name
        part.append(instr_map[voice_name])
        part.append(clef_map[voice_name])
        add_key_signature(part, "C")
        add_time_signature(part, "4/4")
        if voice_name == "Soprano":
            add_tempo(part, 80)

        for m_idx, pitches in enumerate(measures):
            m = stream.Measure(number=m_idx + 1)
            if m_idx == 7:
                # Final whole-note chord feel — use 4 quarter notes on same pitch
                for p in pitches:
                    m.append(make_note(p, 1.0))
            else:
                for p in pitches:
                    m.append(make_note(p, 1.0))
            part.append(m)

        sc.insert(0, part)

    return sc


# ---------------------------------------------------------------------------
# Piece 2: Gloria — G major, 3/4, 8 bars
# Joyful triple-meter Gloria with flowing alto/tenor lines
# ---------------------------------------------------------------------------

def build_gloria() -> stream.Score:
    sc = stream.Score()
    sc.metadata = music21.metadata.Metadata()
    sc.metadata.title = "Gloria in excelsis"
    sc.metadata.composer = "Trad. / Test Fixture"

    satb_data = {
        "Soprano": [
            ["D5", "E5", "F5"],  # m1
            ["G5", "F5", "E5"],  # m2
            ["D5", "D5", "E5"],  # m3
            ["D5", "C5", "B4"],  # m4
            ["D5", "E5", "F5"],  # m5
            ["G5", "A5", "G5"],  # m6
            ["F5", "E5", "D5"],  # m7
            ["G5", "G5", "G5"],  # m8
        ],
        "Alto": [
            ["B4", "C5", "D5"],
            ["D5", "C5", "B4"],
            ["A4", "B4", "C5"],
            ["B4", "A4", "G4"],
            ["B4", "C5", "D5"],
            ["D5", "E5", "D5"],
            ["C5", "B4", "A4"],
            ["B4", "B4", "B4"],
        ],
        "Tenor": [
            ["G4", "G4", "A4"],
            ["B4", "A4", "G4"],
            ["F4", "G4", "A4"],
            ["G4", "F4", "D4"],
            ["G4", "G4", "A4"],
            ["B4", "C5", "B4"],
            ["A4", "G4", "F4"],
            ["G4", "G4", "G4"],
        ],
        "Bass": [
            ["G3", "C4", "D4"],
            ["G3", "G3", "G3"],
            ["D3", "G3", "A3"],
            ["G3", "D3", "G3"],
            ["G3", "C4", "D4"],
            ["G3", "A3", "G3"],
            ["D4", "C4", "D4"],
            ["G2", "G3", "G3"],
        ],
    }

    clef_map = {
        "Soprano": clef.TrebleClef(),
        "Alto": clef.TrebleClef(),
        "Tenor": clef.Treble8vbClef(),
        "Bass": clef.BassClef(),
    }
    instr_map = {
        "Soprano": instrument.Soprano(),
        "Alto": instrument.Alto(),
        "Tenor": instrument.Tenor(),
        "Bass": instrument.Bass(),
    }

    for voice_name, measures in satb_data.items():
        part = stream.Part()
        part.partName = voice_name
        part.append(instr_map[voice_name])
        part.append(clef_map[voice_name])
        add_key_signature(part, "G")
        add_time_signature(part, "3/4")
        if voice_name == "Soprano":
            add_tempo(part, 100)

        for m_idx, pitches in enumerate(measures):
            m = stream.Measure(number=m_idx + 1)
            for p in pitches:
                m.append(make_note(p, 1.0))
            part.append(m)

        sc.insert(0, part)

    return sc


# ---------------------------------------------------------------------------
# Piece 3: Sanctus — F major, 4/4, 8 bars
# Majestic Sanctus with dotted-rhythm feel (simplified to quarters)
# ---------------------------------------------------------------------------

def build_sanctus() -> stream.Score:
    sc = stream.Score()
    sc.metadata = music21.metadata.Metadata()
    sc.metadata.title = "Sanctus"
    sc.metadata.composer = "Trad. / Test Fixture"

    satb_data = {
        "Soprano": [
            ["F5", "E5", "F5", "G5"],
            ["A5", "G5", "F5", "E5"],
            ["F5", "F5", "G5", "A5"],
            ["B-5", "A5", "G5", "F5"],
            ["C5", "D5", "E5", "F5"],
            ["G5", "F5", "E5", "D5"],
            ["C5", "D5", "E5", "F5"],
            ["F5", "F5", "F5", "F5"],
        ],
        "Alto": [
            ["C5", "C5", "A4", "C5"],
            ["F5", "E5", "D5", "C5"],
            ["D5", "C5", "E5", "F5"],
            ["G5", "F5", "E5", "D5"],
            ["A4", "B-4", "C5", "D5"],
            ["E5", "D5", "C5", "B-4"],
            ["A4", "B-4", "C5", "D5"],
            ["C5", "C5", "C5", "C5"],
        ],
        "Tenor": [
            ["A4", "G4", "F4", "E4"],
            ["F4", "C5", "A4", "G4"],
            ["B-4", "A4", "C5", "C5"],
            ["D5", "C5", "B-4", "A4"],
            ["F4", "F4", "G4", "A4"],
            ["C5", "A4", "G4", "G4"],
            ["F4", "G4", "G4", "A4"],
            ["A4", "A4", "A4", "A4"],
        ],
        "Bass": [
            ["F3", "C4", "F4", "C4"],
            ["F4", "C4", "D4", "C4"],
            ["B-3", "F4", "C4", "F4"],
            ["B-3", "F4", "C4", "D4"],
            ["F3", "B-3", "C4", "D4"],
            ["C4", "F4", "C4", "G3"],
            ["F3", "B-3", "C4", "F3"],
            ["F3", "F3", "F3", "F3"],
        ],
    }

    clef_map = {
        "Soprano": clef.TrebleClef(),
        "Alto": clef.TrebleClef(),
        "Tenor": clef.Treble8vbClef(),
        "Bass": clef.BassClef(),
    }
    instr_map = {
        "Soprano": instrument.Soprano(),
        "Alto": instrument.Alto(),
        "Tenor": instrument.Tenor(),
        "Bass": instrument.Bass(),
    }

    for voice_name, measures in satb_data.items():
        part = stream.Part()
        part.partName = voice_name
        part.append(instr_map[voice_name])
        part.append(clef_map[voice_name])
        add_key_signature(part, "F")
        add_time_signature(part, "4/4")
        if voice_name == "Soprano":
            add_tempo(part, 72)

        for m_idx, pitches in enumerate(measures):
            m = stream.Measure(number=m_idx + 1)
            for p in pitches:
                m.append(make_note(p, 1.0))
            part.append(m)

        sc.insert(0, part)

    return sc


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def score_to_musicxml(sc: stream.Score, out_path: Path) -> None:
    sc.write("musicxml", fp=str(out_path))
    print(f"  MusicXML → {out_path}")


def musicxml_to_pdf(xml_path: Path, pdf_path: Path) -> None:
    """Convert MusicXML → SVG via verovio → PDF via cairosvg."""
    tk = verovio.toolkit()
    tk.setOptions({
        "pageWidth": 2400,
        "pageHeight": 3200,
        "pageMarginTop": 150,
        "pageMarginBottom": 150,
        "pageMarginLeft": 150,
        "pageMarginRight": 150,
        "scale": 40,
        "adjustPageHeight": True,
        "header": "encoded",
        "footer": "auto",
    })

    with open(xml_path, "r", encoding="utf-8") as f:
        xml_content = f.read()

    loaded = tk.loadData(xml_content)
    if not loaded:
        raise RuntimeError(f"verovio failed to load {xml_path}")

    page_count = tk.getPageCount()
    print(f"  verovio: {page_count} page(s) for {xml_path.name}")

    # Collect all pages as SVG bytes, convert each to PDF bytes, merge
    svg_pages = []
    for page in range(1, page_count + 1):
        svg_str = tk.renderToSVG(page)
        svg_pages.append(svg_str.encode("utf-8"))

    if len(svg_pages) == 1:
        pdf_bytes = cairosvg.svg2pdf(bytestring=svg_pages[0])
    else:
        # Multi-page: convert each SVG to PDF and concatenate with pypdf if available,
        # otherwise just use the first page (adequate for test fixtures)
        try:
            import pypdf
            from io import BytesIO

            writer = pypdf.PdfWriter()
            for svg_bytes in svg_pages:
                page_pdf = cairosvg.svg2pdf(bytestring=svg_bytes)
                reader = pypdf.PdfReader(BytesIO(page_pdf))
                for p in reader.pages:
                    writer.add_page(p)
            buf = BytesIO()
            writer.write(buf)
            pdf_bytes = buf.getvalue()
        except ImportError:
            # pypdf unavailable — concatenate all pages as a single merged SVG isn't possible;
            # use cairosvg's built-in multi-page support via write_to
            pdf_bytes = cairosvg.svg2pdf(bytestring=svg_pages[0])
            print("  Warning: pypdf not installed, only first page included")

    pdf_path.write_bytes(pdf_bytes)
    print(f"  PDF     → {pdf_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    pieces = [
        ("kyrie_eleison", build_kyrie),
        ("gloria_in_excelsis", build_gloria),
        ("sanctus", build_sanctus),
    ]

    print(f"music21 {music21.__version__}")
    print(f"verovio {verovio.toolkit().getVersion()}")
    print(f"cairosvg {cairosvg.__version__}")
    print()

    for slug, builder in pieces:
        print(f"=== {slug} ===")
        sc = builder()
        xml_path = MUSICXML_DIR / f"{slug}.xml"
        pdf_path = PDF_DIR / f"{slug}.pdf"
        score_to_musicxml(sc, xml_path)
        musicxml_to_pdf(xml_path, pdf_path)
        print()

    print("Done.")
    print(f"MusicXML: {MUSICXML_DIR}")
    print(f"PDFs:     {PDF_DIR}")


if __name__ == "__main__":
    main()
