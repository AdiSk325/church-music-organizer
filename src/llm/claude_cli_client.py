"""LLM backend that drives the local ``claude`` CLI via subprocess.

A drop-in alternative to :class:`src.llm.client.LLMClient` (Gemini) for when the Gemini
quota is exhausted or no key is configured, but the Claude Code CLI is installed and
authenticated in the environment. It speaks the same two methods the pipeline agents use —
``complete_text`` and ``parse`` — by piping a prompt to ``claude -p`` (non-interactive
"print" mode) over stdin and reading the completion from stdout.

Structured output (``parse``) is achieved by appending the target JSON schema to the prompt
and instructing the model to return JSON only; the result is validated against the Pydantic
model exactly like the Gemini path.
"""

import json
import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Per-step wall-clock timeouts (seconds). The CLI pays a fixed cold-start overhead on every
# call and the score/underlay steps additionally generate large MusicXML, so they get far more
# headroom than the small text/lyrics structured calls. ``CMO_CLAUDE_CLI_TIMEOUT`` overrides
# all of them at once (kept for backward compatibility).
_DEFAULT_TIMEOUTS = {"text": 180, "lyrics": 240, "score": 600, "underlay": 360}
_TIMEOUT_FALLBACK = 300


def _timeout_for(step: str) -> int:
    override = os.getenv("CMO_CLAUDE_CLI_TIMEOUT")
    if override and override.strip().isdigit():
        return int(override.strip())
    return _DEFAULT_TIMEOUTS.get(step, _TIMEOUT_FALLBACK)


# Per-step default model: fast model for the small structured calls, a stronger one for the
# musically demanding score/underlay work. ``CMO_CLAUDE_CLI_MODEL`` overrides all steps.
_DEFAULT_MODELS = {"text": "haiku", "lyrics": "haiku", "score": "sonnet", "underlay": "sonnet"}


def _model_for(step: str, explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    env = os.getenv("CMO_CLAUDE_CLI_MODEL")
    if env and env.strip():
        return env.strip()
    return _DEFAULT_MODELS.get(step)

# Well-known install locations checked after PATH (Windows user-local install).
_KNOWN = [
    Path.home() / ".local" / "bin" / "claude",
    Path.home() / ".local" / "bin" / "claude.cmd",
    Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd",
]


@lru_cache(maxsize=1)
def _find_claude() -> Optional[str]:
    """Locate the ``claude`` CLI executable (PATH first, then known locations)."""
    found = shutil.which("claude")
    if found:
        return found
    for cand in _KNOWN:
        if cand.exists():
            return str(cand)
    return None


def claude_cli_available() -> bool:
    """Return True when the ``claude`` CLI can be located on this machine."""
    return _find_claude() is not None


def _run(prompt: str, *, step: str, model: Optional[str] = None) -> str:
    """Pipe ``prompt`` to ``claude -p`` over stdin and return stdout text.

    The invocation is kept deliberately lean to cut the ~15 s cold-start overhead and to
    avoid hangs: ``--strict-mcp-config`` (with no ``--mcp-config``) skips the MCP server
    health-checks, a fast model is pinned per step, and the prompt is a single-shot text
    completion (no tool use needed). A :class:`subprocess.TimeoutExpired` is mapped to a
    ``RuntimeError`` whose message contains "timeout" so the per-voice underlay loop and the
    :class:`~src.llm.client.FallbackClient` treat it as a transient, skippable failure.
    """
    exe = _find_claude()
    if not exe:
        raise RuntimeError("Nie znaleziono CLI 'claude' w środowisku.")
    cmd = [exe, "-p", "--output-format", "text", "--strict-mcp-config"]
    resolved_model = _model_for(step, model)
    if resolved_model:
        cmd += ["--model", resolved_model]
    timeout = _timeout_for(step)
    logger.info(
        "ClaudeCliClient: wywołanie %s (step=%s, model=%s, timeout=%ss, prompt %d znaków)",
        exe, step, resolved_model or "domyślny", timeout, len(prompt),
    )
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"claude CLI przekroczył limit czasu (timeout {timeout}s, step={step})."
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI zwrócił kod {proc.returncode}: {(proc.stderr or '')[:500]}"
        )
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError("claude CLI zwrócił pustą odpowiedź.")
    return out


def _extract_json(text: str) -> str:
    """Pull a JSON object/array out of an LLM reply (tolerate code fences / prose)."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    # Otherwise grab from the first opening brace/bracket to its matching last one.
    start = min(
        [i for i in (text.find("{"), text.find("[")) if i != -1],
        default=-1,
    )
    if start == -1:
        return text.strip()
    end = max(text.rfind("}"), text.rfind("]"))
    if end > start:
        return text[start : end + 1].strip()
    return text.strip()


class ClaudeCliClient:
    """Pipeline LLM access backed by the local ``claude`` CLI (same API as ``LLMClient``)."""

    @staticmethod
    def available() -> bool:
        return claude_cli_available()

    def __init__(self, model: Optional[str] = None):
        # Default model = whatever the CLI is configured to use; override via env if desired.
        self._model = model or os.getenv("CMO_CLAUDE_CLI_MODEL") or None

    def complete_text(self, system: str, user: str, *, step: str) -> str:
        """Run a single completion and return the text (mirrors LLMClient.complete_text)."""
        prompt = f"{system}\n\n{user}"
        logger.info("ClaudeCliClient.complete_text: step=%s", step)
        return _run(prompt, step=step, model=self._model)

    def parse(self, system: str, user: str, schema: Type[T], *, step: str) -> T:
        """Run a completion constrained to ``schema`` and return the parsed instance.

        The JSON schema is appended to the prompt and JSON-only output is requested; the
        reply is validated with Pydantic, matching the Gemini structured-output contract.
        """
        try:
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        except Exception:  # pragma: no cover - schema without pydantic v2
            schema_json = schema.__name__
        prompt = (
            f"{system}\n\n{user}\n\n"
            "Zwróć WYŁĄCZNIE poprawny obiekt JSON zgodny z poniższym schematem JSON Schema "
            "(bez komentarzy, bez bloków kodu, bez tekstu poza JSON):\n"
            f"{schema_json}"
        )
        logger.info("ClaudeCliClient.parse: step=%s schema=%s", step, schema.__name__)
        raw = _run(prompt, step=step, model=self._model)
        payload = _extract_json(raw)
        return schema.model_validate_json(payload)  # type: ignore[attr-defined]
