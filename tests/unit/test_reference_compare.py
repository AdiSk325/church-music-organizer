"""Unit tests for reference-based score comparison."""

from src.evaluation.reference_compare import compare_musicxml

_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>M</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions>
        <key><fifths>-1</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>D</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_identical_scores_score_perfectly(tmp_path):
    ref = tmp_path / "ref.musicxml"
    cand = tmp_path / "cand.xml"
    ref.write_text(_SCORE, encoding="utf-8")
    cand.write_text(_SCORE, encoding="utf-8")

    m = compare_musicxml(str(ref), str(cand))
    assert "error" not in m
    assert m["valid_musicxml"] is True
    assert m["note_recall"] == 1.0
    assert m["measure_match"] is True
    assert m["key_match"] is True  # both -1 fifths
    assert m["ts_match"] is True
    assert m["part_match"] is True
    assert m["overall_score"] == 1.0


def test_missing_key_equals_zero_fifths(tmp_path):
    ref = tmp_path / "ref.musicxml"
    cand = tmp_path / "cand.xml"
    # reference with no accidentals (0 fifths) ...
    ref.write_text(_SCORE.replace("<fifths>-1</fifths>", "<fifths>0</fifths>"), encoding="utf-8")
    # ... candidate with the whole <key> element removed → None ≡ 0
    cand.write_text(_SCORE.replace("<key><fifths>-1</fifths></key>", ""), encoding="utf-8")

    m = compare_musicxml(str(ref), str(cand))
    assert m["key_match"] is True
