"""Lyrics aligner — align extracted lyrics text to OMR-recognized notes.

Merges lyrics extracted by PDFTextExtractor (from the PDF text layer)
with notes detected by the OMR engine, producing a music21 Score
with lyrics properly attached to notes.
"""

import logging
from pathlib import Path
from typing import List, Optional

from music21 import converter, stream, note, chord

from src.ocr.pdf_text_extractor import PDFTextExtractor, LyricsData

logger = logging.getLogger(__name__)


class LyricsAligner:
    """Align extracted lyrics to OMR-detected notes in a score."""

    def __init__(self):
        self.extractor = PDFTextExtractor()

    def align(
        self,
        musicxml_path: str,
        pdf_path: str,
        vocal_part_indices: Optional[List[int]] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Align lyrics from PDF text layer onto MusicXML notes.

        Args:
            musicxml_path: Path to the OMR-produced MusicXML file
            pdf_path: Path to the original PDF (for lyrics extraction)
            vocal_part_indices: Indices of parts to attach lyrics to.
                If None, uses first part (index 0).
            output_path: Where to save the result. If None, overwrites input.

        Returns:
            Path to the output MusicXML file.
        """
        # 1) Extract lyrics from PDF text layer
        lyrics_data = self.extractor.extract_from_pdf(pdf_path)
        if not lyrics_data.syllables:
            logger.warning("No lyrics extracted from PDF, skipping alignment")
            return musicxml_path

        logger.info(f"Extracted {len(lyrics_data.syllables)} syllables from PDF")

        # 2) Parse the OMR score
        score = converter.parse(musicxml_path)

        # 3) Determine which parts get lyrics
        if vocal_part_indices is None:
            # Default: first part only
            vocal_part_indices = [0]

        # 4) Attach lyrics to each vocal part
        for part_idx in vocal_part_indices:
            if part_idx >= len(score.parts):
                logger.warning(f"Part index {part_idx} out of range, skipping")
                continue
            part = score.parts[part_idx]
            self._attach_lyrics_to_part(part, lyrics_data.syllables)

        # 5) Save result
        save_path = output_path or musicxml_path
        score.write('musicxml', fp=save_path)
        logger.info(f"Saved score with lyrics to {save_path}")
        return save_path

    def _attach_lyrics_to_part(
        self,
        part: stream.Part,
        syllables: List[str],
    ):
        """Attach syllables to notes in a part.

        Each syllable is attached to successive notes (skipping rests).
        Syllabic type (begin/middle/end/single) is inferred from hyphens.
        """
        from music21 import note as m21note

        notes_iter = (
            n for n in part.flatten().notes
            if isinstance(n, m21note.Note)
        )

        syl_idx = 0
        for n in notes_iter:
            if syl_idx >= len(syllables):
                break

            raw = syllables[syl_idx]
            syl_idx += 1

            # Determine syllabic type
            text, syllabic = self._parse_syllable(
                raw,
                prev=syllables[syl_idx - 2] if syl_idx >= 2 else None,
                next_syl=syllables[syl_idx] if syl_idx < len(syllables) else None,
            )

            from music21 import note as m21note2
            lyric = m21note2.Lyric()
            lyric.text = text
            lyric.syllabic = syllabic
            lyric.number = 1
            n.lyrics.append(lyric)

        attached = min(syl_idx, len(syllables))
        logger.info(
            f"Attached {attached}/{len(syllables)} syllables "
            f"to part '{part.partName or part.id}'"
        )

    def _parse_syllable(
        self,
        raw: str,
        prev: Optional[str] = None,
        next_syl: Optional[str] = None,
    ) -> tuple:
        """Determine text and syllabic type for a syllable.

        Convention: trailing hyphen means continuation follows,
        leading hyphen means continuation from previous.

        Returns:
            (clean_text, syllabic_type) where syllabic is one of
            'single', 'begin', 'middle', 'end'
        """
        has_trailing = raw.endswith('-')
        has_leading = raw.startswith('-')

        text = raw.strip('-').strip()
        if not text:
            text = " "

        if has_leading and has_trailing:
            return text, 'middle'
        elif has_leading:
            return text, 'end'
        elif has_trailing:
            return text, 'begin'
        else:
            # Check if next syllable starts with hyphen (continuation)
            if next_syl and next_syl.startswith('-'):
                return text, 'begin'
            return text, 'single'

    def align_from_lyrics_data(
        self,
        musicxml_path: str,
        lyrics_data: LyricsData,
        vocal_part_indices: Optional[List[int]] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Align pre-extracted lyrics data onto a MusicXML score.

        Same as align() but accepts LyricsData directly instead of
        extracting from PDF.
        """
        score = converter.parse(musicxml_path)

        if not lyrics_data.syllables:
            logger.warning("No syllables provided, skipping alignment")
            return musicxml_path

        if vocal_part_indices is None:
            vocal_part_indices = [0]

        for part_idx in vocal_part_indices:
            if part_idx >= len(score.parts):
                continue
            part = score.parts[part_idx]
            self._attach_lyrics_to_part(part, lyrics_data.syllables)

        save_path = output_path or musicxml_path
        score.write('musicxml', fp=save_path)
        logger.info(f"Saved score with lyrics to {save_path}")
        return save_path
