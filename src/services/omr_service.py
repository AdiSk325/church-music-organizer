"""Orchestrates OMR processing (PDF → MusicXML via Audiveris) and persists results."""

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.analysis.score_descriptor import ScoreDescriptor
from src.database.models import FileType, MusicFile, MusicFileKind, MusicPiece
from src.ocr.pdf_to_musicxml import PdfToMusicXml, audiveris_available

logger = logging.getLogger(__name__)

# File types that can be fed to Audiveris OMR.
_SUPPORTED_TYPES = {FileType.PDF, FileType.SCAN}

# ISO 639-1 codes (as produced by the analyser) → human-readable Polish labels.
_LANG_LABELS = {
    "la": "łacina",
    "pl": "polski",
    "en": "angielski",
    "de": "niemiecki",
    "it": "włoski",
    "fr": "francuski",
    "es": "hiszpański",
}


class OMRService:
    """Run Audiveris OMR on a MusicFile and persist the resulting MusicXML.

    Usage::

        service = OMRService()
        if OMRService.is_available():
            result = service.process_file(db, file_id=42)
            if result and result["success"]:
                db.commit()
    """

    def __init__(self, output_dir: str = "data/processed"):
        """Initialise the service.

        Args:
            output_dir: Directory where Audiveris will write its MusicXML
                output.  Created automatically if it does not exist.
        """
        self._output_dir = output_dir
        self._converter = PdfToMusicXml()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Return True when Audiveris is installed and can be invoked.

        Used by the UI layer to show / hide the OMR button gracefully instead
        of raising an exception.
        """
        return audiveris_available()

    def process_file(self, db: Session, file_id: int) -> Optional[dict]:
        """Run Audiveris OMR on a MusicFile and save the resulting MusicXML.

        The generated MusicXML is persisted as a new ``MusicFile`` record
        (``FileType.XML``) attached to the same ``music_piece_id``.

        **The caller is responsible for committing the session** — this mirrors
        the convention used by ``OCRService`` / ``FileService``.

        Args:
            db: Active SQLAlchemy session.
            file_id: Primary key of the source ``MusicFile`` to process.
                     Must be of type ``PDF`` or ``SCAN``.

        Returns:
            On success::

                {
                    "success": True,
                    "file_id": <source file id>,
                    "music_piece_id": <int>,
                    "musicxml_path": "<absolute path to .mxl/.xml>",
                    "output_file_id": <new MusicFile id>,
                }

            On failure: ``None`` (or a dict with ``"success": False`` and
            ``"error": "<message>"`` when the source record exists but
            conversion failed).
        """
        # --- Locate source MusicFile record ---
        music_file: Optional[MusicFile] = (
            db.query(MusicFile).filter(MusicFile.id == file_id).first()
        )
        if music_file is None:
            logger.warning("OMRService: MusicFile id=%s not found", file_id)
            return None

        # --- Validate file type ---
        if music_file.file_type not in _SUPPORTED_TYPES:
            logger.warning(
                "OMRService: file_id=%s has unsupported type %s (expected PDF or SCAN)",
                file_id,
                music_file.file_type,
            )
            return {
                "success": False,
                "file_id": file_id,
                "error": (
                    f"Unsupported file type {music_file.file_type.value!r}. "
                    "OMR requires a PDF or SCAN file."
                ),
            }

        # --- Validate the file exists on disk ---
        src_path = Path(music_file.file_path)
        if not src_path.exists():
            logger.warning("OMRService: source file not on disk: %s", src_path)
            return {
                "success": False,
                "file_id": file_id,
                "error": f"Source file not found on disk: {src_path}",
            }

        # --- Run Audiveris ---
        logger.info(
            "OMRService: starting Audiveris for file_id=%s path=%s",
            file_id,
            src_path,
        )
        try:
            musicxml_path = self._converter.convert(
                input_path=str(src_path),
                output_dir=self._output_dir,
            )
        except Exception:
            logger.exception("OMRService: Audiveris raised an exception for file_id=%s", file_id)
            return {
                "success": False,
                "file_id": file_id,
                "error": "Audiveris raised an unexpected exception — see logs for details.",
            }

        if musicxml_path is None:
            logger.error("OMRService: Audiveris produced no output for file_id=%s", file_id)
            return {
                "success": False,
                "file_id": file_id,
                "error": "Audiveris completed but produced no MusicXML output.",
            }

        # --- Relocate the MusicXML into the piece's managed upload area ---
        # Audiveris writes to ``output_dir`` (scratch); we move the result next to
        # the piece's other files so it is logically grouped and discoverable.
        # Imported lazily to avoid a circular import at package-init time
        # (src.services.__init__ imports this module).
        from src.services.file_service import FileService

        piece_id = music_file.music_piece_id
        tmp_xml = Path(musicxml_path)

        # Route the OMR artefact into the piece's library folder (derived/) when possible.
        # Fall back to the legacy upload directory if the piece cannot be located.
        piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        try:
            if piece is not None:
                stored_path = FileService.save_uploaded_file(
                    piece_id=piece_id,
                    filename=tmp_xml.name,
                    file_data=tmp_xml.read_bytes(),
                    use_library=True,
                    piece=piece,
                    kind=MusicFileKind.OMR_RAW,
                )
            else:
                stored_path = FileService.save_uploaded_file(
                    piece_id=piece_id,
                    filename=tmp_xml.name,
                    file_data=tmp_xml.read_bytes(),
                )
            if Path(stored_path).resolve() != tmp_xml.resolve() and tmp_xml.exists():
                tmp_xml.unlink()  # drop the scratch copy after relocating
        except Exception:
            logger.exception("OMRService: could not relocate MusicXML; keeping scratch copy")
            stored_path = str(tmp_xml)

        xml_path = Path(stored_path)

        # --- Persist the generated MusicXML as a new MusicFile ---
        output_record = MusicFile(
            music_piece_id=piece_id,
            file_path=str(xml_path),
            file_type=FileType.XML,
            original_filename=xml_path.name,
            file_size=xml_path.stat().st_size if xml_path.exists() else None,
            mime_type="application/vnd.recordare.musicxml+xml",
            description="OMR output (Audiveris) — auto-analysed",
            is_processed=1,
            kind=MusicFileKind.OMR_RAW,
        )
        db.add(output_record)
        db.flush()  # populate output_record.id before returning

        logger.info(
            "OMRService: saved MusicXML as file_id=%s for music_piece_id=%s path=%s",
            output_record.id,
            piece_id,
            xml_path,
        )

        # --- Automatically analyse the score and enrich the parent piece ---
        analysis = self._apply_analysis(db, piece_id, str(xml_path))

        return {
            "success": True,
            "file_id": file_id,
            "music_piece_id": piece_id,
            "musicxml_path": str(xml_path),
            "output_file_id": output_record.id,
            "analysis": analysis,
        }

    def _apply_analysis(self, db: Session, piece_id: int, xml_path: str) -> Optional[dict]:
        """Analyse the MusicXML and fill empty metadata fields of the parent piece.

        Only blank fields are populated (existing user data is never overwritten),
        and the narrative description is appended once under an ``[Auto-analiza OMR]``
        marker. Returns a short summary dict, or ``None`` when analysis fails.
        Caller commits the session.
        """
        from src.services.analysis_service import AnalysisService

        try:
            descriptor: Optional[ScoreDescriptor] = AnalysisService().analyze_file(xml_path)
        except Exception:
            logger.exception("OMRService: analysis crashed for piece_id=%s", piece_id)
            return None
        if descriptor is None:
            logger.warning("OMRService: analysis returned nothing for piece_id=%s", piece_id)
            return None

        piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            return descriptor.to_dict()

        def _meaningful(value) -> bool:
            # The analyser uses sentinels like "unknown"/"none" for undetected
            # attributes — never write those into the piece's metadata.
            return bool(value) and str(value).strip().lower() not in ("unknown", "none", "n/a")

        def _fill(attr: str, value) -> None:
            if _meaningful(value) and not getattr(piece, attr):
                setattr(piece, attr, value)

        first_ts = descriptor.time_signatures[0] if descriptor.time_signatures else None
        lang = _LANG_LABELS.get(descriptor.lyrics_language, descriptor.lyrics_language)
        _fill("key_signature", descriptor.detected_key)
        _fill("time_signature", first_ts)
        _fill("tempo", descriptor.tempo_marking)
        _fill("composer", descriptor.composer)
        _fill("lyrics_author", descriptor.lyricist)
        _fill("language", lang)
        if descriptor.measure_count and not piece.measures_count:
            piece.measures_count = descriptor.measure_count

        narrative = descriptor.narrative_description
        if narrative:
            marker = "[Auto-analiza OMR]"
            if marker not in (piece.description or ""):
                existing = (piece.description or "").rstrip()
                sep = "\n\n" if existing else ""
                piece.description = f"{existing}{sep}{marker} {narrative}"

        db.flush()
        logger.info("OMRService: applied auto-analysis to piece_id=%s", piece_id)
        return {
            "detected_key": descriptor.detected_key,
            "key_confidence": round(descriptor.key_confidence, 2),
            "time_signatures": descriptor.time_signatures,
            "measure_count": descriptor.measure_count,
            "voice_count": descriptor.voice_count,
            "voice_names": descriptor.voice_names,
            "texture_type": descriptor.texture_type,
            "harmony_epoch": descriptor.harmony_epoch,
            "lyrics_language": lang if _meaningful(lang) else None,
            "estimated_grade": descriptor.estimated_grade,
            "grade_label": descriptor.grade_label,
            "narrative": narrative,
            # Full descriptor for persistence (PipelineService stores it as the
            # `analysis` step's data_json so the whole analysis survives reloads).
            "descriptor_full": descriptor.to_dict(),
        }
