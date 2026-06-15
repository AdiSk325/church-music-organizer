"""Unit tests for the claude-CLI LLM backend (subprocess mocked — no real CLI call)."""

import subprocess
from types import SimpleNamespace

import pytest

from src.llm import claude_cli_client as mod
from src.llm.claude_cli_client import ClaudeCliClient, _extract_json

pytest.importorskip("pydantic")
from pydantic import BaseModel  # noqa: E402


class _Demo(BaseModel):
    a: int
    b: str


def _fake_run(stdout: str):
    def _run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return _run


def test_extract_json_strips_code_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('prose before {"a": 1, "b": "x"} trailing') == '{"a": 1, "b": "x"}'


def test_parse_validates_against_schema(monkeypatch):
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")
    monkeypatch.setattr(mod.subprocess, "run", _fake_run('{"a": 7, "b": "hi"}'))
    out = ClaudeCliClient().parse("sys", "user", _Demo, step="text")
    assert isinstance(out, _Demo) and out.a == 7 and out.b == "hi"


def test_parse_tolerates_fenced_json(monkeypatch):
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")
    monkeypatch.setattr(mod.subprocess, "run", _fake_run('```json\n{"a": 3, "b": "z"}\n```'))
    out = ClaudeCliClient().parse("sys", "user", _Demo, step="text")
    assert out.a == 3 and out.b == "z"


def test_complete_text_returns_stdout(monkeypatch):
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")
    monkeypatch.setattr(mod.subprocess, "run", _fake_run("hello world"))
    assert ClaudeCliClient().complete_text("sys", "user", step="score") == "hello world"


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")

    def _boom(*_a, **_k):
        return SimpleNamespace(returncode=1, stdout="", stderr="kaboom")

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    with pytest.raises(RuntimeError):
        ClaudeCliClient().complete_text("s", "u", step="score")


def _capturing_run(captured: dict, stdout: str = "ok"):
    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return _run


def test_lean_flags_present(monkeypatch):
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")
    cap: dict = {}
    monkeypatch.setattr(mod.subprocess, "run", _capturing_run(cap))
    ClaudeCliClient().complete_text("s", "u", step="text")
    cmd = cap["cmd"]
    assert "-p" in cmd and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "text"


def test_per_step_timeout_and_model(monkeypatch):
    monkeypatch.delenv("CMO_CLAUDE_CLI_TIMEOUT", raising=False)
    monkeypatch.delenv("CMO_CLAUDE_CLI_MODEL", raising=False)
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")
    cap: dict = {}
    monkeypatch.setattr(mod.subprocess, "run", _capturing_run(cap))
    # score gets the long timeout and the stronger default model
    ClaudeCliClient().complete_text("s", "u", step="score")
    assert cap["timeout"] == mod._DEFAULT_TIMEOUTS["score"]
    assert cap["cmd"][cap["cmd"].index("--model") + 1] == mod._DEFAULT_MODELS["score"]


def test_global_timeout_override(monkeypatch):
    monkeypatch.setenv("CMO_CLAUDE_CLI_TIMEOUT", "42")
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")
    cap: dict = {}
    monkeypatch.setattr(mod.subprocess, "run", _capturing_run(cap))
    ClaudeCliClient().complete_text("s", "u", step="lyrics")
    assert cap["timeout"] == 42


def test_timeout_expired_maps_to_runtimeerror(monkeypatch):
    monkeypatch.setattr(mod, "_find_claude", lambda: "claude")

    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(mod.subprocess, "run", _timeout)
    with pytest.raises(RuntimeError, match="timeout"):
        ClaudeCliClient().complete_text("s", "u", step="score")
