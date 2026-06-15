"""Unit tests for the pipeline quality-evaluation harness (src/evaluation).

All data is seeded as ProcessingStep rows (+ a MusicFile.extracted_text for OCR
text quality) in an in-memory SQLite DB — no engines, no LLM, no network.
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, FileType, MusicFile, MusicPiece, ProcessingStep
from src.evaluation.evaluator import evaluate_piece, report_to_markdown
from src.evaluation.metrics import (
    _alpha_ratio,
    _analysis_completeness,
    _parse_syllables_placed,
    compute_musicxml_structure,
)

_VALID_MXL_TEXT = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>M</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions>
      <time><beats>4</beats><beat-type>4</beat-type></time>
      <clef><sign>G</sign><line>2</line></clef></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>"""


class TestComputeMusicXMLStructure:
    def test_empty_text_is_invalid(self):
        m = compute_musicxml_structure(None)
        assert m["valid"] is False
        assert m["note_count"] == 0 and m["part_count"] == 0

    def test_garbage_is_invalid_with_reason(self):
        m = compute_musicxml_structure("<score-partwise><oops></broken")
        assert m["valid"] is False
        assert m["reason"]

    def test_valid_document_counts_structure(self):
        m = compute_musicxml_structure(_VALID_MXL_TEXT)
        assert m["valid"] is True
        assert m["note_count"] == 1
        assert m["part_count"] == 1
        assert m["measure_count"] == 1


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def piece(db_session):
    p = MusicPiece(title="Test")
    db_session.add(p)
    db_session.flush()
    return p


def _step(db, piece_id, key, status="ok", **kw):
    data = kw.pop("data", None)
    row = ProcessingStep(
        music_piece_id=piece_id,
        step_key=key,
        step_label=key,
        status=status,
        data_json=json.dumps(data) if data is not None else None,
        **kw,
    )
    db.add(row)
    db.flush()
    return row


