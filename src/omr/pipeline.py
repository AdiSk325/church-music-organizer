"""Compiler-style OMR pipeline.

The pipeline treats OMR as a compilation problem rather than an AI guessing
problem:

    Image/MusicXML → Symbols → ScoreGraph (IR) → Constraint Solver
        → LLM Repair (if needed) → MusicXML output

Each stage transforms a representation:
1. **Symbol extraction** – uses Audiveris (via subprocess) or music21 to turn
   a scanned image / raw MusicXML into basic musical symbols.
2. **Graph construction** – maps those symbols onto a :class:`ScoreGraph`.
3. **Constraint solving** – validates the graph against music-theory rules and
   records all violations.
4. **LLM repair** – delegates *only violated* measures to the
   :class:`~src.omr.llm_repair.LLMRepairTool` for localised correction.
5. **Export** – converts the validated ScoreGraph back to MusicXML via music21.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .constraints import ConstraintEngine, ConstraintViolation
from .llm_repair import LLMRepairTool
from .score_graph import Measure, Note, ScoreGraph, Voice, VoiceType

logger = logging.getLogger(__name__)


class OMRPipeline:
    """End-to-end OMR pipeline from image/file to validated MusicXML.

    Args:
        output_dir:       Directory where output MusicXML files are written.
        use_llm_repair:   Enable LLM-based repair for constraint violations.
        llm_api_key:      API key for the LLM repair tool (optional).
        reference_matcher: A pre-loaded
            :class:`~src.omr.reference_matcher.ReferenceMatcher` used for
            reference-assisted constraint propagation (optional).
    """

    def __init__(
        self,
        output_dir: str = "data/processed",
        use_llm_repair: bool = True,
        llm_api_key: Optional[str] = None,
        reference_matcher=None,
        audiveris_timeout: int = 120,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.constraint_engine = ConstraintEngine()
        self.llm_repair = LLMRepairTool(api_key=llm_api_key) if use_llm_repair else None
        self.reference_matcher = reference_matcher
        self.audiveris_timeout = audiveris_timeout

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def run(
        self,
        input_path: str,
        output_filename: Optional[str] = None,
    ) -> Tuple[ScoreGraph, List[ConstraintViolation], Optional[str]]:
        """Run the full pipeline on an image or MusicXML file.

        Args:
            input_path:      Path to the input file (image, PDF, or MusicXML).
            output_filename: Optional filename for the exported MusicXML.

        Returns:
            A 3-tuple of:
            - :class:`ScoreGraph` (validated)
            - :class:`list` of remaining :class:`ConstraintViolation` objects
            - ``str`` path to the exported MusicXML file, or ``None`` on failure
        """
        input_path = str(input_path)
        logger.info("OMR pipeline starting: %s", input_path)

        # Stage 1: Symbol extraction
        score = self._extract_to_score_graph(input_path)
        if score is None:
            logger.error("Symbol extraction failed for %s", input_path)
            return ScoreGraph(), [], None

        # Stage 2: Reference-assisted constraint propagation (optional)
        if self.reference_matcher is not None:
            score = self._apply_reference_constraints(score)

        # Stage 3: Constraint solving
        violations = self.constraint_engine.validate_all(score)
        logger.info("Found %d constraint violations.", len(violations))

        # Stage 4: LLM repair for violated measures
        if violations and self.llm_repair is not None:
            score, violations = self._repair_violations(score, violations)

        # Stage 5: Export to MusicXML
        output_path = self._export_musicxml(score, output_filename)

        logger.info("Pipeline complete. Remaining violations: %d", len(violations))
        return score, violations, output_path

    # -----------------------------------------------------------------------
    # Stage 1: Symbol extraction
    # -----------------------------------------------------------------------

    def _extract_to_score_graph(self, input_path: str) -> Optional[ScoreGraph]:
        """Dispatch to the appropriate extractor based on file extension."""
        ext = Path(input_path).suffix.lower()
        if ext in (".xml", ".musicxml", ".mxl"):
            return self.musicxml_to_score_graph(input_path)
        if ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
            return self._image_to_score_graph(input_path)
        if ext == ".pdf":
            return self._pdf_to_score_graph(input_path)
        logger.warning("Unsupported input format: %s", ext)
        return None

    def musicxml_to_score_graph(self, musicxml_path: str) -> Optional[ScoreGraph]:
        """Convert a MusicXML file to a :class:`ScoreGraph` using music21.

        This is the primary path for reference loading and for processing
        Audiveris output.
        """
        try:
            from music21 import converter  # type: ignore[import]

            score21 = converter.parse(musicxml_path)
            return _music21_to_score_graph(score21)
        except Exception as exc:  # noqa: BLE001
            logger.error("music21 failed to parse '%s': %s", musicxml_path, exc)
            return None

    def _image_to_score_graph(self, image_path: str) -> Optional[ScoreGraph]:
        """Process a scanned image: try Audiveris first, fall back to stub."""
        # Attempt Audiveris conversion to MusicXML
        musicxml_path = self._run_audiveris(image_path)
        if musicxml_path and Path(musicxml_path).exists():
            logger.info("Using Audiveris output: %s", musicxml_path)
            return self.musicxml_to_score_graph(musicxml_path)

        logger.warning(
            "Audiveris unavailable for '%s'; returning empty ScoreGraph stub.",
            image_path,
        )
        return ScoreGraph(title=Path(image_path).stem)

    def _pdf_to_score_graph(self, pdf_path: str) -> Optional[ScoreGraph]:
        """Convert a PDF to images and process each page."""
        try:
            from pdf2image import convert_from_path  # type: ignore[import]
        except ImportError:
            logger.warning("pdf2image not installed; cannot process PDF.")
            return None

        images = convert_from_path(pdf_path)
        if not images:
            return None

        # Process first page only (extend if multi-page support needed)
        tmp_path = self.output_dir / "_tmp_pdf_page0.png"
        images[0].save(str(tmp_path))
        result = self._image_to_score_graph(str(tmp_path))
        tmp_path.unlink(missing_ok=True)
        return result

    # -----------------------------------------------------------------------
    # Audiveris integration
    # -----------------------------------------------------------------------

    def _run_audiveris(self, image_path: str) -> Optional[str]:
        """Run Audiveris CLI on *image_path* and return the output MusicXML path.

        Returns ``None`` if Audiveris is not installed or the conversion fails.
        """
        output_dir = str(self.output_dir)
        try:
            result = subprocess.run(
                [
                    "audiveris",
                    "-batch",
                    "-export",
                    "-output", output_dir,
                    image_path,
                ],
                capture_output=True,
                text=True,
                timeout=self.audiveris_timeout,
            )
            if result.returncode != 0:
                logger.debug("Audiveris stderr: %s", result.stderr)
                return None

            # Audiveris writes <stem>.mxl or <stem>.xml in the output dir
            stem = Path(image_path).stem
            for suffix in (".mxl", ".xml"):
                candidate = Path(output_dir) / f"{stem}{suffix}"
                if candidate.exists():
                    return str(candidate)
            return None

        except FileNotFoundError:
            logger.debug("Audiveris not found in PATH.")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("Audiveris timed out on '%s'.", image_path)
            return None

    # -----------------------------------------------------------------------
    # Stage 2: Reference-assisted constraints
    # -----------------------------------------------------------------------

    def _apply_reference_constraints(self, score: ScoreGraph) -> ScoreGraph:
        """Use the nearest reference match to fill in missing metadata."""
        results = self.reference_matcher.find_nearest(score, top_k=1)
        if not results:
            return score

        best = results[0].score
        logger.info(
            "Reference match: '%s' (similarity %.2f)", best.title, results[0].similarity
        )

        # Propagate metadata from reference when missing in the OMR output
        if not score.key_signature or score.key_signature == "C":
            score.key_signature = best.key_signature
        if not score.time_signature or score.time_signature == "4/4":
            score.time_signature = best.time_signature

        return score

    # -----------------------------------------------------------------------
    # Stage 3 & 4: Constraint solving + LLM repair
    # -----------------------------------------------------------------------

    def _repair_violations(
        self,
        score: ScoreGraph,
        violations: List[ConstraintViolation],
    ) -> Tuple[ScoreGraph, List[ConstraintViolation]]:
        """Repair each violated measure using the LLM repair tool."""
        violated_measure_numbers = {v.measure_number for v in violations}

        new_measures: List[Measure] = []
        for measure in score.measures:
            if measure.number in violated_measure_numbers:
                measure_violations = [v for v in violations if v.measure_number == measure.number]
                context = _surrounding_measures(score.measures, measure.number, window=2)
                repaired = self.llm_repair.repair_measure(measure, measure_violations, context)
                new_measures.append(repaired)
            else:
                new_measures.append(measure)

        repaired_score = ScoreGraph(
            title=score.title,
            composer=score.composer,
            key_signature=score.key_signature,
            time_signature=score.time_signature,
            measures=new_measures,
            metadata=score.metadata,
        )

        # Re-validate to get remaining violations
        remaining_violations = self.constraint_engine.validate_all(repaired_score)
        return repaired_score, remaining_violations

    # -----------------------------------------------------------------------
    # Stage 5: Export
    # -----------------------------------------------------------------------

    def _export_musicxml(
        self,
        score: ScoreGraph,
        output_filename: Optional[str] = None,
    ) -> Optional[str]:
        """Convert *score* to MusicXML and write to :attr:`output_dir`."""
        try:
            from src.ocr.musicxml_converter import MusicXMLConverter  # noqa: PLC0415

            converter = MusicXMLConverter(str(self.output_dir))
            score21 = converter.score_graph_to_score(score)

            filename = output_filename or f"{score.title or 'output'}.xml"
            output_path = str(self.output_dir / filename)
            success = converter.save_as_musicxml(score21, output_path)
            return output_path if success else None
        except Exception as exc:  # noqa: BLE001
            logger.error("Export to MusicXML failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# music21 → ScoreGraph conversion helpers
# ---------------------------------------------------------------------------

def _music21_to_score_graph(score21) -> ScoreGraph:
    """Convert a music21 Score object to a :class:`ScoreGraph`."""
    from music21 import stream as m21stream, note as m21note, chord as m21chord  # type: ignore

    title = ""
    composer = ""
    if score21.metadata:
        title = score21.metadata.title or ""
        composer = str(score21.metadata.composer) if score21.metadata.composer else ""

    # Global key / time signature from the first part
    key_sig = "C"
    time_sig = "4/4"
    first_part = score21.parts[0] if score21.parts else None
    if first_part:
        ks = first_part.recurse().getElementsByClass("KeySignature").first()
        if ks:
            key_sig = ks.tonic.name if hasattr(ks, "tonic") else str(ks)
        ts = first_part.recurse().getElementsByClass("TimeSignature").first()
        if ts:
            time_sig = ts.ratioString

    measures: List[Measure] = []

    # Assign voices across parts: SATB order where possible
    satb_assignment = [VoiceType.SOPRANO, VoiceType.ALTO, VoiceType.TENOR, VoiceType.BASS]

    # Collect measure objects from each part
    parts = list(score21.parts)
    measure_count = max(
        (len(list(part.getElementsByClass(m21stream.Measure))) for part in parts),
        default=0,
    )

    for m_idx in range(measure_count):
        voices: List[Voice] = []
        measure_number = m_idx + 1
        measure_time_sig = time_sig

        for part_idx, part in enumerate(parts):
            part_measures = list(part.getElementsByClass(m21stream.Measure))
            if m_idx >= len(part_measures):
                continue
            m21_measure = part_measures[m_idx]

            # Update time sig if overridden in this measure
            ts_in_measure = m21_measure.getElementsByClass("TimeSignature").first()
            if ts_in_measure and m_idx == 0:
                measure_time_sig = ts_in_measure.ratioString

            voice_type = satb_assignment[part_idx] if part_idx < len(satb_assignment) else VoiceType.UNASSIGNED
            notes = _extract_notes_from_measure(m21_measure, voice_id=part_idx)
            voices.append(Voice(voice_id=part_idx, voice_type=voice_type, notes=notes))

        measures.append(
            Measure(number=measure_number, time_signature=measure_time_sig, voices=voices)
        )

    return ScoreGraph(
        title=title,
        composer=composer,
        key_signature=key_sig,
        time_signature=time_sig,
        measures=measures,
    )


def _extract_notes_from_measure(m21_measure, voice_id: int) -> List[Note]:
    """Extract :class:`Note` objects from a music21 Measure."""
    from music21 import note as m21note, chord as m21chord  # type: ignore

    notes: List[Note] = []
    for element in m21_measure.flatten().notesAndRests:
        onset = float(element.offset)
        duration = float(element.duration.quarterLength)

        if isinstance(element, m21note.Rest):
            notes.append(Note(pitch="R", duration=duration, onset=onset, voice_id=voice_id))
        elif isinstance(element, m21note.Note):
            pitch = element.nameWithOctave  # e.g. "C4"
            notes.append(Note(pitch=pitch, duration=duration, onset=onset, voice_id=voice_id))
        elif isinstance(element, m21chord.Chord):
            # Take the highest note as the representative pitch
            top = max(element.pitches, key=lambda p: p.midi)
            notes.append(
                Note(pitch=top.nameWithOctave, duration=duration, onset=onset, voice_id=voice_id)
            )

    return sorted(notes, key=lambda n: n.onset)


def _surrounding_measures(
    measures: List[Measure], target_number: int, window: int = 2
) -> List[Measure]:
    """Return up to *window* measures before and after *target_number*."""
    result = []
    for m in measures:
        if m.number != target_number and abs(m.number - target_number) <= window:
            result.append(m)
    return result
