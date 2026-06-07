"""PDF → MusicXML conversion via Audiveris (OMR).

Audiveris is a Java-based OMR engine.  This module wraps it as a subprocess.
Audiveris must be installed and on PATH (or AUDIVERIS_JAR env var must point
to the jar file).  See docs/knowledge/installation.md for setup instructions.

Typical usage:
    converter = PdfToMusicXml()
    xml_path = converter.convert("scan.pdf", output_dir="data/processed")
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audiveris discovery
# ---------------------------------------------------------------------------

def _find_audiveris() -> Optional[str]:
    """Return path to the audiveris executable or jar, or None if not found."""
    # 1. Check AUDIVERIS_JAR env var (path to the fat jar)
    jar_env = os.environ.get("AUDIVERIS_JAR")
    if jar_env and Path(jar_env).exists():
        return jar_env

    # 2. Check if 'audiveris' command is on PATH
    if shutil.which("audiveris"):
        return "audiveris"

    # 3. Common installation locations
    candidates = [
        Path.home() / "Audiveris" / "bin" / "Audiveris",
        Path("/opt/audiveris/bin/Audiveris"),
        Path("/usr/local/bin/audiveris"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    return None


def _audiveris_available() -> bool:
    return _find_audiveris() is not None


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

class PdfToMusicXml:
    """Convert a PDF (or image) score to MusicXML using Audiveris OMR."""

    def __init__(self, audiveris_path: Optional[str] = None):
        self._exe = audiveris_path or _find_audiveris()

    @property
    def is_available(self) -> bool:
        return self._exe is not None

    def convert(
        self,
        input_path: str,
        output_dir: str = "data/processed",
        timeout: int = 300,
    ) -> Optional[str]:
        """Convert *input_path* (PDF/PNG/TIFF) to MusicXML.

        Returns the path of the generated .mxl file, or None on failure.

        Args:
            input_path: Path to the source PDF or image file.
            output_dir: Directory where the output .mxl will be written.
            timeout: Maximum seconds to wait for Audiveris (default 5 minutes).
        """
        if not self._exe:
            raise RuntimeError(
                "Audiveris not found. Install it from https://audiveris.github.io "
                "or set the AUDIVERIS_JAR environment variable."
            )

        src = Path(input_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Input file not found: {src}")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Audiveris writes output to a subdirectory named after the input file
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cmd = self._build_command(str(src), tmp)
            logger.info("Running Audiveris: %s", " ".join(cmd))

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                logger.error("Audiveris timed out after %ds for %s", timeout, src.name)
                return None

            if result.returncode != 0:
                logger.error(
                    "Audiveris failed (exit %d):\n%s", result.returncode, result.stderr[:2000]
                )
                return None

            # Locate output .mxl file produced by Audiveris
            mxl_files = list(tmp_path.rglob("*.mxl"))
            if not mxl_files:
                # Try uncompressed .xml fallback
                xml_files = list(tmp_path.rglob("*.xml"))
                if xml_files:
                    mxl_files = xml_files

            if not mxl_files:
                logger.error("Audiveris produced no output file for %s", src.name)
                logger.debug("Audiveris stdout:\n%s", result.stdout[:2000])
                return None

            # Move the first result to output_dir
            out_file = mxl_files[0]
            dest = out_dir / out_file.name
            shutil.move(str(out_file), str(dest))
            logger.info("MusicXML written to %s", dest)
            return str(dest)

    def _build_command(self, input_path: str, output_dir: str) -> list:
        exe = self._exe or "audiveris"

        if exe.endswith(".jar"):
            # Running via fat jar: java -jar audiveris.jar
            return [
                "java", "-jar", exe,
                "-batch",
                "-export",
                "-output", output_dir,
                "--", input_path,
            ]
        else:
            # Running via wrapper script or binary
            return [
                exe,
                "-batch",
                "-export",
                "-output", output_dir,
                "--", input_path,
            ]

    def conversion_quality_report(
        self,
        original_xml: str,
        converted_xml: str,
    ) -> dict:
        """Compare an original MusicXML against an Audiveris conversion.

        Returns a dict with quality metrics:
          note_count_original, note_count_converted, note_recall,
          measure_count_original, measure_count_converted,
          key_match, time_signature_match, voice_count_match,
          overall_score (0.0–1.0)
        """
        try:
            from music21 import converter as m21converter
            orig = m21converter.parse(original_xml)
            conv = m21converter.parse(converted_xml)
        except Exception as exc:
            return {"error": str(exc)}

        def _note_count(score) -> int:
            return sum(1 for n in score.flatten().notes)

        def _measure_count(score) -> int:
            parts = list(score.parts)
            if not parts:
                return 0
            return len(list(parts[0].getElementsByClass("Measure")))

        def _key_str(score) -> str:
            try:
                return str(score.analyze("key"))
            except Exception:
                return "unknown"

        def _ts_str(score) -> str:
            try:
                ts_list = list(score.flatten().getElementsByClass("TimeSignature"))
                return ts_list[0].ratioString if ts_list else "unknown"
            except Exception:
                return "unknown"

        orig_notes = _note_count(orig)
        conv_notes = _note_count(conv)
        note_recall = conv_notes / orig_notes if orig_notes > 0 else 0.0

        orig_measures = _measure_count(orig)
        conv_measures = _measure_count(conv)

        orig_key = _key_str(orig)
        conv_key = _key_str(conv)
        key_match = orig_key == conv_key

        orig_ts = _ts_str(orig)
        conv_ts = _ts_str(conv)
        ts_match = orig_ts == conv_ts

        orig_voices = len(list(orig.parts))
        conv_voices = len(list(conv.parts))
        voice_match = orig_voices == conv_voices

        # Simple weighted overall score
        overall = (
            min(1.0, note_recall) * 0.5
            + (1.0 if key_match else 0.0) * 0.2
            + (1.0 if ts_match else 0.0) * 0.15
            + (1.0 if voice_match else 0.0) * 0.15
        )

        return {
            "note_count_original": orig_notes,
            "note_count_converted": conv_notes,
            "note_recall": round(note_recall, 3),
            "measure_count_original": orig_measures,
            "measure_count_converted": conv_measures,
            "key_original": orig_key,
            "key_converted": conv_key,
            "key_match": key_match,
            "time_signature_original": orig_ts,
            "time_signature_converted": conv_ts,
            "time_signature_match": ts_match,
            "voice_count_original": orig_voices,
            "voice_count_converted": conv_voices,
            "voice_count_match": voice_match,
            "overall_score": round(overall, 3),
        }
