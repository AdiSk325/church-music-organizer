"""Unit tests for the step-5 programmatic lyric underlay.

The LLM is mocked (it only returns a syllable-per-onset plan); the focus is that the code
inserts <lyric> elements into real MusicXML via music21, re-exports a valid document, and
keeps the original on any failure.
"""

from unittest.mock import MagicMock

from src.llm.lyric_underlayer import OnsetSyllable, PartUnderlay, UnderlayPlan, underlay_lyrics

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


def _client(plan: UnderlayPlan) -> MagicMock:
    client = MagicMock()
    client.parse.return_value = plan
    return client


def _plan(*syllables) -> UnderlayPlan:
    return UnderlayPlan(
        parts=[PartUnderlay(part_index=0, syllables=list(syllables))],
        notes="test",
    )


class TestProgrammaticUnderlay:
    def test_inserts_lyrics_and_validates(self):
        plan = _plan(
            OnsetSyllable(text="A", syllabic="begin"),
            OnsetSyllable(text="ve", syllabic="end"),
            OnsetSyllable(text="Ma", syllabic="single"),
        )
        result = underlay_lyrics("Ave Ma", THREE_NOTE_XML, client=_client(plan))

        assert result.changed is True
        assert "<lyric" in result.musicxml
        assert "ve" in result.musicxml and "Ma" in result.musicxml
        # The plan is built from the real onsets, not by regenerating XML.
        assert result.validation_error is None

    def test_melisma_empty_text_is_skipped(self):
        # Second note is a melisma continuation (empty) — only two syllables placed.
        plan = _plan(
            OnsetSyllable(text="A", syllabic="begin"),
            OnsetSyllable(text="", syllabic="single"),
            OnsetSyllable(text="men", syllabic="end"),
        )
        result = underlay_lyrics("Amen", THREE_NOTE_XML, client=_client(plan))

        assert result.changed is True
        assert "Podłożono 2 sylab" in result.report

    def test_no_syllables_keeps_original(self):
        plan = _plan(OnsetSyllable(text="", syllabic="single"))
        result = underlay_lyrics("x", THREE_NOTE_XML, client=_client(plan))

        assert result.changed is False
        assert result.musicxml == THREE_NOTE_XML
        assert result.validation_error

    def test_unparseable_input_keeps_original(self):
        client = MagicMock()
        result = underlay_lyrics("x", "<not-music-xml>", client=client)

        assert result.changed is False
        assert result.musicxml == "<not-music-xml>"
        client.parse.assert_not_called()  # never reached the LLM
