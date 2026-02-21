"""LLM repair tool for local corrections on a ScoreGraph.

The LLM is used *only* as a localised repair tool, not as a primary
reconstruction engine.  It receives a specific measure, the list of constraint
violations found for that measure, and an optional musical context (surrounding
measures), and returns a suggested corrected measure.

When no LLM API key is available the tool falls back to simple heuristic
repairs (clamp out-of-range pitches, trim/pad durations to match time sig).
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from .constraints import ConstraintViolation
from .score_graph import Measure, Note, Voice, VoiceType

logger = logging.getLogger(__name__)


class LLMRepairTool:
    """Applies localised repairs to measures that violate music-theory constraints.

    When an OpenAI-compatible API key is present the tool can delegate to an
    LLM for context-aware suggestions.  Otherwise, a deterministic heuristic
    fallback is used so the pipeline remains functional without any external
    service.

    Args:
        api_key: OpenAI (or compatible) API key.  If ``None`` the key is read
                 from the ``OPENAI_API_KEY`` environment variable.
        model:   LLM model identifier to use for repair prompts.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self._client = None  # lazy-initialised in _get_client()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return ``True`` if an LLM API key is configured."""
        return bool(self.api_key)

    def repair_measure(
        self,
        measure: Measure,
        violations: List[ConstraintViolation],
        context: Optional[List[Measure]] = None,
    ) -> Measure:
        """Return a repaired copy of *measure* addressing the given *violations*.

        If the LLM is unavailable the heuristic fallback is used transparently.

        Args:
            measure:    The measure to repair.
            violations: Violations found in this measure by the
                        :class:`~src.omr.constraints.ConstraintEngine`.
            context:    Optional neighbouring measures for musical context.

        Returns:
            A new :class:`~src.omr.score_graph.Measure` with repairs applied.
        """
        if self.is_available():
            try:
                return self._llm_repair(measure, violations, context)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM repair failed (%s); falling back to heuristics.", exc)

        return self._heuristic_repair(measure, violations)

    # -----------------------------------------------------------------------
    # LLM-based repair (requires API key)
    # -----------------------------------------------------------------------

    def _get_client(self):
        """Lazy-initialise and return the OpenAI client."""
        if self._client is None:
            try:
                import openai  # type: ignore[import]

                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError as exc:
                raise RuntimeError(
                    "The 'openai' package is required for LLM repair. "
                    "Install it with: pip install openai"
                ) from exc
        return self._client

    def _build_prompt(
        self,
        measure: Measure,
        violations: List[ConstraintViolation],
        context: Optional[List[Measure]],
    ) -> str:
        violation_text = "\n".join(f"- {v.description}" for v in violations)
        notes_text = "\n".join(
            f"  Voice {n.voice_id}: pitch={n.pitch}, duration={n.duration}, onset={n.onset}"
            for n in measure.all_notes()
        )
        return (
            f"You are a music engraving assistant correcting an OMR error.\n\n"
            f"Measure {measure.number} (time sig {measure.time_signature}) contains "
            f"the following constraint violations:\n{violation_text}\n\n"
            f"Current notes:\n{notes_text}\n\n"
            "Reply with a JSON array of corrected notes, each with keys: "
            "'pitch', 'duration', 'onset', 'voice_id'. "
            "Fix only the violations; preserve everything else."
        )

    def _llm_repair(
        self,
        measure: Measure,
        violations: List[ConstraintViolation],
        context: Optional[List[Measure]],
    ) -> Measure:
        import json

        client = self._get_client()
        prompt = self._build_prompt(measure, violations, context)

        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = response.choices[0].message.content

        # Parse the JSON array of notes
        try:
            note_dicts = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON array from the response text
            import re

            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                note_dicts = json.loads(match.group())
            else:
                raise ValueError("LLM did not return valid JSON.")

        # Rebuild measure voices from the corrected notes
        return self._notes_to_measure(measure, note_dicts)

    # -----------------------------------------------------------------------
    # Heuristic fallback
    # -----------------------------------------------------------------------

    def _heuristic_repair(
        self,
        measure: Measure,
        violations: List[ConstraintViolation],
    ) -> Measure:
        """Apply rule-based heuristics to fix common constraint violations.

        Heuristics applied:
        1. **Duration overflow** – truncate the last note in a voice so the
           total duration equals the expected duration.
        2. **Duration underflow** – append a rest to fill the remaining space.
        3. **Out-of-range pitch** – clamp the pitch to the nearest boundary of
           the valid range for the assigned voice type.
        """
        from .score_graph import VOICE_RANGES

        expected = measure.expected_duration()
        repaired_voices: List[Voice] = []

        for voice in measure.voices:
            notes = list(voice.notes)

            # --- Duration fix ---
            total = sum(n.duration for n in notes)
            if abs(total - expected) > 0.01:
                if total > expected:
                    # Truncate last note
                    excess = total - expected
                    if notes:
                        last = notes[-1]
                        new_duration = max(0.0, last.duration - excess)
                        notes[-1] = Note(
                            pitch=last.pitch,
                            duration=new_duration,
                            onset=last.onset,
                            voice_id=last.voice_id,
                        )
                else:
                    # Append a rest to fill remaining duration
                    remaining = expected - total
                    last_onset = notes[-1].onset + notes[-1].duration if notes else 0.0
                    notes.append(
                        Note(
                            pitch="R",
                            duration=remaining,
                            onset=last_onset,
                            voice_id=voice.voice_id,
                        )
                    )

            # --- Pitch range fix (clamp) ---
            if voice.voice_type in VOICE_RANGES:
                low, high = VOICE_RANGES[voice.voice_type]
                clamped_notes: List[Note] = []
                for note in notes:
                    if note.is_rest or note.midi is None:
                        clamped_notes.append(note)
                        continue
                    midi = note.midi
                    if low <= midi <= high:
                        clamped_notes.append(note)
                    else:
                        # Move by octaves until within range
                        while midi < low:
                            midi += 12
                        while midi > high:
                            midi -= 12
                        new_pitch = _midi_to_pitch_string(midi)
                        clamped_notes.append(
                            Note(
                                pitch=new_pitch,
                                duration=note.duration,
                                onset=note.onset,
                                voice_id=note.voice_id,
                            )
                        )
                notes = clamped_notes

            repaired_voices.append(
                Voice(
                    voice_id=voice.voice_id,
                    voice_type=voice.voice_type,
                    notes=notes,
                )
            )

        return Measure(
            number=measure.number,
            time_signature=measure.time_signature,
            voices=repaired_voices,
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _notes_to_measure(original: Measure, note_dicts: list) -> Measure:
        """Reconstruct a ``Measure`` from a list of note dictionaries."""
        voices_map: Dict[int, Voice] = {v.voice_id: v for v in original.voices}
        new_notes_map: Dict[int, List[Note]] = {vid: [] for vid in voices_map}

        for nd in note_dicts:
            vid = nd.get("voice_id", 0)
            if vid not in new_notes_map:
                new_notes_map[vid] = []
            new_notes_map[vid].append(
                Note(
                    pitch=str(nd.get("pitch", "R")),
                    duration=float(nd.get("duration", 1.0)),
                    onset=float(nd.get("onset", 0.0)),
                    voice_id=vid,
                )
            )

        repaired_voices = [
            Voice(
                voice_id=vid,
                voice_type=voices_map[vid].voice_type if vid in voices_map else VoiceType.UNASSIGNED,
                notes=sorted(notes, key=lambda n: n.onset),
            )
            for vid, notes in new_notes_map.items()
        ]
        return Measure(
            number=original.number,
            time_signature=original.time_signature,
            voices=repaired_voices,
        )


def _midi_to_pitch_string(midi: int) -> str:
    """Convert a MIDI note number to a pitch string like ``'C4'``."""
    _NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = (midi // 12) - 1
    name = _NAMES[midi % 12]
    return f"{name}{octave}"
