"""Orchestrates the 5-step transcription pipeline (cascade + individual steps).

Pipeline::

    1. OCR (Tesseract)         -> raw text          [OCRService — existing]
    2. LLM: clean lyrics       -> MusicPiece.lyrics  [src.llm.lyrics_cleaner]
    3. OMR (Audiveris)         -> MusicXML file      [OMRService — existing]
    4. LLM: correct score      -> new MusicFile(XML) [src.llm.score_corrector]
    5. LLM: underlay + verify  -> new MusicFile(XML) [src.llm.lyric_underlayer]

The steps can run individually or, via :meth:`PipelineService.run_full`, cascade one after
another. The cascade passes artefacts in memory and skips dependent steps gracefully when a
prerequisite is missing (empty OCR → no step 2; OMR produced no MusicXML → no steps 4/5;
no clean lyrics → no step 5).

Following the project convention used by ``OCRService`` / ``OMRService``, **the caller is
responsible for committing the session.**
"""

import logging
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from src.database.models import FileType, MusicFile, MusicPiece
from src.llm.client import llm_available
from src.llm.musicxml_validate import load_musicxml_text
from src.services.file_service import FileService
from src.services.ocr_service import OCRService
from src.services.omr_service import OMRService

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, str], None]  # (step_name, status) -> None


