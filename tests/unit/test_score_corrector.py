"""Unit tests for the step-4 score corrector — exercises the music21 safety gate.

The LLM is mocked, so no network or credentials are needed. The focus is the gate:
a valid corrected document replaces the original; anything that fails music21 validation
(or is missing) leaves the original untouched.
"""

from unittest.mock import MagicMock

from src.llm.score_corrector import correct_score

VALID_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>M</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <note><pitch><step>D</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""

ORIGINAL = VALID_MUSICXML.replace("<step>D</step>", "<step>C</step>")


def _client(reply: str) -> MagicMock:
    client = MagicMock()
    client.complete_text.return_value = reply
    return client


class TestScoreCorrectorGate:
    def test_accepts_valid_corrected_document(self):
        reply = f"## Raport korekt\n- Poprawiono nutę.\n\n```xml\n{VALID_MUSICXML}\n```"
        result = correct_score(ORIGINAL, client=_client(reply))

        assert result.changed is True
        assert "score-partwise" in result.musicxml
        assert "<step>D</step>" in result.musicxml  # the corrected content
        assert "Poprawiono" in result.report

    def test_rejects_invalid_xml_keeps_original(self):
        reply = "## Raport\n- coś\n\n```xml\n<score-partwise><oops></broken\n```"
        result = correct_score(ORIGINAL, client=_client(reply))

        assert result.changed is False
        assert result.musicxml == ORIGINAL  # original preserved
        assert result.validation_error

    def test_missing_xml_block_keeps_original(self):
        reply = "Nie znalazłem błędów do poprawienia."
        result = correct_score(ORIGINAL, client=_client(reply))

        assert result.changed is False
        assert result.musicxml == ORIGINAL
        assert result.validation_error

    def test_analysis_context_is_passed_in_prompt(self):
        client = _client(f"## Raport\n```xml\n{VALID_MUSICXML}\n```")
        correct_score(ORIGINAL, analysis_context="Tonacja: C-dur", client=client)

        _, user_arg = client.complete_text.call_args.args[:2]
        assert "Tonacja: C-dur" in user_arg
