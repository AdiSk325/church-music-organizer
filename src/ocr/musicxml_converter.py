"""Music notation converter for converting OCR results to MusicXML.

Produces MusicXML files that can be directly imported and edited in MuseScore.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from music21 import key as m21key
from music21 import metadata, meter, note, stream

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

    def create_from_metadata(
        self,
        title: str,
        composer: str = None,
        key: str = None,
        time_sig: str = None,
    ) -> stream.Score:
        """Create a basic MusicXML score from metadata.

        Args:
            title: Title of the piece
            composer: Composer name
            key: Key signature (e.g. "C major", "D minor")
            time_sig: Time signature (e.g. "4/4", "3/4")

        Returns:
            music21 Score object
        """
        score = stream.Score()

        # Add metadata
        score.metadata = metadata.Metadata()
        score.metadata.title = title
        if composer:
            score.metadata.composer = composer

        # Create a part with a single empty measure
        part = stream.Part()
        part.partName = "Voice"

        m = stream.Measure(number=1)

        # Key signature
        if key:
            try:
                ks = m21key.Key(key)
                m.insert(0, ks)
            except Exception:
                logger.debug("Could not parse key signature: %s", key)

        # Time signature
        if time_sig:
            try:
                ts = meter.TimeSignature(time_sig)
                m.insert(0, ts)
            except Exception:
                logger.debug("Could not parse time signature: %s", time_sig)

        # One whole rest so MuseScore opens the file cleanly
        r = note.Rest(quarterLength=4.0)
        m.append(r)

        part.append(m)
        score.append(part)

        return score

    def create_score_with_lyrics(
        self,
        title: str,
        composer: Optional[str] = None,
        lyrics: Optional[str] = None,
        key_sig: Optional[str] = None,
        time_sig: Optional[str] = None,
    ) -> stream.Score:
        """Create a MusicXML score with lyrics attached as text.

        The generated score contains a single voice part with placeholder notes.
        Lyrics are split by whitespace and attached syllable-by-syllable so that
        MuseScore displays them underneath the staff.  This allows the user to
        add the actual melody while keeping the lyrics aligned.

        Args:
            title: Title of the piece.
            composer: Optional composer name.
            lyrics: Optional lyrics text extracted from the scan.
            key_sig: Optional key signature string (e.g. "C major").
            time_sig: Optional time signature string (e.g. "4/4").

        Returns:
            A music21 Score object ready to be written as MusicXML.
        """
        score = stream.Score()
        score.metadata = metadata.Metadata()
        score.metadata.title = title
        if composer:
            score.metadata.composer = composer

        part = stream.Part()
        part.partName = "Voice"

        measure_num = 1
        first_measure = stream.Measure(number=measure_num)

        # Key signature
        if key_sig:
            try:
                ks = m21key.Key(key_sig)
                first_measure.insert(0, ks)
            except Exception:
                pass

        # Time signature
        ts_obj = None
        if time_sig:
            try:
                ts_obj = meter.TimeSignature(time_sig)
                first_measure.insert(0, ts_obj)
            except Exception:
                pass

        beats_per_measure = ts_obj.numerator if ts_obj else 4

        if lyrics and lyrics.strip():
            syllables = lyrics.split()
            current_measure = first_measure
            beat = 0

            for syllable in syllables:
                if beat >= beats_per_measure:
                    part.append(current_measure)
                    measure_num += 1
                    current_measure = stream.Measure(number=measure_num)
                    beat = 0

                n = note.Note("C4", quarterLength=1.0)
                n.lyric = syllable
                current_measure.append(n)
                beat += 1

            # Pad remaining beats in last measure with rests
            if beat < beats_per_measure:
                r = note.Rest(quarterLength=float(beats_per_measure - beat))
                current_measure.append(r)
            part.append(current_measure)
        else:
            # Empty measure with a whole rest
            r = note.Rest(quarterLength=4.0)
            first_measure.append(r)
            part.append(first_measure)

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
            score.write("musicxml", fp=output_path)
            logger.info("MusicXML saved to %s", output_path)
            return True
        except Exception as e:
            logger.error("Error saving MusicXML to %s: %s", output_path, e)
            return False

    def validate_musicxml(self, musicxml_path: str) -> bool:
        """Validate that a MusicXML file can be parsed by music21.

        Args:
            musicxml_path: Path to the MusicXML file.

        Returns:
            True if the file is valid MusicXML.
        """
        try:
            from music21 import converter

            parsed = converter.parse(musicxml_path)
            return parsed is not None
        except Exception as e:
            logger.error("MusicXML validation failed for %s: %s", musicxml_path, e)
            return False

    def convert_to_musescore(self, musicxml_path: str, output_path: str) -> bool:
        """Convert MusicXML to MuseScore format.

        Tries common MuseScore CLI names: ``mscore``, ``musescore``,
        ``musescore4``, ``MuseScore4``.

        Args:
            musicxml_path: Path to the MusicXML file
            output_path: Path to save the MuseScore file (.mscz)

        Returns:
            True if successful, False otherwise
        """
        candidates = ["mscore", "musescore", "musescore4", "MuseScore4"]
        exe = None
        for name in candidates:
            if shutil.which(name):
                exe = name
                break

        if exe is None:
            logger.warning(
                "MuseScore not found in PATH (tried %s). "
                "The MusicXML file can be imported manually.",
                ", ".join(candidates),
            )
            return False

        try:
            result = subprocess.run(
                [exe, musicxml_path, "-o", output_path],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                logger.info("MuseScore file saved to %s", output_path)
                return True
            else:
                logger.error("MuseScore conversion failed: %s", result.stderr)
                return False
        except subprocess.TimeoutExpired:
            logger.warning("MuseScore conversion timed out.")
            return False
        except Exception as e:
            logger.error("Error converting to MuseScore: %s", e)
            return False
