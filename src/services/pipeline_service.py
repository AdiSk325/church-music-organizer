"""Orchestrates the 5-step transcription pipeline (cascade + individual steps).

Pipeline::

    1. OCR (Tesseract)         -> raw text          [OCRService — existing]
    2. LLM: clean lyrics       -> MusicPiece.lyrics  [src.llm.lyrics_cleaner]
    3. OMR (Audiveris)         -> MusicXML file      [OMRService — existing]
       + score analysis        -> ScoreDescriptor    [AnalysisService — persisted]
    4. LLM: correct score      -> new MusicFile(XML) [src.llm.score_corrector]
    5. LLM: underlay + verify  -> new MusicFile(XML) [src.llm.lyric_underlayer]

The steps can run individually or, via :meth:`PipelineService.run_full`, cascade one after
another. The cascade passes artefacts in memory and skips dependent steps gracefully when a
prerequisite is missing (empty OCR → no step 2; OMR produced no MusicXML → no steps 4/5;
no clean lyrics → no step 5).

Every step run is **persisted** as a :class:`ProcessingStep` row (status, detail, report,
structured payload, produced file, wall-clock time), so the intermediate results survive a
page reload and can be shown per-section in the UI. This service is the single place that
writes those rows — the UI calls these methods rather than the engines directly.

Following the project convention used by ``OCRService`` / ``OMRService``, **the caller is
responsible for committing the session.**
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from src.database.models import FileType, MusicFile, MusicFileKind, MusicPiece, ProcessingStep
from src.llm.client import llm_available
from src.llm.musicxml_validate import export_score_to_musicxml, load_musicxml_text
from src.services.file_service import FileService
from src.services.ocr_service import OCRService
from src.services.omr_service import OMRService

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, str], None]  # (step_name, status) -> None

# Stable step keys → human-readable labels, and the canonical display order. The UI imports
# both to render the processing-status panel and the progress bar.
STEP_LABELS = {
    "ocr": "1. OCR (Tesseract)",
    "metadata": "Metadane (LLM)",
    "clean_text": "2. Oczyszczanie tekstu (LLM)",
    "omr": "3. OMR (Audiveris)",
    "analysis": "Analiza partytury",
    "correct_score": "4. Korekta partytury (LLM)",
    "underlay": "5. Podkład tekstu (LLM)",
}
STEP_SEQUENCE = ["ocr", "metadata", "clean_text", "omr", "analysis", "correct_score", "underlay"]

# Map pipeline output prefix to semantic MusicFileKind so files land in the right
# library sub-directory: CORRECTED/FINAL → scores/, anything else → derived/.
_PREFIX_TO_KIND: dict = {
    "corrected": MusicFileKind.CORRECTED,
    "final": MusicFileKind.FINAL,
}

# Mapping ExtractedMetadata field -> MusicPiece attribute. Only EMPTY MusicPiece fields are
# filled, so the AI never overwrites what the user typed in by hand.
_METADATA_FIELDS = [
    ("title", "title"),
    ("composer", "composer"),
    ("music_author", "music_author"),
    ("lyrics_author", "lyrics_author"),
    ("arranger", "arranger"),
    ("genre", "genre"),
    ("language", "language"),
    ("occasion", "occasion"),
    ("liturgical_season", "liturgical_season"),
    ("source_copyright", "notes"),
]


class PipelineService:
    """Run the OCR→LLM→OMR→LLM→LLM pipeline, whole or step by step."""

    @staticmethod
    def llm_available() -> bool:
        """True when the LLM steps (2, 4, 5) can run (SDK installed + credentials)."""
        return llm_available()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _record_step(
        self,
        db: Session,
        *,
        piece_id: int,
        key: str,
        status: str,
        label: Optional[str] = None,
        detail: str = "",
        report: Optional[str] = None,
        data: Optional[dict] = None,
        source_file_id: Optional[int] = None,
        output_file_id: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> Optional[ProcessingStep]:
        """Append a :class:`ProcessingStep` row for one step run. Best-effort.

        Persistence never breaks the pipeline: a failure here is logged and swallowed so the
        actual transcription result is still returned to the caller.
        """
        if not piece_id:
            return None
        try:
            step = ProcessingStep(
                music_piece_id=piece_id,
                source_file_id=source_file_id,
                output_file_id=output_file_id,
                step_key=key,
                step_label=label or STEP_LABELS.get(key, key),
                status=status,
                detail=detail or "",
                report=report,
                data_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
                duration_ms=duration_ms,
            )
            db.add(step)
            db.flush()
            return step
        except Exception:  # pragma: no cover - defensive
            logger.exception("Nie udało się zapisać ProcessingStep (key=%s)", key)
            return None

    @staticmethod
    def _piece_id_for_file(db: Session, file_id: int) -> Optional[int]:
        mf = db.query(MusicFile).filter(MusicFile.id == file_id).first()
        return mf.music_piece_id if mf else None

    # ------------------------------------------------------------------
    # Engine steps (OCR / OMR) — wrappers that persist + return artefacts
    # ------------------------------------------------------------------

    def run_step1_ocr(self, db: Session, file_id: int) -> dict:
        """Step 1 — run Tesseract OCR on a source file and persist the outcome."""
        piece_id = self._piece_id_for_file(db, file_id)
        t0 = time.perf_counter()
        ocr_res = OCRService().process_file(db, file_id)
        dur = int((time.perf_counter() - t0) * 1000)

        if ocr_res is None:
            detail = "OCR nie powiódł się."
            self._record_step(
                db,
                piece_id=piece_id,
                key="ocr",
                status="error",
                detail=detail,
                source_file_id=file_id,
                duration_ms=dur,
            )
            return {"status": "error", "detail": detail, "text": ""}

        text = ocr_res.get("text", "") or ""
        conf = ocr_res.get("confidence", 0)
        has_notation = ocr_res.get("has_music_notation", False)
        detail = f"Pewność {conf}%, {len(text)} znaków."
        self._record_step(
            db,
            piece_id=piece_id,
            key="ocr",
            status="ok",
            detail=detail,
            data={"confidence": conf, "chars": len(text), "has_music_notation": has_notation},
            source_file_id=file_id,
            duration_ms=dur,
        )
        return {
            "status": "ok",
            "detail": detail,
            "text": text,
            "confidence": conf,
            "has_music_notation": has_notation,
        }

    def run_step3_omr(self, db: Session, file_id: int) -> dict:
        """Step 3 — run Audiveris OMR; persist the OMR step and the score analysis."""
        piece_id = self._piece_id_for_file(db, file_id)
        t0 = time.perf_counter()
        omr_res = OMRService().process_file(db, file_id)
        dur = int((time.perf_counter() - t0) * 1000)

        if not (omr_res and omr_res.get("success")):
            detail = (omr_res or {}).get("error", "Audiveris nie utworzył MusicXML.")
            self._record_step(
                db,
                piece_id=piece_id,
                key="omr",
                status="error",
                detail=detail,
                source_file_id=file_id,
                duration_ms=dur,
            )
            return {"status": "error", "detail": detail}

        xml_path = omr_res.get("musicxml_path")
        out_fid = omr_res.get("output_file_id")
        self._record_step(
            db,
            piece_id=piece_id,
            key="omr",
            status="ok",
            detail="MusicXML utworzony.",
            source_file_id=file_id,
            output_file_id=out_fid,
            duration_ms=dur,
        )

        # Persist the full score analysis as its own step (data_json = ScoreDescriptor).
        analysis = omr_res.get("analysis")
        if analysis:
            self._record_step(
                db,
                piece_id=piece_id,
                key="analysis",
                status="ok",
                detail=_analysis_detail(analysis),
                report=analysis.get("narrative"),
                data=analysis.get("descriptor_full") or analysis,
                source_file_id=out_fid,
            )

        return {
            "status": "ok",
            "detail": "MusicXML utworzony.",
            "musicxml_path": xml_path,
            "output_file_id": out_fid,
            "analysis": analysis,
        }

    # ------------------------------------------------------------------
    # Individual LLM steps
    # ------------------------------------------------------------------

    def run_step2_clean_text(
        self,
        db: Session,
        piece_id: int,
        raw_text: str,
        *,
        source_file_id: Optional[int] = None,
    ) -> dict:
        """Step 2 — clean OCR text into lyrics and store on the parent piece.

        Writes ``MusicPiece.lyrics`` and fills ``language`` when still blank.
        """
        from src.llm.lyrics_cleaner import clean_lyrics

        if not raw_text or not raw_text.strip():
            result = {"status": "skipped", "detail": "Brak tekstu OCR do oczyszczenia."}
            self._record_step(
                db,
                piece_id=piece_id,
                key="clean_text",
                status="skipped",
                detail=result["detail"],
                source_file_id=source_file_id,
            )
            return result

        t0 = time.perf_counter()
        cleaned = clean_lyrics(raw_text)
        dur = int((time.perf_counter() - t0) * 1000)

        piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            detail = f"Nie znaleziono utworu id={piece_id}."
            self._record_step(
                db,
                piece_id=piece_id,
                key="clean_text",
                status="error",
                detail=detail,
                source_file_id=source_file_id,
                duration_ms=dur,
            )
            return {"status": "error", "detail": detail}

        piece.lyrics = cleaned.cleaned_lyrics
        lang = (cleaned.language or "").strip().lower()
        if lang and lang not in ("und", "unknown") and not piece.language:
            piece.language = lang
        db.flush()

        result = {
            "status": "ok",
            "detail": cleaned.notes,
            "language": cleaned.language,
            "lyrics": cleaned.cleaned_lyrics,
        }
        self._record_step(
            db,
            piece_id=piece_id,
            key="clean_text",
            status="ok",
            detail=f"Język: {cleaned.language}; {len(cleaned.cleaned_lyrics or '')} znaków.",
            report=cleaned.notes,
            data={"language": cleaned.language, "lyrics": cleaned.cleaned_lyrics},
            source_file_id=source_file_id,
            duration_ms=dur,
        )
        return result

    def run_step_metadata(
        self,
        db: Session,
        piece_id: int,
        ocr_text: str,
        *,
        score_metadata: Optional[dict] = None,
        source_file_id: Optional[int] = None,
    ) -> dict:
        """Extract header metadata (title/authors/…) and fill EMPTY MusicPiece fields only.

        Never overwrites fields the user already filled. Returns the extracted values plus the
        list of fields actually applied, so the UI can show what changed.
        """
        from src.llm.metadata_extractor import extract_metadata

        if not (ocr_text and ocr_text.strip()) and not score_metadata:
            detail = "Brak tekstu OCR do ekstrakcji metadanych."
            self._record_step(
                db,
                piece_id=piece_id,
                key="metadata",
                status="skipped",
                detail=detail,
                source_file_id=source_file_id,
            )
            return {"status": "skipped", "detail": detail}

        t0 = time.perf_counter()
        meta = extract_metadata(ocr_text, score_metadata=score_metadata)
        dur = int((time.perf_counter() - t0) * 1000)

        piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is None:
            detail = f"Nie znaleziono utworu id={piece_id}."
            self._record_step(
                db,
                piece_id=piece_id,
                key="metadata",
                status="error",
                detail=detail,
                source_file_id=source_file_id,
                duration_ms=dur,
            )
            return {"status": "error", "detail": detail}

        extracted: dict = {}
        applied: list[str] = []
        for src_attr, dest_attr in _METADATA_FIELDS:
            value = (getattr(meta, src_attr, "") or "").strip()
            if value:
                extracted[src_attr] = value
            if value and not (getattr(piece, dest_attr, None) or "").strip():
                setattr(piece, dest_attr, value)
                applied.append(dest_attr)
        db.flush()

        detail = (
            f"Uzupełniono pola: {', '.join(applied)}."
            if applied
            else "Nie znaleziono nowych metadanych do uzupełnienia."
        )
        self._record_step(
            db,
            piece_id=piece_id,
            key="metadata",
            status="ok",
            detail=detail,
            report=(meta.notes or None),
            data={"extracted": extracted, "applied": applied},
            source_file_id=source_file_id,
            duration_ms=dur,
        )
        return {"status": "ok", "detail": detail, "extracted": extracted, "applied": applied}

    def run_step4_correct_score(
        self,
        db: Session,
        piece_id: int,
        xml_path: str,
        *,
        source_file_id: Optional[int] = None,
    ) -> dict:
        """Step 4 — correct an OMR MusicXML file; persist a NEW MusicFile on success."""
        from src.llm.score_corrector import correct_score

        try:
            source_xml = load_musicxml_text(xml_path)
        except Exception as exc:
            logger.exception("run_step4: nie udało się wczytać MusicXML %s", xml_path)
            detail = f"Nie wczytano MusicXML: {exc}"
            self._record_step(
                db,
                piece_id=piece_id,
                key="correct_score",
                status="error",
                detail=detail,
                source_file_id=source_file_id,
            )
            return {"status": "error", "detail": detail}

        context = self._analysis_context(xml_path)
        t0 = time.perf_counter()
        result = correct_score(source_xml, analysis_context=context)
        dur = int((time.perf_counter() - t0) * 1000)

        if not result.changed:
            detail = "Brak zaakceptowanych zmian — zachowano oryginał OMR."
            self._record_step(
                db,
                piece_id=piece_id,
                key="correct_score",
                status="ok",
                detail=detail,
                report=result.report,
                source_file_id=source_file_id,
                duration_ms=dur,
            )
            return {
                "status": "ok",
                "changed": False,
                "report": result.report,
                "musicxml": result.musicxml,
                "detail": detail,
            }

        record = self._save_musicxml(
            db,
            piece_id,
            result.musicxml,
            description="Korekta partytury (LLM) — krok 4",
            prefix="corrected",
            source_path=xml_path,
            score=getattr(result, "score", None),
        )
        detail = "Zapisano poprawiony plik MusicXML."
        self._record_step(
            db,
            piece_id=piece_id,
            key="correct_score",
            status="ok",
            detail=detail,
            report=result.report,
            source_file_id=source_file_id,
            output_file_id=record.id,
            duration_ms=dur,
        )
        return {
            "status": "ok",
            "changed": True,
            "report": result.report,
            "musicxml": result.musicxml,
            "output_file_id": record.id,
            "output_path": record.file_path,
            "detail": detail,
        }

    def run_step5_underlay(
        self,
        db: Session,
        piece_id: int,
        lyrics: str,
        *,
        xml_path: Optional[str] = None,
        xml_content: Optional[str] = None,
        source_file_id: Optional[int] = None,
    ) -> dict:
        """Step 5 — underlay lyrics into the corrected MusicXML; persist a NEW MusicFile."""
        from src.llm.lyric_underlayer import underlay_lyrics

        if not lyrics or not lyrics.strip():
            detail = "Brak oczyszczonego tekstu do podłożenia."
            self._record_step(
                db,
                piece_id=piece_id,
                key="underlay",
                status="skipped",
                detail=detail,
                source_file_id=source_file_id,
            )
            return {"status": "skipped", "detail": detail}

        if xml_content is None:
            if not xml_path:
                detail = "Nie podano pliku MusicXML."
                self._record_step(
                    db,
                    piece_id=piece_id,
                    key="underlay",
                    status="error",
                    detail=detail,
                    source_file_id=source_file_id,
                )
                return {"status": "error", "detail": detail}
            try:
                xml_content = load_musicxml_text(xml_path)
            except Exception as exc:
                logger.exception("run_step5: nie udało się wczytać MusicXML %s", xml_path)
                detail = f"Nie wczytano MusicXML: {exc}"
                self._record_step(
                    db,
                    piece_id=piece_id,
                    key="underlay",
                    status="error",
                    detail=detail,
                    source_file_id=source_file_id,
                )
                return {"status": "error", "detail": detail}

        t0 = time.perf_counter()
        result = underlay_lyrics(lyrics, xml_content)
        dur = int((time.perf_counter() - t0) * 1000)

        if not result.changed:
            detail = "Nie utworzono finalnego pliku — zachowano plik z korekty."
            self._record_step(
                db,
                piece_id=piece_id,
                key="underlay",
                status="ok",
                detail=detail,
                report=result.report,
                source_file_id=source_file_id,
                duration_ms=dur,
            )
            return {
                "status": "ok",
                "changed": False,
                "report": result.report,
                "detail": detail,
            }

        record = self._save_musicxml(
            db,
            piece_id,
            result.musicxml,
            description="Finalny MusicXML z podłożonym tekstem (LLM) — krok 5",
            prefix="final",
            source_path=xml_path or "score.xml",
            score=getattr(result, "score", None),
        )
        detail = "Zapisano finalny plik MusicXML z tekstem."
        self._record_step(
            db,
            piece_id=piece_id,
            key="underlay",
            status="ok",
            detail=detail,
            report=result.report,
            source_file_id=source_file_id,
            output_file_id=record.id,
            duration_ms=dur,
        )
        return {
            "status": "ok",
            "changed": True,
            "report": result.report,
            "output_file_id": record.id,
            "output_path": record.file_path,
            "detail": detail,
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

        Artefacts are threaded between steps in memory; each step is persisted by the method
        that runs it. Each step contributes an entry to the returned ``steps`` list with
        ``status`` ∈ {``ok``, ``skipped``, ``error``}. The caller commits the session.
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
            r1 = self.run_step1_ocr(db, file_id)
            raw_text = r1.get("text", "") or ""
            record(STEP_LABELS["ocr"], {"status": r1["status"], "detail": r1.get("detail", "")})
        except Exception as exc:
            logger.exception("run_full: OCR crashed")
            record(STEP_LABELS["ocr"], {"status": "error", "detail": str(exc)})

        # --- Metadata extraction (LLM) — fills empty piece fields from the OCR header ---
        if not self.llm_available():
            record(STEP_LABELS["metadata"], _llm_unavailable())
        elif not raw_text.strip():
            record(
                STEP_LABELS["metadata"],
                {"status": "skipped", "detail": "Brak tekstu OCR — krok pominięty."},
            )
        else:
            try:
                rm = self.run_step_metadata(db, piece_id, raw_text, source_file_id=file_id)
                record(STEP_LABELS["metadata"], rm)
            except Exception as exc:
                logger.exception("run_full: metadata crashed")
                record(STEP_LABELS["metadata"], {"status": "error", "detail": str(exc)})

        # --- Step 2: clean text (LLM) ---
        clean_lyrics_text = ""
        if not self.llm_available():
            record(STEP_LABELS["clean_text"], _llm_unavailable())
        else:
            try:
                r2 = self.run_step2_clean_text(db, piece_id, raw_text, source_file_id=file_id)
                if r2.get("status") == "ok":
                    clean_lyrics_text = r2.get("lyrics", "") or ""
                record(STEP_LABELS["clean_text"], r2)
            except Exception as exc:
                logger.exception("run_full: step 2 crashed")
                record(STEP_LABELS["clean_text"], {"status": "error", "detail": str(exc)})

        # --- Step 3: OMR (+ analysis) ---
        xml_path: Optional[str] = None
        try:
            r3 = self.run_step3_omr(db, file_id)
            if r3.get("status") == "ok":
                xml_path = r3.get("musicxml_path")
            record(STEP_LABELS["omr"], {"status": r3["status"], "detail": r3.get("detail", "")})
        except Exception as exc:
            logger.exception("run_full: OMR crashed")
            record(STEP_LABELS["omr"], {"status": "error", "detail": str(exc)})

        # --- Step 4: correct score (LLM) ---
        corrected_xml: Optional[str] = None
        if xml_path is None:
            record(
                STEP_LABELS["correct_score"],
                {"status": "skipped", "detail": "Brak MusicXML z OMR — krok pominięty."},
            )
        elif not self.llm_available():
            record(STEP_LABELS["correct_score"], _llm_unavailable())
        else:
            try:
                r4 = self.run_step4_correct_score(db, piece_id, xml_path, source_file_id=file_id)
                corrected_xml = r4.get("musicxml")
                record(STEP_LABELS["correct_score"], r4)
            except Exception as exc:
                logger.exception("run_full: step 4 crashed")
                record(STEP_LABELS["correct_score"], {"status": "error", "detail": str(exc)})

        # --- Step 5: underlay lyrics + validate (LLM) ---
        if corrected_xml is None:
            record(
                STEP_LABELS["underlay"],
                {"status": "skipped", "detail": "Brak poprawionej partytury — krok pominięty."},
            )
        elif not clean_lyrics_text.strip():
            record(
                STEP_LABELS["underlay"],
                {"status": "skipped", "detail": "Brak oczyszczonego tekstu — krok pominięty."},
            )
        elif not self.llm_available():
            record(STEP_LABELS["underlay"], _llm_unavailable())
        else:
            try:
                r5 = self.run_step5_underlay(
                    db,
                    piece_id,
                    clean_lyrics_text,
                    xml_path=xml_path,
                    xml_content=corrected_xml,
                    source_file_id=file_id,
                )
                record(STEP_LABELS["underlay"], r5)
            except Exception as exc:
                logger.exception("run_full: step 5 crashed")
                record(STEP_LABELS["underlay"], {"status": "error", "detail": str(exc)})

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

    def _save_musicxml(
        self,
        db: Session,
        piece_id: int,
        xml_text: str,
        description: str,
        *,
        prefix: str,
        source_path: str,
        score=None,
    ) -> MusicFile:
        """Persist a score as UNCOMPRESSED ``.musicxml`` (inspectable, MuseScore-compatible).

        The canonical output is plain ``.musicxml`` written from a music21 ``Score`` so every
        element can be reviewed/edited and diffed precisely against a reference. When ``score``
        is provided (from a step 4/5 result) it is exported directly; otherwise ``xml_text`` is
        re-parsed. If normalisation fails the raw ``xml_text`` is saved as-is so nothing is lost.

        The file is **versioned** within its ``prefix`` family (``corrected`` / ``final``): the
        next free version number for this piece is computed and recorded on the row and woven
        into the filename together with a creation timestamp, so the download list is
        self-explanatory (which file is which, and which is newest).
        """
        out_text: Optional[str] = None
        try:
            if score is None:
                from music21 import converter

                score = converter.parseData(xml_text, format="musicxml")
            out_text = export_score_to_musicxml(score)
        except Exception:
            logger.warning(
                "pipeline: normalizacja do .musicxml nie powiodła się — zapis surowego XML",
                exc_info=True,
            )
            out_text = xml_text

        kind = _PREFIX_TO_KIND.get(prefix, MusicFileKind.OMR_RAW)
        version = self._next_version(db, piece_id, prefix)
        filename = self._derived_name(source_path, prefix=prefix, version=version)

        # Route through LibraryService when the parent piece exists — this places the
        # artefact under pieces/<id>_<slug>/scores/ or derived/ instead of data/uploads/.
        piece: Optional[MusicPiece] = db.query(MusicPiece).filter(MusicPiece.id == piece_id).first()
        if piece is not None:
            stored_path = FileService.save_uploaded_file(
                piece_id=piece_id,
                filename=filename,
                file_data=out_text.encode("utf-8"),
                use_library=True,
                piece=piece,
                kind=kind,
            )
        else:
            # Fallback: piece disappeared between steps (should not happen in normal flow).
            logger.warning(
                "pipeline: piece_id=%s not found — falling back to legacy upload path", piece_id
            )
            stored_path = FileService.save_uploaded_file(
                piece_id=piece_id,
                filename=filename,
                file_data=out_text.encode("utf-8"),
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
            version=version,
            kind=kind,
        )
        db.add(record)
        db.flush()  # populate record.id
        logger.info(
            "pipeline: zapisano %s (wersja %s) jako file_id=%s", path.name, version, record.id
        )
        return record

    @staticmethod
    def _next_version(db: Session, piece_id: int, prefix: str) -> int:
        """Next free version number for this piece's ``<prefix>_*`` output family (1-based)."""
        existing = (
            db.query(MusicFile)
            .filter(
                MusicFile.music_piece_id == piece_id,
                MusicFile.original_filename.like(f"{prefix}_%"),
            )
            .count()
        )
        return existing + 1

    @staticmethod
    def _derived_name(source_path: str, *, prefix: str, version: int = 1) -> str:
        """Build a ``<prefix>_v<version>_<YYYYmmdd-HHMM>_<stem>.musicxml`` filename.

        Encodes the output family, its version and the creation time directly in the name so a
        downloaded file is identifiable on disk without the database.
        """
        stem = Path(source_path).stem or "score"
        # Strip any earlier pipeline prefix from the stem so names don't accrete (corrected_…).
        for known in ("corrected_", "final_"):
            if stem.startswith(known):
                stem = stem[len(known) :]
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
        return f"{prefix}_v{version}_{stamp}_{stem}.musicxml"


def _analysis_detail(analysis: dict) -> str:
    """One-line summary of the score analysis for the step's ``detail`` field."""
    key = analysis.get("detected_key") or "?"
    voices = analysis.get("voice_count") or "?"
    texture = analysis.get("texture_type") or "?"
    grade = analysis.get("grade_label") or "?"
    return f"Tonacja {key}; głosy: {voices}; faktura: {texture}; trudność: {grade}."


def _llm_unavailable() -> dict:
    return {
        "status": "skipped",
        "detail": "Gemini LLM niedostępny (brak pakietu 'google-genai' lub klucza GEMINI_API_KEY).",
    }
