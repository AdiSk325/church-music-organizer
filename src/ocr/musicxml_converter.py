"""Music notation converter for converting OCR results to MusicXML."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional
from music21 import converter, metadata, stream, note as m21note, duration as m21duration

logger = logging.getLogger(__name__)


class MusicXMLConverter:
    """Converter for music notation to MusicXML format."""
    
    def __init__(self, output_dir: str = "data/processed"):
        """Initialize MusicXML converter.
        
        Args:
            output_dir: Directory to store converted files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_from_metadata(self, title: str, composer: str = None, 
                           key: str = None, time_sig: str = None) -> stream.Score:
        """Create a basic MusicXML score from metadata.
        
        Args:
            title: Title of the piece
            composer: Composer name
            key: Key signature
            time_sig: Time signature
            
        Returns:
            music21 Score object
        """
        score = stream.Score()
        
        # Add metadata
        score.metadata = metadata.Metadata()
        score.metadata.title = title
        if composer:
            score.metadata.composer = composer
        
        # Create a part
        part = stream.Part()
        score.append(part)
        
        return score
    
    def save_as_musicxml(self, score: stream.Score, output_path: str) -> bool:
        """Save a music21 Score as MusicXML.
        
        Args:
            score: music21 Score object
            output_path: Path to save the MusicXML file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            score.write('musicxml', fp=output_path)
            logger.info(f"MusicXML saved to {output_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving MusicXML to {output_path}: {str(e)}")
            return False
    
    def score_graph_to_score(self, score_graph) -> stream.Score:
        """Convert a :class:`~src.omr.score_graph.ScoreGraph` to a music21 Score.

        This bridges the OMR pipeline's Intermediate Representation with the
        existing music21-based export infrastructure.

        Args:
            score_graph: A :class:`~src.omr.score_graph.ScoreGraph` instance.

        Returns:
            A ``music21.stream.Score`` ready for MusicXML export.
        """
        score = stream.Score()

        # Metadata
        score.metadata = metadata.Metadata()
        score.metadata.title = score_graph.title or ""
        if score_graph.composer:
            score.metadata.composer = score_graph.composer

        # One part per unique voice_id
        voice_ids = score_graph.voice_ids()
        parts: Dict[int, stream.Part] = {}
        for vid in voice_ids:
            part = stream.Part()
            parts[vid] = part
            score.append(part)

        # Populate parts from measures
        for measure in score_graph.measures:
            for voice in measure.voices:
                if voice.voice_id not in parts:
                    part = stream.Part()
                    parts[voice.voice_id] = part
                    score.append(part)

                m21_measure = stream.Measure(number=measure.number)

                # Add time signature on the first measure
                if measure.number == 1:
                    from music21 import meter  # noqa: PLC0415
                    try:
                        m21_measure.append(meter.TimeSignature(measure.time_signature))
                    except Exception:  # noqa: BLE001
                        pass

                for n in voice.notes:
                    try:
                        dur = m21duration.Duration(quarterLength=n.duration)
                        if n.is_rest:
                            element = m21note.Rest(duration=dur)
                        else:
                            element = m21note.Note(n.pitch, duration=dur)
                        m21_measure.append(element)
                    except Exception:  # noqa: BLE001
                        pass

                parts[voice.voice_id].append(m21_measure)

        return score

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
            
            # Try to convert using MuseScore command line
            result = subprocess.run(
                ['musescore', musicxml_path, '-o', output_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"MuseScore file saved to {output_path}")
                return True
            else:
                logger.error(f"MuseScore conversion failed: {result.stderr}")
                return False
        except FileNotFoundError:
            logger.warning("MuseScore not found in PATH. Skipping conversion.")
            return False
        except Exception as e:
            logger.error(f"Error converting to MuseScore: {str(e)}")
            return False
