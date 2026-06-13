"""Unit tests for the MusicXML validation / loading helpers."""

import zipfile

from src.llm.musicxml_validate import load_musicxml_text, validate_musicxml

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
        ok, error = validate_musicxml(VALID_MUSICXML)
        assert ok is True
        assert error is None

    def test_empty_string_fails(self):
        ok, error = validate_musicxml("")
        assert ok is False
        assert error

    def test_garbage_fails(self):
        ok, error = validate_musicxml("<score-partwise><oops></broken")
        assert ok is False
        assert error

    def test_parses_but_no_notes_fails(self):
        empty = (
            '<?xml version="1.0"?><score-partwise version="3.1">'
            '<part-list><score-part id="P1"><part-name>M</part-name></score-part>'
            '</part-list><part id="P1"><measure number="1">'
            "<attributes><divisions>1</divisions></attributes></measure></part>"
            "</score-partwise>"
        )
        ok, error = validate_musicxml(empty)
        assert ok is False
        assert "nut" in error.lower()


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
