"""Music notation converter for converting OCR results to MusicXML.

Creates MusicXML files with lyrics that can be opened in MuseScore.
"""

import logging
import re
from pathlib import Path
from typing import Optional, List

from music21 import (
    converter, metadata, stream, note, meter,
    key, tempo, clef, instrument, expressions
)
from music21.note import Lyric

from .pdf_text_extractor import LyricsData

logger = logging.getLogger(__name__)


class MusicXMLConverter:
    """Converter for music notation to MusicXML format.
    
    Creates MusicXML scores with lyrics attached to notes,
    suitable for import into MuseScore.
    """
    
    def __init__(self, output_dir: str = "data/processed"):
        """Initialize MusicXML converter.
        
        Args:
            output_dir: Directory to store converted files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_from_metadata(self, title: str, composer: str = None, 
                           key_sig: str = None, time_sig: str = None) -> stream.Score:
        """Create a basic MusicXML score from metadata.
        
        Args:
            title: Title of the piece
            composer: Composer name
            key_sig: Key signature (e.g., 'A major', 'D minor')
            time_sig: Time signature (e.g., '4/4', '3/4')
            
        Returns:
            music21 Score object
        """
        score = stream.Score()
        
        # Add metadata
        score.metadata = metadata.Metadata()
        score.metadata.title = title
        if composer:
            score.metadata.composer = composer
        
        # Create a part with voice instrument
        part = stream.Part()
        part.partName = "Voice"
        vocal = instrument.Vocalist()
        part.insert(0, vocal)
        
        # Add clef
        part.insert(0, clef.TrebleClef())
        
        # Add time signature
        if time_sig:
            ts = meter.TimeSignature(time_sig)
        else:
            ts = meter.TimeSignature('4/4')
        part.insert(0, ts)
        
        # Add key signature if provided
        if key_sig:
            try:
                ks = key.Key(key_sig)
                part.insert(0, ks)
            except Exception:
                pass
        
        score.append(part)
        return score

    def create_score_with_lyrics(self, lyrics_data: LyricsData,
                                  time_sig: str = '4/4',
                                  key_sig: str = 'A',
                                  default_pitch: str = 'A4',
                                  note_duration: float = 1.0) -> stream.Score:
        """Create a MusicXML score with lyrics attached to notes.
        
        Each syllable is assigned to a note. Since we only have lyrics
        (not actual pitches from the PDF), placeholder notes are used
        at a default pitch. The user can then edit pitches in MuseScore
        while keeping the lyric alignment.
        
        Args:
            lyrics_data: LyricsData object with extracted lyrics
            time_sig: Time signature string (default: '4/4')
            key_sig: Key signature (default: 'A' for A major - matches Panis Angelicus)
            default_pitch: Default pitch for placeholder notes
            note_duration: Duration of each note in quarter lengths
            
        Returns:
            music21 Score object with lyrics
        """
        # Create score with metadata
        title = lyrics_data.title or "Untitled"
        composer = lyrics_data.composer or ""
        
        score = self.create_from_metadata(
            title=title,
            composer=composer,
            key_sig=key_sig,
            time_sig=time_sig
        )
        
        part = score.parts[0]
        
        # Add tempo marking if available
        if lyrics_data.tempo_marking:
            tempo_text = expressions.TextExpression(lyrics_data.tempo_marking)
            part.insert(0, tempo_text)
        
        # Parse time signature to know beats per measure
        ts = meter.TimeSignature(time_sig)
        beats_per_measure = ts.numerator
        beat_type = ts.denominator
        
        # Calculate how many notes fit per measure
        # note_duration is in quarter-note lengths
        notes_per_measure = int(beats_per_measure * (4.0 / beat_type) / note_duration)
        if notes_per_measure < 1:
            notes_per_measure = 1
        
        # Create notes with lyrics
        syllables = lyrics_data.syllables
        if not syllables:
            logger.warning("No syllables to add to score")
            return score
        
        current_measure = stream.Measure(number=1)
        measure_num = 1
        note_count_in_measure = 0
        
        for i, syllable in enumerate(syllables):
            # Create a note
            n = note.Note(default_pitch)
            n.duration.quarterLength = note_duration
            
            # Determine syllabic type for proper MusicXML lyric rendering
            syllabic = self._get_syllabic_type(syllable, syllables, i)
            
            # Clean the syllable text (remove trailing hyphens for display)
            clean_syllable = syllable.rstrip('-')
            
            # Add lyric to note
            lyric = Lyric()
            lyric.text = clean_syllable
            lyric.number = 1
            lyric.syllabic = syllabic
            n.lyrics.append(lyric)
            
            # Add note to current measure
            current_measure.append(n)
            note_count_in_measure += 1
            
            # Start new measure when full
            if note_count_in_measure >= notes_per_measure:
                part.append(current_measure)
                measure_num += 1
                current_measure = stream.Measure(number=measure_num)
                note_count_in_measure = 0
        
        # Append the last measure if it has notes
        if note_count_in_measure > 0:
            # Pad with rests if needed
            remaining = notes_per_measure - note_count_in_measure
            for _ in range(remaining):
                r = note.Rest()
                r.duration.quarterLength = note_duration
                current_measure.append(r)
            part.append(current_measure)
        
        logger.info(
            f"Created score '{title}' with {len(syllables)} syllables "
            f"across {measure_num} measures"
        )
        return score

    def _get_syllabic_type(self, syllable: str, all_syllables: List[str], index: int) -> str:
        """Determine the syllabic type for MusicXML lyric rendering.
        
        Args:
            syllable: Current syllable
            all_syllables: All syllables list
            index: Current index
            
        Returns:
            Syllabic type: 'single', 'begin', 'middle', or 'end'
        """
        ends_with_hyphen = syllable.endswith('-')
        
        # Check if previous syllable had a hyphen (meaning this continues a word)
        prev_had_hyphen = False
        if index > 0:
            prev_had_hyphen = all_syllables[index - 1].endswith('-')
        
        if prev_had_hyphen and ends_with_hyphen:
            return 'middle'
        elif prev_had_hyphen and not ends_with_hyphen:
            return 'end'
        elif not prev_had_hyphen and ends_with_hyphen:
            return 'begin'
        else:
            return 'single'

    def save_as_musicxml(self, score: stream.Score, output_path: str) -> bool:
        """Save a music21 Score as MusicXML.
        
        Args:
            score: music21 Score object
            output_path: Path to save the MusicXML file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            output_path = str(output_path)
            # Ensure .musicxml extension for MuseScore compatibility
            if not output_path.endswith(('.xml', '.musicxml')):
                output_path += '.musicxml'
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            score.write('musicxml', fp=output_path)
            logger.info(f"MusicXML saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving MusicXML to {output_path}: {str(e)}")
            return False
    
    def convert_to_musescore(self, musicxml_path: str, output_path: str) -> bool:
        """Convert MusicXML to MuseScore format.
        
        Note: This requires MuseScore to be installed and available in PATH.
        
        Args:
            musicxml_path: Path to the MusicXML file
            output_path: Path to save the MuseScore file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import subprocess
            
            # Try common MuseScore executable names
            mscore_names = ['musescore', 'MuseScore4', 'MuseScore3', 'mscore']
            
            for mscore in mscore_names:
                try:
                    result = subprocess.run(
                        [mscore, musicxml_path, '-o', output_path],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"MuseScore file saved to {output_path}")
                        return True
                except FileNotFoundError:
                    continue
            
            logger.warning("MuseScore not found in PATH. Skipping conversion.")
            return False
        except Exception as e:
            logger.error(f"Error converting to MuseScore: {str(e)}")
            return False
