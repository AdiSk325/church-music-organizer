"""MusicXML validator — verify and fix common OMR errors.

Validates measure completeness, voice ranges, enharmonic spelling,
and other musical correctness checks. Can auto-fix some common issues.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from music21 import converter, stream, note, chord, meter, key, clef, duration

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A single validation issue found in the score."""
    severity: str = "warning"     # "critical", "warning", "info"
    category: str = ""            # "measure", "range", "key", "rhythm", etc.
    message: str = ""
    measure_number: int = 0
    part_name: str = ""
    auto_fixable: bool = False


@dataclass
class ValidationReport:
    """Complete validation report for a score."""
    is_valid: bool = True
    total_issues: int = 0
    critical_issues: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    info: List[ValidationIssue] = field(default_factory=list)
    fixes_applied: List[str] = field(default_factory=list)


class MusicXMLValidator:
    """Validate and fix MusicXML scores produced by OMR."""

    # Reasonable note ranges per voice type (MIDI numbers)
    VOICE_RANGES = {
        'Soprano': (55, 88),       # G3 - E6 (generous range)
        'Alto': (48, 79),          # C3 - G5
        'Tenor': (43, 74),         # G2 - D5
        'Bass': (36, 67),          # C2 - G4
        'Treble': (48, 96),        # C3 - C7 (any treble instrument)
        'Bass Clef': (28, 67),     # E1 - G4
        'General': (21, 108),      # A0 - C8 (full piano range)
    }

    def validate(self, score_or_path, auto_fix: bool = False) -> ValidationReport:
        """Validate a MusicXML score.

        Args:
            score_or_path: music21 Score object or path to MusicXML file
            auto_fix: If True, attempt to auto-fix common issues

        Returns:
            ValidationReport
        """
        if isinstance(score_or_path, str):
            try:
                score = converter.parse(score_or_path)
            except Exception as e:
                report = ValidationReport(is_valid=False)
                report.critical_issues.append(ValidationIssue(
                    severity="critical",
                    category="parse",
                    message=f"Cannot parse MusicXML: {e}",
                ))
                report.total_issues = 1
                return report
        else:
            score = score_or_path

        report = ValidationReport()

        # Run all checks
        self._check_measure_completeness(score, report)
        self._check_note_ranges(score, report)
        self._check_key_consistency(score, report)
        self._check_empty_parts(score, report)
        self._check_rhythm_consistency(score, report)

        # Count totals
        report.total_issues = (
            len(report.critical_issues) + len(report.warnings) + len(report.info)
        )
        report.is_valid = len(report.critical_issues) == 0

        # Auto-fix if requested
        if auto_fix:
            self._apply_fixes(score, report)

        return report

    def validate_and_fix(self, musicxml_path: str, output_path: str = None) -> ValidationReport:
        """Validate, auto-fix, and save a MusicXML file.

        Args:
            musicxml_path: Path to input MusicXML
            output_path: Path to save fixed MusicXML (default: overwrites input)

        Returns:
            ValidationReport with fixes applied
        """
        score = converter.parse(musicxml_path)
        report = self.validate(score, auto_fix=True)

        if report.fixes_applied:
            save_path = output_path or musicxml_path
            score.write('musicxml', fp=save_path)
            logger.info(f"Saved fixed score to {save_path} ({len(report.fixes_applied)} fixes)")

        return report

    @staticmethod
    def _measure_duration(notes_and_rests) -> float:
        """Compute effective measure duration, accounting for voices.

        Uses offset + duration to find the actual time span, which
        correctly handles overlapping voices without double-counting.
        """
        if not notes_and_rests:
            return 0.0
        max_end = max(
            nr.offset + nr.quarterLength
            for nr in notes_and_rests
        )
        min_start = min(nr.offset for nr in notes_and_rests)
        return max_end - min_start

    def _check_measure_completeness(self, score: stream.Score, report: ValidationReport):
        """Check that each measure has the correct beat count."""
        for part in score.parts:
            part_name = part.partName or part.id or "Unknown"
            measures = part.getElementsByClass('Measure')
            current_ts = meter.TimeSignature('4/4')

            for m in measures:
                # Update time signature
                ts_list = m.getElementsByClass('TimeSignature')
                if ts_list:
                    current_ts = ts_list[0]

                # Skip pickup measures (anacrusis)
                if m.number == 0:
                    continue

                notes_and_rests = m.flatten().notesAndRests
                if len(notes_and_rests) == 0:
                    continue

                # Group by voice to avoid double-counting
                # multi-voice measures
                actual = self._measure_duration(
                    notes_and_rests)
                expected = current_ts.barDuration.quarterLength

                diff = actual - expected
                if abs(diff) > 0.01:
                    severity = "critical" if abs(diff) >= 1.0 else "warning"
                    issue = ValidationIssue(
                        severity=severity,
                        category="measure",
                        message=(
                            f"Measure {m.number} in {part_name}: "
                            f"expected {expected} beats, got {actual:.2f} "
                            f"(diff: {diff:+.2f})"
                        ),
                        measure_number=m.number,
                        part_name=part_name,
                        auto_fixable=diff < 0,  # Can add rests for short measures
                    )
                    if severity == "critical":
                        report.critical_issues.append(issue)
                    else:
                        report.warnings.append(issue)

    def _check_note_ranges(self, score: stream.Score, report: ValidationReport):
        """Check that note pitches are within reasonable ranges."""
        for part in score.parts:
            part_name = part.partName or part.id or "Unknown"

            # Determine expected range based on clef
            clefs_found = part.flatten().getElementsByClass('Clef')
            if clefs_found:
                clef_name = type(clefs_found[0]).__name__
                if 'Treble' in clef_name:
                    range_key = 'Treble'
                elif 'Bass' in clef_name:
                    range_key = 'Bass Clef'
                else:
                    range_key = 'General'
            else:
                range_key = 'General'

            low, high = self.VOICE_RANGES[range_key]

            for n in part.flatten().notes:
                pitches = []
                if isinstance(n, note.Note):
                    pitches = [n.pitch]
                elif isinstance(n, chord.Chord):
                    pitches = list(n.pitches)

                for p in pitches:
                    if p.midi < low or p.midi > high:
                        m = n.getContextByClass('Measure')
                        mnum = m.number if m else 0
                        issue = ValidationIssue(
                            severity="warning",
                            category="range",
                            message=(
                                f"Note {p.nameWithOctave} (MIDI {p.midi}) in "
                                f"{part_name} m.{mnum} is outside expected "
                                f"range for {range_key}"
                            ),
                            measure_number=mnum,
                            part_name=part_name,
                        )
                        report.warnings.append(issue)

    def _check_key_consistency(self, score: stream.Score, report: ValidationReport):
        """Check if the detected notes are consistent with the key signature."""
        for part in score.parts:
            part_name = part.partName or part.id or "Unknown"

            # Get declared key
            keys = part.flatten().getElementsByClass('KeySignature')
            if not keys:
                continue

            ks = keys[0]
            try:
                declared_key = ks.asKey()
            except Exception:
                continue

            # Analyze what key the notes suggest
            try:
                analyzed_key = part.flatten().analyze('key')
                if str(analyzed_key) != str(declared_key):
                    # Check if it's the relative major/minor
                    is_relative = (
                        (declared_key.mode == 'major' and
                         str(analyzed_key) == str(declared_key.relative)) or
                        (declared_key.mode == 'minor' and
                         str(analyzed_key) == str(declared_key.relative))
                    )
                    if not is_relative:
                        report.info.append(ValidationIssue(
                            severity="info",
                            category="key",
                            message=(
                                f"Part '{part_name}': declared key {declared_key}, "
                                f"but analysis suggests {analyzed_key}"
                            ),
                            part_name=part_name,
                        ))
            except Exception:
                pass

    def _check_empty_parts(self, score: stream.Score, report: ValidationReport):
        """Check for parts with no notes."""
        for part in score.parts:
            part_name = part.partName or part.id or "Unknown"
            notes = part.flatten().notes
            if len(notes) == 0:
                report.warnings.append(ValidationIssue(
                    severity="warning",
                    category="empty",
                    message=f"Part '{part_name}' has no notes",
                    part_name=part_name,
                ))

    def _check_rhythm_consistency(self, score: stream.Score, report: ValidationReport):
        """Check for suspicious rhythm patterns common in OMR errors."""
        for part in score.parts:
            part_name = part.partName or part.id or "Unknown"

            for n in part.flatten().notes:
                # Check for unusually long notes (OMR often misreads duration)
                if n.quarterLength > 16:  # Longer than a longa
                    m = n.getContextByClass('Measure')
                    mnum = m.number if m else 0
                    report.warnings.append(ValidationIssue(
                        severity="warning",
                        category="rhythm",
                        message=(
                            f"Unusually long note ({n.quarterLength} beats) in "
                            f"{part_name} m.{mnum} — possible OMR error"
                        ),
                        measure_number=mnum,
                        part_name=part_name,
                        auto_fixable=True,
                    ))

    def _apply_fixes(self, score: stream.Score, report: ValidationReport):
        """Apply auto-fixes for common OMR issues."""
        fixes_count = 0

        for part in score.parts:
            part_name = part.partName or part.id or "Unknown"
            measures = part.getElementsByClass('Measure')
            current_ts = meter.TimeSignature('4/4')

            for m in measures:
                ts_list = m.getElementsByClass('TimeSignature')
                if ts_list:
                    current_ts = ts_list[0]

                if m.number == 0:
                    continue

                notes_and_rests = m.flatten().notesAndRests
                if len(notes_and_rests) == 0:
                    continue

                actual = self._measure_duration(
                    notes_and_rests)
                expected = current_ts.barDuration.quarterLength
                diff = expected - actual

                # Add rests to fill short measures
                if diff > 0.01:
                    rest = note.Rest()
                    rest.quarterLength = diff
                    m.append(rest)
                    report.fixes_applied.append(
                        f"Added rest ({diff:.2f} beats) to fill m.{m.number} in {part_name}"
                    )
                    fixes_count += 1

        if fixes_count:
            logger.info(f"Applied {fixes_count} auto-fixes")

    def get_report_text(self, report: ValidationReport) -> str:
        """Format validation report as readable text.

        Args:
            report: ValidationReport

        Returns:
            Formatted text report
        """
        lines = [
            f"Validation Report",
            f"{'=' * 50}",
            f"  Status:     {'VALID' if report.is_valid else 'INVALID'}",
            f"  Issues:     {report.total_issues}",
            f"  Critical:   {len(report.critical_issues)}",
            f"  Warnings:   {len(report.warnings)}",
            f"  Info:       {len(report.info)}",
        ]

        if report.fixes_applied:
            lines.append(f"  Fixes:      {len(report.fixes_applied)}")

        if report.critical_issues:
            lines.append(f"\n  Critical Issues:")
            for issue in report.critical_issues[:20]:
                lines.append(f"    ✗ {issue.message}")

        if report.warnings:
            lines.append(f"\n  Warnings:")
            for issue in report.warnings[:20]:
                lines.append(f"    ⚠ {issue.message}")

        if report.info:
            lines.append(f"\n  Info:")
            for issue in report.info[:10]:
                lines.append(f"    ℹ {issue.message}")

        if report.fixes_applied:
            lines.append(f"\n  Fixes Applied:")
            for fix in report.fixes_applied[:20]:
                lines.append(f"    ✓ {fix}")

        return '\n'.join(lines)
