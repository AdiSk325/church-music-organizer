"""Unit tests for the step-5 programmatic, per-voice lyric underlay.

The LLM is mocked (it only returns a per-part syllable plan); the focus is that the code
inserts <lyric> elements into real MusicXML via music21, re-exports a valid document, and
keeps the original on any failure.
"""

from unittest.mock import MagicMock

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


# Two vocal parts (SA + TB style), three notes each — to prove EVERY part gets lyrics.
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


def _client(*syllables) -> MagicMock:
    """Mock client whose every parse() returns a PartSyllables with the given onsets."""
    client = MagicMock()
    client.parse.return_value = PartSyllables(syllables=list(syllables), notes="test")
    return client


class TestProgrammaticUnderlay:
    def test_inserts_lyrics_and_validates(self):
        client = _client(
            OnsetSyllable(text="A", syllabic="begin"),
            OnsetSyllable(text="ve", syllabic="end"),
            OnsetSyllable(text="Ma", syllabic="single"),
        )
        result = underlay_lyrics("Ave Ma", THREE_NOTE_XML, client=client)

        assert result.changed is True
        assert "<lyric" in result.musicxml
        assert "ve" in result.musicxml and "Ma" in result.musicxml
        assert result.validation_error is None
        # One LLM call per vocal part (one part here).
        assert client.parse.call_count == 1

    def test_melisma_empty_text_is_skipped(self):
        # Second note is a melisma continuation (empty) — only two syllables placed.
        client = _client(
            OnsetSyllable(text="A", syllabic="begin"),
            OnsetSyllable(text="", syllabic="single"),
            OnsetSyllable(text="men", syllabic="end"),
        )
        result = underlay_lyrics("Amen", THREE_NOTE_XML, client=client)

        assert result.changed is True
        assert "Podłożono 2 sylab" in result.report

    def test_no_syllables_keeps_original(self):
        client = _client(OnsetSyllable(text="", syllabic="single"))
        result = underlay_lyrics("x", THREE_NOTE_XML, client=client)

        assert result.changed is False
        assert result.musicxml == THREE_NOTE_XML
        assert result.validation_error

    def test_fills_every_vocal_part(self):
        # The mock returns plenty of syllables for each part; both parts must get lyrics
        # (regression: the old single-call design left all but the first part empty).
        client = _client(
            OnsetSyllable(text="la", syllabic="single"),
            OnsetSyllable(text="la", syllabic="single"),
            OnsetSyllable(text="la", syllabic="single"),
        )
        result = underlay_lyrics("la la la", TWO_PART_XML, client=client)

        assert result.changed is True
        assert client.parse.call_count == 2  # one alignment call per vocal part

        from music21 import converter

        score = converter.parseData(result.musicxml, format="musicxml")
        per_part = [
            sum(1 for n in p.recurse().notes if n.lyrics) for p in score.parts
        ]
        assert per_part == [3, 3]  # BOTH parts fully texted

    def test_unparseable_input_keeps_original(self):
        client = MagicMock()
        result = underlay_lyrics("x", "<not-music-xml>", client=client)

        assert result.changed is False
        assert result.musicxml == "<not-music-xml>"
        client.parse.assert_not_called()  # never reached the LLM
