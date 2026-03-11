"""Text classifier — extract and classify text from sheet music PDFs.

Uses PyMuPDF to extract text blocks with their positions, font sizes,
and font names, then classifies each text element into categories:
title, composer, part names, lyrics, tempo, annotations, etc.

This is critical for the "general to specific" approach: we extract
all metadata BEFORE running OMR, so we don't confuse part labels
with lyrics or OCR-garbled text with the actual title.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class TextElement:
    """A single text element extracted from a PDF with position info."""
    text: str = ""
    x: float = 0.0       # absolute x position
    y: float = 0.0       # absolute y position
    x1: float = 0.0      # right edge
    y1: float = 0.0      # bottom edge
    rel_x: float = 0.0   # relative x (0-1)
    rel_y: float = 0.0   # relative y (0-1)
    font_size: float = 0.0
    font_name: str = ""
    page: int = 0
    category: str = ""   # classified category


@dataclass
class ClassifiedText:
    """All text from a PDF, classified by category."""
    title: str = ""
    subtitle: str = ""
    composer: str = ""
    arranger: str = ""
    lyricist: str = ""
    parish: str = ""           # parish/church name
    location: str = ""         # city
    date_info: str = ""        # liturgical date
    
    part_names: List[Dict] = field(default_factory=list)
    # Each: {"name": "S", "y": 56.3, "rel_y": 0.07}
    
    lyrics_lines: List[Dict] = field(default_factory=list)
    # Each: {"text": "...", "x": ..., "y": ..., "page": 0}
    
    tempo_markings: List[Dict] = field(default_factory=list)
    # Each: {"text": "= 100", "y": ..., "section": "Wstęp"}
    
    section_labels: List[Dict] = field(default_factory=list)
    # Each: {"text": "Wstęp", "y": ..., "page": 0}
    
    measure_numbers: List[Dict] = field(default_factory=list)
    
    all_elements: List[TextElement] = field(default_factory=list)
    
    # Derived
    lyrics_syllables: List[str] = field(default_factory=list)
    pages: int = 0


# Music notation fonts (SMuFL) — their text is glyph data, not readable
MUSIC_FONTS = {
    "leland", "lelandtext", "bravura", "bravuratext",
    "petaluma", "petalumatext", "musejazz", "musejazztext",
    "gonville", "emmentaler", "finale", "sibelius",
    "opus", "maestro", "petrucci", "sebastian",
}

# Common part name labels in church music
PART_LABELS = {
    "s", "a", "t", "b",
    "s.", "a.", "t.", "b.",
    "sop.", "alt.", "ten.", "bas.",
    "soprano", "alto", "tenor", "bass",
    "sopran", "alt", "tenor", "bas",
    "org.", "org", "organo",
    "ch.", "choir", "chór",
    "fl.", "ob.", "vl.", "vc.",
}


class TextClassifier:
    """Extract and classify text from sheet music PDFs."""

    def __init__(self):
        self.page_width = 0.0
        self.page_height = 0.0

    def classify(self, pdf_path: str) -> ClassifiedText:
        """Extract and classify all text from a PDF.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            ClassifiedText with all elements categorized
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return ClassifiedText()

        result = ClassifiedText()

        try:
            doc = fitz.open(str(pdf_path))
            result.pages = doc.page_count

            for page_num in range(doc.page_count):
                page = doc[page_num]
                self.page_width = page.rect.width
                self.page_height = page.rect.height

                elements = self._extract_elements(page, page_num)
                result.all_elements.extend(elements)

            doc.close()
        except Exception as e:
            logger.error(f"Error reading PDF {pdf_path}: {e}")
            return result

        # Classify each element
        self._classify_elements(result)

        # Derive syllables from lyrics lines
        self._derive_syllables(result)

        logger.info(
            f"TextClassifier: title='{result.title}', "
            f"{len(result.part_names)} parts, "
            f"{len(result.lyrics_lines)} lyrics lines, "
            f"{len(result.lyrics_syllables)} syllables"
        )
        return result

    def _extract_elements(self, page, page_num: int) -> List[TextElement]:
        """Extract all text elements with positions from a PDF page."""
        elements = []
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in blocks["blocks"]:
            if block["type"] != 0:  # skip image blocks
                continue

            for line in block["lines"]:
                spans = line["spans"]
                if not spans:
                    continue

                lx0, ly0, lx1, ly1 = line["bbox"]
                text = "".join(span["text"] for span in spans).strip()
                if not text:
                    continue

                font_size = spans[0]["size"]
                font_name = spans[0]["font"]

                # Skip music notation fonts (SMuFL glyphs)
                if font_name.lower().rstrip("0123456789") in MUSIC_FONTS:
                    continue

                elem = TextElement(
                    text=text,
                    x=lx0,
                    y=ly0,
                    x1=lx1,
                    y1=ly1,
                    rel_x=lx0 / self.page_width if self.page_width else 0,
                    rel_y=ly0 / self.page_height if self.page_height else 0,
                    font_size=font_size,
                    font_name=font_name,
                    page=page_num,
                )
                elements.append(elem)

        return elements

    def _classify_elements(self, result: ClassifiedText):
        """Classify all extracted text elements into categories."""
        for elem in result.all_elements:
            category = self._classify_single(elem, result)
            elem.category = category

            if category == "title":
                if not result.title:
                    result.title = elem.text
                else:
                    result.subtitle = elem.text
            elif category == "composer":
                result.composer = elem.text
            elif category == "arranger":
                result.arranger = elem.text
            elif category == "parish":
                if not result.parish:
                    result.parish = elem.text
                else:
                    result.location = elem.text
            elif category == "part_name":
                result.part_names.append({
                    "name": elem.text,
                    "y": elem.y,
                    "rel_y": elem.rel_y,
                    "page": elem.page,
                })
            elif category == "lyrics":
                result.lyrics_lines.append({
                    "text": elem.text,
                    "x": elem.x,
                    "y": elem.y,
                    "rel_y": elem.rel_y,
                    "page": elem.page,
                })
            elif category == "tempo":
                result.tempo_markings.append({
                    "text": elem.text,
                    "y": elem.y,
                    "rel_y": elem.rel_y,
                    "page": elem.page,
                })
            elif category == "section_label":
                result.section_labels.append({
                    "text": elem.text,
                    "y": elem.y,
                    "page": elem.page,
                })
            elif category == "measure_number":
                result.measure_numbers.append({
                    "text": elem.text,
                    "y": elem.y,
                    "page": elem.page,
                })
            elif category == "date":
                result.date_info = elem.text

    def _classify_single(self, elem: TextElement, result: ClassifiedText) -> str:
        """Classify a single text element based on position, font, content.

        Classification rules (priority order):
        1. Position-based: header (top 5%), footer (bottom 5%), left margin (<10%)
        2. Font-based: italic = section label, small = annotation
        3. Content-based: digits = measure number, part labels, tempo patterns
        """
        text = elem.text.strip()
        rel_y = elem.rel_y
        rel_x = elem.rel_x
        font = elem.font_name.lower()
        size = elem.font_size

        # --- FOOTER (bottom 5% of page) ---
        if rel_y > 0.92:
            # Bottom-right = arranger/editor
            if rel_x > 0.7:
                return "arranger"
            # Bottom-center = date/liturgical info
            return "date"

        # --- HEADER (top 6% of page) ---
        if rel_y < 0.06:
            # Small font at top
            if size < 10:
                # Left side = parish/location info
                if rel_x < 0.15:
                    return "parish"
                # Centered = title
                if rel_x > 0.15:
                    return "title"
            # Larger font at top-center = also title
            if rel_x > 0.2 and size >= 10:
                return "title"

        # --- LEFT MARGIN (< 10% of width) = part names ---
        if rel_x < 0.12 and 0.06 < rel_y < 0.92:
            text_lower = text.lower().strip(".")
            # Check if it's a known part label
            if text_lower in PART_LABELS or text.lower() in PART_LABELS:
                return "part_name"
            # Single capital letter at left margin = likely part abbrev
            if len(text) <= 4 and text[0].isupper():
                return "part_name"

        # --- MEASURE NUMBERS (standalone digits, small font) ---
        if re.match(r'^\d+$', text) and size < 12:
            return "measure_number"

        # --- TEMPO MARKINGS ---
        # Pattern: "= 100" or "♩ = 80" or metronome-like
        if re.search(r'[=]\s*\d+', text):
            return "tempo"
        # Tempo words
        tempo_words = {"allegro", "andante", "adagio", "moderato", "lento",
                       "vivace", "presto", "largo", "grave", "tempo"}
        if text.lower() in tempo_words:
            return "tempo"

        # --- SECTION LABELS (italic font) ---
        if "italic" in font.lower():
            return "section_label"

        # --- LYRICS (remaining text, between staves, readable font) ---
        if 0.06 < rel_y < 0.92 and rel_x > 0.08 and size > 8:
            # Not at extreme left margin, not a part name
            text_lower = text.lower().strip(".")
            if text_lower not in PART_LABELS:
                return "lyrics"

        # --- UNKNOWN / ANNOTATION ---
        return "annotation"

    def _derive_syllables(self, result: ClassifiedText):
        """Derive ordered syllables from classified lyrics lines.

        Lyrics lines are sorted by page, then y position, then x position
        to reconstruct the correct reading order. Then split into syllables
        based on hyphens and spaces.
        """
        if not result.lyrics_lines:
            return

        # Sort by page, y, x
        sorted_lines = sorted(
            result.lyrics_lines,
            key=lambda l: (l["page"], l["y"], l["x"])
        )

        # Group by approximate y position (same line = within 3px)
        grouped_lines = []
        current_group = [sorted_lines[0]]

        for line in sorted_lines[1:]:
            if (line["page"] == current_group[0]["page"] and
                    abs(line["y"] - current_group[0]["y"]) < 3):
                current_group.append(line)
            else:
                grouped_lines.append(current_group)
                current_group = [line]
        grouped_lines.append(current_group)

        # For each line group, sort by x and concatenate
        all_syllables = []
        for group in grouped_lines:
            group_sorted = sorted(group, key=lambda l: l["x"])
            full_text = " ".join(l["text"] for l in group_sorted)
            
            # Split into syllables, preserving hyphens
            syllables = self._split_into_syllables(full_text)
            all_syllables.extend(syllables)

        result.lyrics_syllables = all_syllables

    def _split_into_syllables(self, text: str) -> List[str]:
        """Split lyrics text into syllables.

        Handles:
        - Space-separated words: "Jawicie się" → ["Jawicie", "się"]
        - Hyphenated syllables: "świa-tła" → ["świa-", "tła"]
        - Mixed: "Trzymając się mocno Sło-wa" → ["Trzymając", "się", "mocno", "Sło-", "wa"]
        """
        syllables = []
        # Split by spaces first
        tokens = text.split()

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            # Check for hyphenated syllables within the token
            if "-" in token and not token.startswith("(") and not token.endswith(")"):
                parts = token.split("-")
                for i, part in enumerate(parts):
                    part = part.strip()
                    if not part:
                        continue
                    if i < len(parts) - 1:
                        # Not the last part — add hyphen to indicate continuation
                        syllables.append(part + "-")
                    else:
                        # Last part — no trailing hyphen unless original had it
                        if token.endswith("-"):
                            syllables.append(part + "-")
                        else:
                            syllables.append(part)
            else:
                syllables.append(token)

        return syllables

    def get_summary(self, result: ClassifiedText) -> str:
        """Return a human-readable summary of classified text."""
        lines = []
        lines.append(f"  Title:    {result.title}")
        if result.subtitle:
            lines.append(f"  Subtitle: {result.subtitle}")
        if result.composer:
            lines.append(f"  Composer: {result.composer}")
        if result.arranger:
            lines.append(f"  Arranger: {result.arranger}")
        if result.parish:
            lines.append(f"  Parish:   {result.parish}")
        if result.location:
            lines.append(f"  Location: {result.location}")
        if result.date_info:
            lines.append(f"  Date:     {result.date_info}")

        part_str = ", ".join(p["name"] for p in result.part_names)
        lines.append(f"  Parts:    [{part_str}]")

        if result.tempo_markings:
            tempo_str = ", ".join(t["text"] for t in result.tempo_markings)
            lines.append(f"  Tempo:    {tempo_str}")

        if result.section_labels:
            sec_str = ", ".join(s["text"] for s in result.section_labels)
            lines.append(f"  Sections: {sec_str}")

        lines.append(f"  Lyrics:   {len(result.lyrics_syllables)} syllables")
        if result.lyrics_syllables:
            preview = " ".join(result.lyrics_syllables[:10])
            if len(result.lyrics_syllables) > 10:
                preview += " ..."
            lines.append(f"            \"{preview}\"")

        return "\n".join(lines)
