"""Unit tests for ProcessingStep persistence and ProcessingStepService reads."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, MusicPiece, ProcessingStep
from src.services.pipeline_service import STEP_LABELS, PipelineService
from src.services.processing_step_service import ProcessingStepService


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


def test_record_step_persists_row_and_payload(db_session, piece):
    svc = PipelineService()
    step = svc._record_step(
        db_session,
        piece_id=piece.id,
        key="ocr",
        status="ok",
        detail="Pewność 80%",
        data={"confidence": 80, "chars": 120},
        duration_ms=42,
    )
    assert step is not None and step.id

    row = db_session.query(ProcessingStep).one()
    assert row.step_key == "ocr"
    assert row.status == "ok"
    assert row.step_label == STEP_LABELS["ocr"]  # default label resolved from the key
    assert row.duration_ms == 42
    assert json.loads(row.data_json) == {"confidence": 80, "chars": 120}


def test_record_step_without_piece_is_noop(db_session):
    assert PipelineService()._record_step(db_session, piece_id=None, key="ocr", status="ok") is None
    assert db_session.query(ProcessingStep).count() == 0


def test_latest_by_key_returns_newest_per_key(db_session, piece):
    svc = PipelineService()
    svc._record_step(db_session, piece_id=piece.id, key="clean_text", status="error", detail="old")
    svc._record_step(db_session, piece_id=piece.id, key="clean_text", status="ok", detail="new")
    svc._record_step(db_session, piece_id=piece.id, key="omr", status="ok", detail="omr")

    latest = ProcessingStepService.latest_by_key(db_session, piece.id)
    assert set(latest) == {"clean_text", "omr"}
    assert latest["clean_text"].status == "ok"
    assert latest["clean_text"].detail == "new"  # the later row wins


def test_history_returns_all_runs_newest_first(db_session, piece):
    svc = PipelineService()
    svc._record_step(db_session, piece_id=piece.id, key="correct_score", status="error", detail="a")
    svc._record_step(db_session, piece_id=piece.id, key="correct_score", status="ok", detail="b")

    hist = ProcessingStepService.history(db_session, piece.id, "correct_score")
    assert [h.detail for h in hist] == ["b", "a"]


def test_data_decodes_and_tolerates_garbage(db_session, piece):
    good = PipelineService()._record_step(
        db_session, piece_id=piece.id, key="analysis", status="ok", data={"k": 1}
    )
    assert ProcessingStepService.data(good) == {"k": 1}
    assert ProcessingStepService.data(None) is None

    good.data_json = "{not json"
    assert ProcessingStepService.data(good) is None


def test_cascade_delete_removes_steps(db_session, piece):
    PipelineService()._record_step(db_session, piece_id=piece.id, key="ocr", status="ok")
    db_session.flush()
    db_session.delete(db_session.get(MusicPiece, piece.id))
    db_session.flush()
    assert db_session.query(ProcessingStep).count() == 0
