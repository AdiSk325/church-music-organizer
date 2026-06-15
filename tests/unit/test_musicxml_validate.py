"""Unit tests for the MusicXML validation / loading helpers."""

import zipfile

from src.llm.musicxml_validate import (
    export_score_to_mxl,
    load_musicxml_text,
    validate_musicxml,
)

# Minimal but valid MusicXML with a single note (no external DTD to avoid network).
VALID_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Music</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


class TestValidateMusicXML:
    def test_valid_document_passes(self):
        ok, error, score = validate_musicxml(VALID_MUSICXML)
        assert ok is True
        assert error is None
        assert score is not None

    def test_empty_string_fails(self):
        ok, error, score = validate_musicxml("")
        assert ok is False
        assert error
        assert score is None

    def test_garbage_fails(self):
        ok, error, score = validate_musicxml("<score-partwise><oops></broken")
        assert ok is False
        assert error
        assert score is None

    def test_parses_but_no_notes_fails(self):
        empty = (
            '<?xml version="1.0"?><score-partwise version="3.1">'
            '<part-list><score-part id="P1"><part-name>M</part-name></score-part>'
            '</part-list><part id="P1"><measure number="1">'
            "<attributes><divisions>1</divisions></attributes></measure></part>"
            "</score-partwise>"
        )
        ok, error, score = validate_musicxml(empty)
        assert ok is False
        assert "nut" in error.lower()
        assert score is None

    def test_missing_divisions_fails(self):
        # Like VALID_MUSICXML but without the <divisions> declaration MuseScore needs.
        no_div = VALID_MUSICXML.replace("<divisions>1</divisions>", "")
        ok, error, score = validate_musicxml(no_div)
        assert ok is False
        assert "divisions" in error.lower()
        assert score is None

    def test_overfull_measure_is_valid_with_warning(self):
        # Measure 2 in 4/4 holds six quarter notes (6 > 4). Audiveris produces such bars
        # and MuseScore still IMPORTS them, so validation must NOT reject — only warn.
        notes = (
            "<note><pitch><step>C</step><octave>4</octave></pitch>"
            "<duration>1</duration><type>quarter</type></note>"
        ) * 6
        overfull = (
            '<?xml version="1.0"?><score-partwise version="3.1">'
            '<part-list><score-part id="P1"><part-name>M</part-name></score-part></part-list>'
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>1</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time>"
            "<clef><sign>G</sign><line>2</line></clef></attributes>"
            "<note><pitch><step>C</step><octave>4</octave></pitch>"
            "<duration>4</duration><type>whole</type></note></measure>"
            f'<measure number="2">{notes}</measure>'
            "</part></score-partwise>"
        )
        ok, error, score = validate_musicxml(overfull)
        assert ok is True  # overfull bars are tolerated (MuseScore imports them)
        assert error is None
        assert score is not None


class TestExportScoreToMxl:
    def test_exports_valid_zip_preserving_notes(self):
        ok, _err, score = validate_musicxml(VALID_MUSICXML)
        assert ok and score is not None
        n0 = len(list(score.recurse().notes))

        mxl = export_score_to_mxl(score)
        assert isinstance(mxl, bytes)
        assert mxl[:2] == b"PK"  # compressed .mxl is a ZIP archive

        # Round-trips back through the loader/validator with the same note count.
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mktemp(suffix=".mxl"))
        tmp.write_bytes(mxl)
        try:
            ok2, _err2, score2 = validate_musicxml(load_musicxml_text(str(tmp)))
            assert ok2
            assert len(list(score2.recurse().notes)) == n0
        finally:
            tmp.unlink(missing_ok=True)


class TestLoadMusicXMLText:
    def test_reads_plain_xml(self, tmp_path):
        f = tmp_path / "score.xml"
        f.write_text(VALID_MUSICXML, encoding="utf-8")
        assert "score-partwise" in load_musicxml_text(str(f))

    def test_decompresses_mxl_via_container(self, tmp_path):
        f = tmp_path / "score.mxl"
        container = (
            '<?xml version="1.0"?><container><rootfiles>'
            '<rootfile full-path="score.xml"/></rootfiles></container>'
        )
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("META-INF/container.xml", container)
            zf.writestr("score.xml", VALID_MUSICXML)

        text = load_musicxml_text(str(f))
        assert "score-partwise" in text

    def test_decompresses_mxl_without_container_manifest(self, tmp_path):
        f = tmp_path / "score.mxl"
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("anything.xml", VALID_MUSICXML)

        text = load_musicxml_text(str(f))
        assert "score-partwise" in text
