"""Unit tests for the step-5 underlay: algorithmic by default, LLM only on low confidence.

The LLM client is always a mock; tests assert WHEN it is (not) called and that lyrics land in
real MusicXML via music21 with a valid round-trip.
"""

from unittest.mock import MagicMock

import pytest

from src.llm.lyric_underlayer import OnsetSyllable, PartSyllables, underlay_lyrics

# A minimal but real one-part score with three notes.
THREE_NOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>S</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>3</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


# Two vocal parts (SA + TB style), three notes each.
TWO_PART_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>S</part-name></score-part>
    <score-part id="P2"><part-name>B</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>3</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>3</beats><beat-type>4</beat-type></time>
        <clef><sign>F</sign><line>4</line></clef></attributes>
      <note><pitch><step>C</step><octave>3</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>3</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>3</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


@pytest.fixture(autouse=True)
def _clear_backend_env(monkeypatch):
    """Default to the auto backend regardless of the developer's shell environment."""
    monkeypatch.delenv("CMO_UNDERLAY_BACKEND", raising=False)
    monkeypatch.delenv("CMO_UNDERLAY_LLM_THRESHOLD", raising=False)


def _llm_client(*syllables) -> MagicMock:
    client = MagicMock()
    client.parse.return_value = PartSyllables(syllables=list(syllables), notes="test")
    return client


def _lyric_count(musicxml: str) -> list:
    from music21 import converter

    score = converter.parseData(musicxml, format="musicxml")
    return [sum(1 for n in p.recurse().notes if n.lyrics) for p in score.parts]


class TestUnderlay:
    def test_algorithmic_when_counts_match_no_llm(self):
        # "Ave Ma" → A-ve + Ma = 3 syllables over 3 notes → confidence 1.0 → no LLM.
        client = _llm_client()
        result = underlay_lyrics("Ave Ma", THREE_NOTE_XML, client=client)

        assert result.changed is True
        assert "<lyric" in result.musicxml
        assert _lyric_count(result.musicxml) == [3]
        client.parse.assert_not_called()

    def test_fills_every_vocal_part_algorithmically(self):
        client = _llm_client()
        result = underlay_lyrics("la la la", TWO_PART_XML, client=client)

        assert result.changed is True
        assert _lyric_count(result.musicxml) == [3, 3]
        client.parse.assert_not_called()

    def test_more_notes_than_syllables_makes_melisma_algo_only(self, monkeypatch):
        monkeypatch.setenv("CMO_UNDERLAY_BACKEND", "algo")  # never escalate
        client = _llm_client()
        result = underlay_lyrics("A", THREE_NOTE_XML, client=client)

        assert result.changed is True
        assert "Podłożono 1 sylab" in result.report
        assert _lyric_count(result.musicxml) == [1]  # one syllable, two melisma notes
        client.parse.assert_not_called()

    def test_low_confidence_escalates_to_llm(self):
        # 1 syllable over 3 notes → confidence < 0.6 → LLM redoes the part.
        client = _llm_client(
            OnsetSyllable(text="A", syllabic="begin"),
            OnsetSyllable(text="", syllabic="single"),
            OnsetSyllable(text="men", syllabic="end"),
        )
        result = underlay_lyrics("A", THREE_NOTE_XML, client=client)

        assert result.changed is True
        client.parse.assert_called_once()
        assert _lyric_count(result.musicxml) == [2]  # from the LLM plan

    def test_forced_llm_backend_always_calls(self, monkeypatch):
        monkeypatch.setenv("CMO_UNDERLAY_BACKEND", "llm")
        client = _llm_client(
            OnsetSyllable(text="la", syllabic="single"),
            OnsetSyllable(text="la", syllabic="single"),
            OnsetSyllable(text="la", syllabic="single"),
        )
        result = underlay_lyrics("la la la", THREE_NOTE_XML, client=client)

        assert result.changed is True
        client.parse.assert_called_once()

    def test_llm_failure_falls_back_to_algorithm(self):
        # Non-transient error → no retry → immediate fallback to the algorithmic placement.
        client = MagicMock()
        client.parse.side_effect = RuntimeError("claude CLI zwrócił kod 1: brak dostępu")
        result = underlay_lyrics("A", THREE_NOTE_XML, client=client)  # low conf → tries LLM

        assert result.changed is True  # fell back to the algorithmic placement
        client.parse.assert_called_once()
        assert _lyric_count(result.musicxml) == [1]

    def test_no_syllables_keeps_original(self):
        client = MagicMock()
        result = underlay_lyrics("--- 123 !!!", THREE_NOTE_XML, client=client)

        assert result.changed is False
        assert result.musicxml == THREE_NOTE_XML
        client.parse.assert_not_called()

    def test_unparseable_input_keeps_original(self):
        client = MagicMock()
        result = underlay_lyrics("la", "<not-music-xml>", client=client)

        assert result.changed is False
        assert result.musicxml == "<not-music-xml>"
        client.parse.assert_not_called()
