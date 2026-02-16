"""PDF text extractor using PyMuPDF (fitz) for text-based PDFs.

This module extracts lyrics and metadata from sheet music PDFs
without requiring Tesseract OCR, using PyMuPDF's built-in text extraction.
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class LyricsData:
    """Structured lyrics data extracted from a PDF."""
    title: str = ""
    composer: str = ""
    lyricist: str = ""
    tempo_marking: str = ""
    syllables: List[str] = field(default_factory=list)
    raw_text: str = ""
    pages: int = 0


class PDFTextExtractor:
    """Extract text and lyrics from sheet music PDFs using PyMuPDF."""

    # Common tempo/expression markings to detect
    EXPRESSION_MARKS = {
        'dolce', 'cresc.', 'cresc', 'dim.', 'dim', 'rall.', 'rall',
        'rit.', 'rit', 'a tempo', 'poco', 'lento', 'allegro',
        'andante', 'adagio', 'moderato', 'forte', 'piano',
        'crescendo', 'diminuendo', 'rallentando', 'ritardando',
        'Poco lento', 'poco lento'
    }

    # Patterns that are measure numbers or page numbers (digits only)
    NUMERIC_PATTERN = re.compile(r'^\d+$')

    # Hyphenated syllable pattern (e.g., "pa-", "-nis", "ge- li- cus")
    SYLLABLE_PATTERN = re.compile(r'^[a-zA-ZàáâãäåæçèéêëìíîïðñòóôõöùúûüýþÿÀ-ÖØ-öø-ÿ]+[-]?$')

    def __init__(self, output_dir: str = "data/processed"):
        """Initialize the PDF text extractor.

        Args:
            output_dir: Directory to store extracted data
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_from_pdf(self, pdf_path: str) -> LyricsData:
        """Extract lyrics and metadata from a PDF file.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            LyricsData object with extracted information
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return LyricsData()

        try:
            doc = fitz.open(str(pdf_path))
            lyrics_data = LyricsData(pages=doc.page_count)

            all_text_lines = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                text = page.get_text()
                all_text_lines.extend(text.strip().split('\n'))

            lyrics_data.raw_text = '\n'.join(all_text_lines)

            # Extract metadata from first page
            self._extract_metadata(all_text_lines, lyrics_data)

            # Extract syllables from all pages
            self._extract_syllables(all_text_lines, lyrics_data)

            doc.close()

            logger.info(
                f"Extracted from '{pdf_path.name}': "
                f"title='{lyrics_data.title}', "
                f"composer='{lyrics_data.composer}', "
                f"{len(lyrics_data.syllables)} syllables"
            )
            return lyrics_data

        except Exception as e:
            logger.error(f"Error extracting text from {pdf_path}: {e}")
            return LyricsData()

    def _extract_metadata(self, lines: List[str], data: LyricsData):
        """Extract title, composer, and other metadata from text lines.

        Args:
            lines: List of text lines from the PDF
            data: LyricsData to populate
        """
        # Skip empty lines and page numbers at the start
        content_lines = []
        for line in lines[:15]:  # Look in first 15 lines
            stripped = line.strip()
            if stripped and not self.NUMERIC_PATTERN.match(stripped):
                content_lines.append(stripped)

        if not content_lines:
            return

        # First non-numeric content line is typically the title
        data.title = content_lines[0] if content_lines else ""

        # Look for composer/lyricist info - usually contains dates in parentheses
        for line in content_lines[1:]:
            # Lines with dates like (1822-1890) are likely composer/lyricist
            if re.search(r'\(\d{4}', line):
                if not data.lyricist:
                    data.lyricist = line
                elif not data.composer:
                    data.composer = line
            elif any(mark.lower() in line.lower() for mark in ['FWV', 'BWV', 'Op.', 'K.', 'D.']):
                # Catalog numbers - skip
                continue
            elif not data.composer and not re.search(r'\(\d{4}', line):
                # Could be composer name without dates
                if len(content_lines) > 2:
                    pass  # Will be set from date-containing lines

        # If we found date lines, use the names before the dates
        for i, line in enumerate(content_lines[1:8], 1):
            if re.search(r'\(\d{4}', line):
                # The previous non-date line is the person's name
                name_line = content_lines[i - 1] if i > 0 else ""
                date_match = re.search(r'\((\d{4})-(\d{4})\)', line)
                date_info = f" {line}" if date_match else ""

                if not data.lyricist or data.lyricist == line:
                    data.lyricist = name_line + date_info
                elif not data.composer or data.composer == line:
                    data.composer = name_line + date_info

        # Look for tempo marking
        for line in content_lines:
            lower = line.lower()
            for mark in self.EXPRESSION_MARKS:
                if mark.lower() in lower:
                    data.tempo_marking = line
                    break
            if data.tempo_marking:
                break

    def _extract_syllables(self, lines: List[str], data: LyricsData):
        """Extract lyric syllables from text lines.

        Filters out measure numbers, expression markings, page numbers,
        and other non-lyric content.

        Args:
            lines: All text lines from the PDF
            data: LyricsData to populate with syllables
        """
        syllables = []

        for line in lines:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # Skip page numbers (standalone digits)
            if self.NUMERIC_PATTERN.match(stripped):
                continue

            # Skip if it's the title, composer, or lyricist info
            if stripped == data.title:
                continue
            if data.composer and stripped in data.composer:
                continue
            if data.lyricist and stripped in data.lyricist:
                continue

            # Skip catalog numbers (FWV, BWV, etc.)
            if re.match(r'^[A-Z]{2,4}\s+\d+', stripped):
                continue

            # Skip date lines
            if re.match(r'^\(\d{4}', stripped):
                continue

            # Skip expression/tempo markings
            stripped_lower = stripped.lower()
            if stripped_lower in {m.lower() for m in self.EXPRESSION_MARKS}:
                continue

            # Process the line for syllables
            # Split by whitespace
            tokens = stripped.split()

            for token in tokens:
                # Remove underscores (tied notes in lyrics)
                token = token.replace('_', '').strip()

                if not token:
                    continue

                # Skip standalone expression markings within a line
                if token.lower() in {m.lower() for m in self.EXPRESSION_MARKS}:
                    continue

                # Skip pure numbers
                if self.NUMERIC_PATTERN.match(token):
                    continue

                # Accept tokens that look like lyric syllables
                # They contain letters and may end with '-'
                clean = token.strip('-').strip()
                if clean and re.match(r'^[a-zA-ZàáâãäåæçèéêëìíîïðñòóôõöùúûüýþÿÀ-ÖØ-öø-ÿ:;,.!?]+$', clean):
                    syllables.append(token)

        data.syllables = syllables

    def get_lyrics_text(self, data: LyricsData) -> str:
        """Reconstruct readable lyrics from syllables.

        Joins hyphenated syllables into words.

        Args:
            data: LyricsData with extracted syllables

        Returns:
            Reconstructed lyrics as readable text
        """
        if not data.syllables:
            return ""

        words = []
        current_word = ""

        for syllable in data.syllables:
            if syllable.endswith('-'):
                # Syllable continues
                current_word += syllable[:-1]
            elif current_word:
                # End of hyphenated word
                current_word += syllable
                words.append(current_word)
                current_word = ""
            else:
                # Standalone word
                words.append(syllable)

        # Don't forget the last partial word
        if current_word:
            words.append(current_word)

        return ' '.join(words)

    def save_lyrics(self, data: LyricsData, output_path: Optional[str] = None) -> str:
        """Save extracted lyrics to a text file.

        Args:
            data: LyricsData with extracted information
            output_path: Optional output file path

        Returns:
            Path to the saved file
        """
        if output_path is None:
            safe_title = re.sub(r'[^\w\s-]', '', data.title).strip().replace(' ', '_')
            output_path = str(self.output_dir / f"{safe_title}_lyrics.txt")

        lyrics_text = self.get_lyrics_text(data)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Title: {data.title}\n")
            f.write(f"Composer: {data.composer}\n")
            f.write(f"Lyricist: {data.lyricist}\n")
            if data.tempo_marking:
                f.write(f"Tempo: {data.tempo_marking}\n")
            f.write(f"\n--- Lyrics ---\n\n")
            f.write(lyrics_text + "\n")
            f.write(f"\n--- Syllables ({len(data.syllables)}) ---\n\n")
            f.write(' | '.join(data.syllables) + "\n")

        logger.info(f"Lyrics saved to {output_path}")
        return output_path