class PipelineService:
    """Run the OCR→LLM→OMR→LLM→LLM pipeline, whole or step by step."""

    @staticmethod
    def llm_available() -> bool:
        """True when the LLM steps (2, 4, 5) can run (SDK installed + credentials)."""
        return llm_available()

    # ------------------------------------------------------------------
    # Individual LLM steps
    # ------------------------------------------------------------------

    def run_step2_clean_text(self, db: Session, piece_id: int, raw_text: str) -> dict:
        """Step 2 — clean OCR text into lyrics and store on the parent piece.

        Writes ``MusicPiece.lyrics`` and fills ``language`` when still blank.
        """
        from src.llm.lyrics_cleaner import clean_lyrics

        if not raw_text or not raw_text.strip():
            return {"status": "skipped", "detail": "Brak tekstu OCR do oczyszczenia."}

        result = clean_lyrics(raw_text)
        piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            return {"status": "error", "detail": f"Nie znaleziono utworu id={piece_id}."}

        piece.lyrics = result.cleaned_lyrics
        lang = (result.language or "").strip().lower()
        if lang and lang not in ("und", "unknown") and not piece.language:
            piece.language = lang
        db.flush()

        return {
            "status": "ok",
            "detail": result.notes,
            "language": result.language,
            "lyrics": result.cleaned_lyrics,
        }

    def run_step4_correct_score(self, db: Session, piece_id: int, xml_path: str) -> dict:
        """Step 4 — correct an OMR MusicXML file; persist a NEW MusicFile on success."""
        from src.llm.score_corrector import correct_score

        try:
            source_xml = load_musicxml_text(xml_path)
        except Exception as exc:
            logger.exception("run_step4: nie udało się wczytać MusicXML %s", xml_path)
            return {"status": "error", "detail": f"Nie wczytano MusicXML: {exc}"}

        context = self._analysis_context(xml_path)
        result = correct_score(source_xml, analysis_context=context)

        if not result.changed:
            return {
                "status": "ok",
                "changed": False,
                "report": result.report,
                "musicxml": result.musicxml,
                "detail": "Brak zaakceptowanych zmian — zachowano oryginał OMR.",
            }

        record = self._save_xml(
            db,
            piece_id,
            self._derived_name(xml_path, prefix="corrected"),
            result.musicxml,
            description="Korekta partytury (LLM) — krok 4",
        )
        return {
            "status": "ok",
            "changed": True,
            "report": result.report,
            "musicxml": result.musicxml,
            "output_file_id": record.id,
            "output_path": record.file_path,
            "detail": "Zapisano poprawiony plik MusicXML.",
        }

    def run_step5_underlay(
        self,
        db: Session,
        piece_id: int,
        lyrics: str,
        *,
        xml_path: Optional[str] = None,
        xml_content: Optional[str] = None,
    ) -> dict:
        """Step 5 — underlay lyrics into the corrected MusicXML; persist a NEW MusicFile."""
        from src.llm.lyric_underlayer import underlay_lyrics

        if not lyrics or not lyrics.strip():
            return {"status": "skipped", "detail": "Brak oczyszczonego tekstu do podłożenia."}

        if xml_content is None:
            if not xml_path:
                return {"status": "error", "detail": "Nie podano pliku MusicXML."}
            try:
                xml_content = load_musicxml_text(xml_path)
            except Exception as exc:
                logger.exception("run_step5: nie udało się wczytać MusicXML %s", xml_path)
                return {"status": "error", "detail": f"Nie wczytano MusicXML: {exc}"}

        result = underlay_lyrics(lyrics, xml_content)

        if not result.changed:
            return {
                "status": "ok",
                "changed": False,
                "report": result.report,
                "detail": "Nie utworzono finalnego pliku — zachowano plik z korekty.",
            }

        base = xml_path or "score.xml"
        record = self._save_xml(
            db,
            piece_id,
            self._derived_name(base, prefix="final"),
            result.musicxml,
            description="Finalny MusicXML z podłożonym tekstem (LLM) — krok 5",
        )
        return {
            "status": "ok",
            "changed": True,
            "report": result.report,
            "output_file_id": record.id,
            "output_path": record.file_path,
            "detail": "Zapisano finalny plik MusicXML z tekstem.",
        }

    # ------------------------------------------------------------------
    # Cascade
    # ------------------------------------------------------------------

    def run_full(
        self,
        db: Session,
        file_id: int,
        on_progress: Optional[ProgressFn] = None,
    ) -> dict:
        """Run steps 1→5 in sequence on a source PDF/SCAN file.

        Artefacts are threaded between steps in memory. Each step contributes an entry to
        the returned ``steps`` list with ``status`` ∈ {``ok``, ``skipped``, ``error``}.
        The caller commits the session.
        """
        steps: list[dict] = []

        def record(name: str, result: dict) -> dict:
            entry = {"name": name, **result}
            steps.append(entry)
            if on_progress:
                on_progress(name, result.get("status", "ok"))
            return result

        music_file: Optional[MusicFile] = (
            db.query(MusicFile).filter(MusicFile.id == file_id).first()
        )
        if music_file is None:
            return {"steps": [], "error": f"Nie znaleziono pliku id={file_id}."}
        piece_id = music_file.music_piece_id

        # --- Step 1: OCR ---
        raw_text = ""
        try:
            ocr_res = OCRService().process_file(db, file_id)
            if ocr_res is None:
                record("1. OCR (Tesseract)", {"status": "error", "detail": "OCR nie powiódł się."})
            else:
                raw_text = ocr_res.get("text", "") or ""
                record(
                    "1. OCR (Tesseract)",
                    {
                        "status": "ok",
                        "detail": f"Pewność {ocr_res.get('confidence', 0)}%, "
                        f"{len(raw_text)} znaków.",
                    },
                )
        except Exception as exc:
            logger.exception("run_full: OCR crashed")
            record("1. OCR (Tesseract)", {"status": "error", "detail": str(exc)})

        # --- Step 2: clean text (LLM) ---
        clean_lyrics_text = ""
        if not self.llm_available():
            record("2. Oczyszczanie tekstu (LLM)", _llm_unavailable())
        else:
            try:
                r2 = self.run_step2_clean_text(db, piece_id, raw_text)
                if r2.get("status") == "ok":
                    clean_lyrics_text = r2.get("lyrics", "") or ""
                record("2. Oczyszczanie tekstu (LLM)", r2)
            except Exception as exc:
                logger.exception("run_full: step 2 crashed")
                record("2. Oczyszczanie tekstu (LLM)", {"status": "error", "detail": str(exc)})

        # --- Step 3: OMR ---
        xml_path: Optional[str] = None
        try:
            omr_res = OMRService().process_file(db, file_id)
            if omr_res and omr_res.get("success"):
                xml_path = omr_res.get("musicxml_path")
                record("3. OMR (Audiveris)", {"status": "ok", "detail": "MusicXML utworzony."})
            else:
                detail = (omr_res or {}).get("error", "Audiveris nie utworzył MusicXML.")
                record("3. OMR (Audiveris)", {"status": "error", "detail": detail})
        except Exception as exc:
            logger.exception("run_full: OMR crashed")
            record("3. OMR (Audiveris)", {"status": "error", "detail": str(exc)})

        # --- Step 4: correct score (LLM) ---
        corrected_xml: Optional[str] = None
        if xml_path is None:
            record(
                "4. Korekta partytury (LLM)",
                {"status": "skipped", "detail": "Brak MusicXML z OMR — krok pominięty."},
            )
        elif not self.llm_available():
            record("4. Korekta partytury (LLM)", _llm_unavailable())
        else:
            try:
                r4 = self.run_step4_correct_score(db, piece_id, xml_path)
                corrected_xml = r4.get("musicxml")
                record("4. Korekta partytury (LLM)", r4)
            except Exception as exc:
                logger.exception("run_full: step 4 crashed")
                record("4. Korekta partytury (LLM)", {"status": "error", "detail": str(exc)})

        # --- Step 5: underlay lyrics + validate (LLM) ---
        if corrected_xml is None:
            record(
                "5. Podkład tekstu (LLM)",
                {"status": "skipped", "detail": "Brak poprawionej partytury — krok pominięty."},
            )
        elif not clean_lyrics_text.strip():
            record(
                "5. Podkład tekstu (LLM)",
                {"status": "skipped", "detail": "Brak oczyszczonego tekstu — krok pominięty."},
            )
        elif not self.llm_available():
            record("5. Podkład tekstu (LLM)", _llm_unavailable())
        else:
            try:
                r5 = self.run_step5_underlay(
                    db, piece_id, clean_lyrics_text, xml_path=xml_path, xml_content=corrected_xml
                )
                record("5. Podkład tekstu (LLM)", r5)
            except Exception as exc:
                logger.exception("run_full: step 5 crashed")
                record("5. Podkład tekstu (LLM)", {"status": "error", "detail": str(exc)})

        return {"steps": steps, "piece_id": piece_id}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _analysis_context(self, xml_path: str) -> Optional[str]:
        """Build a short musical summary to ground the score-correction prompt."""
        from src.services.analysis_service import AnalysisService

        try:
            descriptor = AnalysisService().analyze_file(xml_path)
        except Exception:
            logger.warning("pipeline: analiza kontekstu nie powiodła się", exc_info=True)
            return None
        if descriptor is None:
            return None

        ts = descriptor.time_signatures[0] if descriptor.time_signatures else "?"
        voices = ", ".join(descriptor.voice_names) if descriptor.voice_names else "?"
        return (
            f"Tonacja: {descriptor.detected_key or '?'}; metrum: {ts}; "
            f"taktów: {descriptor.measure_count or '?'}; głosy ({descriptor.voice_count}): "
            f"{voices}; epoka: {descriptor.harmony_epoch or '?'}; "
            f"faktura: {descriptor.texture_type or '?'}."
        )

    def _save_xml(
        self,
        db: Session,
        piece_id: int,
        filename: str,
        content: str,
        description: str,
    ) -> MusicFile:
        """Persist MusicXML content as a new MusicFile (FileType.XML)."""
        stored_path = FileService.save_uploaded_file(
            piece_id=piece_id,
            filename=filename,
            file_data=content.encode("utf-8"),
        )
        path = Path(stored_path)
        record = MusicFile(
            music_piece_id=piece_id,
            file_path=str(path),
            file_type=FileType.XML,
            original_filename=path.name,
            file_size=path.stat().st_size if path.exists() else None,
            mime_type="application/vnd.recordare.musicxml+xml",
            description=description,
            is_processed=1,
        )
        db.add(record)
        db.flush()  # populate record.id
        logger.info("pipeline: zapisano %s jako file_id=%s", path.name, record.id)
        return record

    @staticmethod
    def _derived_name(source_path: str, *, prefix: str) -> str:
        """Build a ``<prefix>_<stem>.xml`` filename from a source path."""
        stem = Path(source_path).stem or "score"
        return f"{prefix}_{stem}.xml"


def _llm_unavailable() -> dict:
    return {
        "status": "skipped",
        "detail": "Gemini LLM niedostępny (brak pakietu 'google-genai' lub klucza GEMINI_API_KEY).",
    }
