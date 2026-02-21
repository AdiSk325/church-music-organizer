"""Step 10 — Integration tests.

Combines:
- Basic project structure / import / database smoke tests
  (from root test_integration.py)
- OMR pipeline end-to-end tests per test case
  (from root test_boze_moj.py, test_jana_kantego.py, test_psalm_adwent.py)

OMR pipeline tests are marked ``@pytest.mark.slow`` because they invoke
the full OMR engine and may take minutes per case.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def _collect_pitches(part) -> set[int]:
    """Return the set of MIDI pitch numbers present in *part*."""
    pitches: set[int] = set()
    for n in part.flatten().notes:
        if hasattr(n, "pitch"):
            pitches.add(n.pitch.midi)
        elif hasattr(n, "pitches"):
            for p in n.pitches:
                pitches.add(p.midi)
    return pitches


# ===================================================================
# 1. Project structure smoke tests
# ===================================================================


class TestDirectoryStructure:
    """Verify required directories exist."""

    @pytest.mark.parametrize(
        "rel_dir",
        [
            "src",
            "src/database",
            "src/ocr",
            "src/app",
            "data",
            "data/uploads",
            "data/processed",
            "tests",
        ],
    )
    def test_directory_exists(self, rel_dir: str) -> None:
        assert (ROOT / rel_dir).is_dir(), f"Missing directory: {rel_dir}"


class TestRequiredFiles:
    """Verify key source files are present."""

    @pytest.mark.parametrize(
        "rel_file",
        [
            "requirements.txt",
            "README.md",
            "src/database/models.py",
            "src/database/database.py",
            "src/ocr/musicxml_converter.py",
            "src/ocr/score_builder.py",
            "src/ocr/part_definition.py",
            "src/ocr/xml_writer.py",
            "src/app/main.py",
            "tests/test_database.py",
            "tests/test_ocr.py",
        ],
    )
    def test_file_exists(self, rel_file: str) -> None:
        assert (ROOT / rel_file).is_file(), f"Missing file: {rel_file}"


# ===================================================================
# 2. Import smoke tests
# ===================================================================


class TestImports:
    """All public modules must be importable without side effects."""

    def test_database_imports(self) -> None:
        from src.database import init_db, get_db_session, MusicPiece, MusicFile, Tag, FileType  # noqa: F401

    def test_ocr_imports(self) -> None:
        from src.ocr import MusicXMLConverter, ScoreBuilder, PartDefinition  # noqa: F401

    def test_v2_pipeline_imports(self) -> None:
        from src.ocr.text_classifier import TextClassifier, ClassifiedText  # noqa: F401
        from src.ocr.staff_detector import StaffDetector  # noqa: F401
        from src.ocr.staff_splitter import StaffSplitter  # noqa: F401
        from src.ocr.score_builder import ScoreBuilder  # noqa: F401
        from src.ocr.musicxml_validator import MusicXMLValidator  # noqa: F401
        from src.ocr.omr_engine import get_best_available_engine  # noqa: F401


# ===================================================================
# 3. Model / database smoke tests
# ===================================================================


class TestModels:
    """Basic model instantiation."""

    def test_music_piece_creation(self) -> None:
        from src.database.models import MusicPiece

        piece = MusicPiece(title="Test Piece")
        assert piece.title == "Test Piece"

    def test_tag_creation(self) -> None:
        from src.database.models import Tag

        tag = Tag(name="test_tag")
        assert tag.name == "test_tag"

    def test_filetype_enum(self) -> None:
        from src.database.models import FileType

        assert FileType.PDF.value == "pdf"
        assert FileType.MUSESCORE.value == "musescore"
        assert FileType.MUSICXML.value == "musicxml"


class TestDatabase:
    """Database CRUD round-trip with an ephemeral SQLite DB."""

    def test_crud_round_trip(self, tmp_path: Path) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from src.database.database import Base
        from src.database.models import FileType, MusicFile, MusicPiece, Tag

        db_path = tmp_path / "test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        # Create
        session = Session()
        piece = MusicPiece(
            title="Test Hymn",
            composer="Test Composer",
            genre="Hymn",
            key_signature="C major",
        )
        session.add(piece)
        session.commit()
        piece_id = piece.id
        session.close()
        assert piece_id is not None

        # Tag
        session = Session()
        piece = session.query(MusicPiece).get(piece_id)
        piece.tags.append(Tag(name="test"))
        session.commit()
        session.close()

        # File
        session = Session()
        session.add(
            MusicFile(
                music_piece_id=piece_id,
                file_path="/test/path.pdf",
                file_type=FileType.PDF,
                original_filename="test.pdf",
            )
        )
        session.commit()
        session.close()

        # Query
        session = Session()
        pieces = session.query(MusicPiece).all()
        assert len(pieces) == 1
        assert pieces[0].title == "Test Hymn"
        assert len(pieces[0].tags) == 1
        assert len(pieces[0].files) == 1
        session.close()


# ===================================================================
# 4. OMR pipeline end-to-end tests (slow)
# ===================================================================


def _run_omr_pipeline(
    image_path: str,
    output_path: str,
    title: str = "",
    composer: str = "",
) -> str:
    """Run the full v2 OMR pipeline on *image_path* and return the output path."""
    from src.ocr.musicxml_validator import MusicXMLValidator
    from src.ocr.omr_engine import get_best_available_engine
    from src.ocr.score_builder import ScoreBuilder
    from src.ocr.staff_detector import StaffDetector
    from src.ocr.staff_splitter import StaffSplitter
    from src.ocr.text_classifier import ClassifiedText

    # 1. Staff detection
    detector = StaffDetector()
    layout = detector.detect(image_path)

    # 2. Staff splitting
    out_dir = str(Path(output_path).parent / "staves")
    splitter = StaffSplitter(output_dir=out_dir)
    staff_images = splitter.split(image_path, layout)

    # 3. OMR per staff
    engine = get_best_available_engine()
    staff_omr_results = []
    for si in staff_images:
        result = engine.recognize(si["path"])
        if result.success:
            staff_omr_results.append(
                {
                    "path": result.musicxml_path,
                    "staff_indices": si["staff_indices"],
                    "group_type": si["group_type"],
                }
            )

    assert staff_omr_results, "OMR produced no results"

    # 4. Build score
    text_info = ClassifiedText(title=title, composer=composer)
    builder = ScoreBuilder()
    if len(staff_omr_results) >= 2:
        out = builder.build(
            staff_omr_results=staff_omr_results,
            text_info=text_info,
            layout=layout,
            output_path=output_path,
        )
    else:
        out = builder.build_from_single_omr(
            omr_musicxml_path=staff_omr_results[0]["path"],
            text_info=text_info,
            layout=layout,
            output_path=output_path,
        )

    # 5. Validate
    validator = MusicXMLValidator()
    validator.validate_and_fix(out)

    return out


def _compare_scores(actual_path: str, expected_path: str) -> dict:
    """Parse both MusicXML files and return a comparison dict."""
    from music21 import converter

    exp = converter.parse(expected_path)
    act = converter.parse(actual_path)

    result: dict = {
        "expected_parts": len(exp.parts),
        "actual_parts": len(act.parts),
        "parts": [],
    }
    for i in range(min(len(exp.parts), len(act.parts))):
        ep, ap = exp.parts[i], act.parts[i]
        e_measures = list(ep.getElementsByClass("Measure"))
        a_measures = list(ap.getElementsByClass("Measure"))
        e_pitches = _collect_pitches(ep)
        a_pitches = _collect_pitches(ap)
        result["parts"].append(
            {
                "expected_name": ep.partName,
                "actual_name": ap.partName,
                "expected_measures": len(e_measures),
                "actual_measures": len(a_measures),
                "expected_notes": len(list(ep.flatten().notes)),
                "actual_notes": len(list(ap.flatten().notes)),
                "common_pitches": len(e_pitches & a_pitches),
                "only_expected_pitches": e_pitches - a_pitches,
                "only_actual_pitches": a_pitches - e_pitches,
            }
        )
    return result


# --- Boże mój ---

_BOZE_MOJ_IMG = ROOT / "data" / "processed" / "temp" / "boze_moj_test.png"
_BOZE_MOJ_EXPECTED = ROOT / "tests" / "OMR" / "expected_output" / "Boże_mój.musicxml"


@pytest.mark.slow
@pytest.mark.skipif(
    not _BOZE_MOJ_IMG.exists(),
    reason=f"Input image not found: {_BOZE_MOJ_IMG}",
)
@pytest.mark.skipif(
    not _BOZE_MOJ_EXPECTED.exists(),
    reason=f"Expected output not found: {_BOZE_MOJ_EXPECTED}",
)
def test_boze_moj_pipeline(tmp_path: Path) -> None:
    """Run full OMR pipeline on Boże mój and compare with expected output."""
    output = str(tmp_path / "boze_moj_final.musicxml")
    out = _run_omr_pipeline(
        image_path=str(_BOZE_MOJ_IMG),
        output_path=output,
        title="Boże mój",
        composer="m.: J. Sykulski",
    )
    assert Path(out).exists()

    cmp = _compare_scores(out, str(_BOZE_MOJ_EXPECTED))
    assert cmp["actual_parts"] == cmp["expected_parts"]
    for part_cmp in cmp["parts"]:
        # At least some pitch overlap
        assert part_cmp["common_pitches"] > 0, (
            f"Part '{part_cmp['expected_name']}': no pitch overlap"
        )


# --- do Jana Kantego ---

_JANA_KANTEGO_OUTPUT = ROOT / "data" / "processed" / "do Jana Kantego_final.musicxml"
_JANA_KANTEGO_EXPECTED = ROOT / "tests" / "OMR" / "expected_output" / "do Jana Kantego.musicxml"


@pytest.mark.slow
@pytest.mark.skipif(
    not _JANA_KANTEGO_OUTPUT.exists(),
    reason=f"Pipeline output not found: {_JANA_KANTEGO_OUTPUT}",
)
@pytest.mark.skipif(
    not _JANA_KANTEGO_EXPECTED.exists(),
    reason=f"Expected output not found: {_JANA_KANTEGO_EXPECTED}",
)
def test_jana_kantego_comparison() -> None:
    """Compare existing Jana Kantego pipeline output with expected MusicXML."""
    cmp = _compare_scores(str(_JANA_KANTEGO_OUTPUT), str(_JANA_KANTEGO_EXPECTED))
    assert cmp["actual_parts"] == cmp["expected_parts"]
    for part_cmp in cmp["parts"]:
        assert part_cmp["common_pitches"] > 0, (
            f"Part '{part_cmp['expected_name']}': no pitch overlap"
        )


# --- Psalm adwent ---

_PSALM_ADWENT_IMG = ROOT / "data" / "processed" / "temp" / "psalm_adwent.png"
_PSALM_ADWENT_EXPECTED = ROOT / "tests" / "OMR" / "expected_output" / "psalm_adwent.musicxml"


@pytest.mark.slow
@pytest.mark.skipif(
    not _PSALM_ADWENT_IMG.exists(),
    reason=f"Input image not found: {_PSALM_ADWENT_IMG}",
)
@pytest.mark.skipif(
    not _PSALM_ADWENT_EXPECTED.exists(),
    reason=f"Expected output not found: {_PSALM_ADWENT_EXPECTED}",
)
def test_psalm_adwent_pipeline(tmp_path: Path) -> None:
    """Run full OMR pipeline on psalm_adwent and compare with expected output."""
    output = str(tmp_path / "psalm_adwent_final.musicxml")
    out = _run_omr_pipeline(
        image_path=str(_PSALM_ADWENT_IMG),
        output_path=output,
        title="Psalmy responsoryjne",
        composer="m.: ks. K. Pasionek",
    )
    assert Path(out).exists()

    cmp = _compare_scores(out, str(_PSALM_ADWENT_EXPECTED))
    assert cmp["actual_parts"] == cmp["expected_parts"]
    for part_cmp in cmp["parts"]:
        assert part_cmp["common_pitches"] > 0, (
            f"Part '{part_cmp['expected_name']}': no pitch overlap"
        )