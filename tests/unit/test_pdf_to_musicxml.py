"""Unit tests for src/ocr/pdf_to_musicxml.py.

Covers:
  - _find_audiveris(): env var resolution, PATH lookup, fallback to None
  - audiveris_available(): thin bool wrapper around _find_audiveris()
  - PdfToMusicXml._build_command(): .jar vs .exe/.bat invocation, required flags
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.ocr.pdf_to_musicxml import PdfToMusicXml, _find_audiveris, audiveris_available

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_converter(exe: str) -> PdfToMusicXml:
    """Return a PdfToMusicXml with _exe set — skips _find_audiveris() on init."""
    conv = PdfToMusicXml.__new__(PdfToMusicXml)
    conv._exe = exe
    return conv


# ---------------------------------------------------------------------------
# _find_audiveris(): AUDIVERIS_PATH env var
# ---------------------------------------------------------------------------


class TestFindAudiverisEnvPath:
    def test_returns_path_when_audiveris_path_env_set_and_file_exists(self, tmp_path, monkeypatch):
        exe = tmp_path / "Audiveris.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("AUDIVERIS_PATH", str(exe))
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        assert _find_audiveris() == str(exe)

    def test_ignores_audiveris_path_when_file_does_not_exist(self, monkeypatch):
        monkeypatch.setenv("AUDIVERIS_PATH", "/definitely/nonexistent/Audiveris.exe")
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        with patch("src.ocr.pdf_to_musicxml.shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = _find_audiveris()

        assert result is None

    def test_audiveris_path_takes_precedence_over_jar_env(self, tmp_path, monkeypatch):
        exe = tmp_path / "Audiveris.exe"
        jar = tmp_path / "audiveris.jar"
        exe.write_bytes(b"")
        jar.write_bytes(b"")
        monkeypatch.setenv("AUDIVERIS_PATH", str(exe))
        monkeypatch.setenv("AUDIVERIS_JAR", str(jar))

        assert _find_audiveris() == str(exe)


# ---------------------------------------------------------------------------
# _find_audiveris(): AUDIVERIS_JAR env var
# ---------------------------------------------------------------------------


class TestFindAudiverisEnvJar:
    def test_returns_jar_when_audiveris_jar_env_set_and_file_exists(self, tmp_path, monkeypatch):
        jar = tmp_path / "audiveris.jar"
        jar.write_bytes(b"")
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.setenv("AUDIVERIS_JAR", str(jar))

        assert _find_audiveris() == str(jar)

    def test_ignores_audiveris_jar_when_file_does_not_exist(self, monkeypatch):
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.setenv("AUDIVERIS_JAR", "/nonexistent/audiveris.jar")

        with patch("src.ocr.pdf_to_musicxml.shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = _find_audiveris()

        assert result is None


# ---------------------------------------------------------------------------
# _find_audiveris(): PATH lookup via shutil.which
# ---------------------------------------------------------------------------


class TestFindAudiverisWhich:
    def test_returns_path_found_by_which(self, monkeypatch):
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        with patch("src.ocr.pdf_to_musicxml.shutil.which", return_value="/usr/bin/Audiveris"):
            result = _find_audiveris()

        assert result == "/usr/bin/Audiveris"

    def test_checks_capitalised_name_first(self, monkeypatch):
        """shutil.which("Audiveris") is checked before "audiveris"."""
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        call_log: list[str] = []

        def fake_which(name):
            call_log.append(name)
            return "/bin/Audiveris" if name == "Audiveris" else None

        with patch("src.ocr.pdf_to_musicxml.shutil.which", side_effect=fake_which):
            result = _find_audiveris()

        assert result == "/bin/Audiveris"
        assert call_log[0] == "Audiveris"


# ---------------------------------------------------------------------------
# _find_audiveris(): fallback — returns None when nothing found
# ---------------------------------------------------------------------------


class TestFindAudiverisNotFound:
    def test_returns_none_when_nothing_is_available(self, monkeypatch):
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        with patch("src.ocr.pdf_to_musicxml.shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = _find_audiveris()

        assert result is None


# ---------------------------------------------------------------------------
# audiveris_available()
# ---------------------------------------------------------------------------


class TestAudiverisAvailable:
    def test_returns_true_when_audiveris_path_env_points_to_real_file(self, tmp_path, monkeypatch):
        exe = tmp_path / "Audiveris.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("AUDIVERIS_PATH", str(exe))
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        assert audiveris_available() is True

    def test_returns_false_when_nothing_found(self, monkeypatch):
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        with patch("src.ocr.pdf_to_musicxml.shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = audiveris_available()

        assert result is False

    def test_is_bool(self, monkeypatch):
        monkeypatch.delenv("AUDIVERIS_PATH", raising=False)
        monkeypatch.delenv("AUDIVERIS_JAR", raising=False)

        with patch("src.ocr.pdf_to_musicxml.shutil.which", return_value=None):
            with patch.object(Path, "exists", return_value=False):
                result = audiveris_available()

        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# PdfToMusicXml._build_command(): .jar invocation
# ---------------------------------------------------------------------------


class TestBuildCommandJar:
    def test_starts_with_java_dash_jar(self):
        conv = _make_converter("/path/to/audiveris.jar")
        cmd = conv._build_command("/input/score.pdf", "/output/dir")
        assert cmd[0] == "java"
        assert cmd[1] == "-jar"
        assert cmd[2] == "/path/to/audiveris.jar"

    def test_uppercase_jar_extension_is_treated_as_jar(self):
        """Extension matching must be case-insensitive."""
        conv = _make_converter("/path/to/Audiveris.JAR")
        cmd = conv._build_command("/input/score.pdf", "/output/dir")
        assert cmd[0] == "java"

    def test_contains_batch_flag(self):
        conv = _make_converter("/path/audiveris.jar")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert "-batch" in cmd

    def test_contains_export_flag(self):
        conv = _make_converter("/path/audiveris.jar")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert "-export" in cmd

    def test_contains_output_flag_followed_by_dir(self):
        conv = _make_converter("/path/audiveris.jar")
        cmd = conv._build_command("/input/score.pdf", "/my/output/dir")
        idx = cmd.index("-output")
        assert cmd[idx + 1] == "/my/output/dir"

    def test_input_path_follows_separator(self):
        conv = _make_converter("/path/audiveris.jar")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert "--" in cmd
        sep_idx = cmd.index("--")
        assert cmd[sep_idx + 1] == "/input/score.pdf"


# ---------------------------------------------------------------------------
# PdfToMusicXml._build_command(): .exe / .bat / script invocation
# ---------------------------------------------------------------------------


class TestBuildCommandExe:
    def test_exe_starts_with_exe_path_not_java(self):
        conv = _make_converter(r"C:\Audiveris\Audiveris.exe")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert cmd[0] == r"C:\Audiveris\Audiveris.exe"
        assert "java" not in cmd

    def test_bat_starts_with_bat_path_not_java(self):
        conv = _make_converter("/home/user/Audiveris/bin/Audiveris.bat")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert cmd[0] == "/home/user/Audiveris/bin/Audiveris.bat"
        assert "java" not in cmd

    def test_bare_script_starts_with_script_path(self):
        """A plain script (no extension) should be called directly."""
        conv = _make_converter("/usr/local/bin/audiveris")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert cmd[0] == "/usr/local/bin/audiveris"
        assert "java" not in cmd

    def test_exe_contains_batch_flag(self):
        conv = _make_converter("/path/Audiveris.exe")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert "-batch" in cmd

    def test_exe_contains_export_flag(self):
        conv = _make_converter("/path/Audiveris.exe")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert "-export" in cmd

    def test_exe_contains_output_flag_followed_by_dir(self):
        conv = _make_converter("/path/Audiveris.exe")
        cmd = conv._build_command("/input/score.pdf", "/my/output/dir")
        idx = cmd.index("-output")
        assert cmd[idx + 1] == "/my/output/dir"

    def test_exe_input_path_follows_separator(self):
        conv = _make_converter("/path/Audiveris.exe")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert "--" in cmd
        sep_idx = cmd.index("--")
        assert cmd[sep_idx + 1] == "/input/score.pdf"

    def test_exe_result_is_list(self):
        conv = _make_converter("/path/Audiveris.exe")
        cmd = conv._build_command("/input/score.pdf", "/output")
        assert isinstance(cmd, list)
        assert all(isinstance(item, str) for item in cmd)