_GOOD_ANALYSIS = {
    "detected_key": "C major",
    "key_confidence": 0.9,
    "mode": "major",
    "time_signatures": ["4/4"],
    "voice_count": 2,
    "voice_names": ["Sopran", "Bas"],
    "measure_count": 32,
    "texture_type": "polyphonic_imitative",
    "harmony_epoch": "renaissance",
    "form_type": "through_composed",
    "text_setting_type": "melismatic",
    "estimated_grade": 4,
    "grade_label": "advanced",
    "voice_ranges": [{"name": "S"}],
    "harmonic_rhythm": "moderate",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_alpha_ratio():
    assert _alpha_ratio("Ave Maria") == 1.0
    assert _alpha_ratio("") == 0.0
    assert _alpha_ratio("=== 4 2 > p") < 0.2  # OCR garbage
    assert 0.4 < _alpha_ratio("ab12") <= 0.5


def test_analysis_completeness_full_vs_empty():
    assert _analysis_completeness(_GOOD_ANALYSIS) == 1.0
    assert _analysis_completeness({}) == 0.0
    sparse = {"detected_key": "unknown", "voice_count": 0, "time_signatures": []}
    assert _analysis_completeness(sparse) == 0.0  # all sentinels/empty


def test_parse_syllables():
    assert _parse_syllables_placed("Podłożono 69 sylab w 2 partii.") == 69
    assert _parse_syllables_placed("Podlozono 5 sylab") == 5  # ASCII fallback
    assert _parse_syllables_placed("brak") is None
    assert _parse_syllables_placed(None) is None


# ---------------------------------------------------------------------------
# evaluate_piece — scenarios
# ---------------------------------------------------------------------------


def test_healthy_full_run_all_ok(db_session, piece):
    src = MusicFile(
        music_piece_id=piece.id,
        file_path="s.pdf",
        file_type=FileType.PDF,
        original_filename="s.pdf",
        extracted_text="Ave Maria gratia plena Dominus tecum benedicta tu",
    )
    db_session.add(src)
    db_session.flush()

    _step(db_session, piece.id, "ocr", data={"confidence": 85, "chars": 50}, source_file_id=src.id)
    _step(db_session, piece.id, "clean_text", data={"language": "la", "lyrics": "Ave Maria"})
    _step(db_session, piece.id, "omr", output_file_id=src.id, duration_ms=70000)
    _step(db_session, piece.id, "analysis", data=_GOOD_ANALYSIS)
    _step(db_session, piece.id, "correct_score", output_file_id=src.id, duration_ms=300000)
    _step(
        db_session, piece.id, "underlay", output_file_id=src.id,
        report="Podłożono 40 sylab w 2 partii.", duration_ms=60000,
    )

    report = evaluate_piece(db_session, piece.id)
    by_key = {s.key: s for s in report.stages}
    assert report.overall_status == "ok"
    assert report.end_to_end_ok is True
    assert by_key["ocr"].status == "ok"
    assert by_key["ocr"].metrics["alpha_ratio"] > 0.8
    assert by_key["analysis"].status == "ok"
    assert by_key["analysis"].metrics["completeness"] == 1.0
    assert by_key["underlay"].metrics["syllables_placed"] == 40
    assert report.stages_ok == report.stages_total == 6


def test_noisy_ocr_flags_fail(db_session, piece):
    src = MusicFile(
        music_piece_id=piece.id,
        file_path="s.pdf",
        file_type=FileType.PDF,
        original_filename="s.pdf",
        extracted_text="=== 4 2 > p | == _ 2 < NE > | 7 |",  # symbol garbage
    )
    db_session.add(src)
    db_session.flush()
    _step(db_session, piece.id, "ocr", data={"confidence": 30, "chars": 20}, source_file_id=src.id)

    report = evaluate_piece(db_session, piece.id)
    ocr = next(s for s in report.stages if s.key == "ocr")
    assert ocr.status == "fail"  # low confidence AND low alpha_ratio
    assert report.overall_status == "fail"


def test_missing_stages_are_missing_not_failed(db_session, piece):
    _step(db_session, piece.id, "ocr", data={"confidence": 80, "chars": 100},
          source_file_id=None)
    report = evaluate_piece(db_session, piece.id)
    by_key = {s.key: s for s in report.stages}
    assert by_key["omr"].status == "missing"
    assert by_key["underlay"].status == "missing"
    # Overall reflects only the present OCR stage.
    assert report.stages_total == 1


def test_low_completeness_analysis_warns(db_session, piece):
    sparse = {"detected_key": "C major", "key_confidence": 0.9, "voice_count": 1,
              "voice_names": ["V"], "time_signatures": ["4/4"]}  # ~5/15 fields
    _step(db_session, piece.id, "analysis", data=sparse)
    report = evaluate_piece(db_session, piece.id)
    analysis = next(s for s in report.stages if s.key == "analysis")
    assert analysis.status in ("warn", "fail")
    assert analysis.metrics["completeness"] < 0.4


def test_engine_only_run_end_to_end_ok(db_session, piece):
    # OMR + analysis ok, LLM stages skipped → end_to_end_ok via condition B.
    src = MusicFile(music_piece_id=piece.id, file_path="x.xml", file_type=FileType.XML,
                    original_filename="x.xml")
    db_session.add(src)
    db_session.flush()
    _step(db_session, piece.id, "omr", output_file_id=src.id)
    _step(db_session, piece.id, "analysis", data=_GOOD_ANALYSIS)
    _step(db_session, piece.id, "clean_text", status="skipped")
    _step(db_session, piece.id, "correct_score", status="skipped")
    _step(db_session, piece.id, "underlay", status="skipped")

    report = evaluate_piece(db_session, piece.id)
    assert report.end_to_end_ok is True


def test_error_status_is_fail(db_session, piece):
    _step(db_session, piece.id, "omr", status="error", detail="Audiveris padł")
    report = evaluate_piece(db_session, piece.id)
    omr = next(s for s in report.stages if s.key == "omr")
    assert omr.status == "fail"


def test_markdown_render_and_unknown_piece(db_session, piece):
    _step(db_session, piece.id, "ocr", data={"confidence": 80, "chars": 10})
    report = evaluate_piece(db_session, piece.id)
    md = report_to_markdown(report)
    assert "Raport jakości" in md and "| Etap |" in md

    with pytest.raises(ValueError):
        evaluate_piece(db_session, 999999)
