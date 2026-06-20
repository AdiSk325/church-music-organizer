"""Thin wrapper around the Google Gemini SDK (``google-genai``) for the pipeline's LLM steps.

Design goals
------------
* **Optional dependency.** ``google-genai`` is imported lazily inside methods so the rest
  of the application imports cleanly even when the package is absent. :func:`llm_available`
  reports whether the engine can actually run, exactly like ``tesseract_available`` /
  ``audiveris_available`` gate the OCR/OMR engines.
* **Zero-config credentials.** The default ``genai.Client()`` is "zero-config": it picks up
  the ``GEMINI_API_KEY`` (or ``GOOGLE_API_KEY``) environment variable automatically — no
  authorisation code and no key in the source. ``.env`` is loaded on import.
* **Configurable models.** Each step picks its model from ``.env`` (see ``_MODEL_ENV``),
  defaulting to ``gemini-2.5-flash``.

Steps are identified by the literals ``"text"`` (step 2), ``"score"`` (step 4) and
``"lyrics"`` (step 5).
"""

import logging
import os
from functools import lru_cache
from typing import Optional, Type, TypeVar

logger = logging.getLogger(__name__)

# Load .env once so GEMINI_API_KEY and CMO_LLM_* variables are visible. Best-effort —
# python-dotenv is a project dependency, but never let a missing .env break import.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - defensive
    pass

# Use the OS-native certificate store for TLS. On Windows with an HTTPS-intercepting
# proxy/antivirus the server presents a certificate signed by a local root CA that lives
# in the Windows store but not in certifi's bundle — which httpx (used by google-genai)
# would otherwise reject with CERTIFICATE_VERIFY_FAILED. ``truststore`` makes Python trust
# the OS store instead. Best-effort: harmless and a no-op where not installed/needed.
try:  # pragma: no cover - environment-dependent
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

_DEFAULT_MODEL = "gemini-2.5-flash"

# Per-step model override env vars (fall back to CMO_LLM_MODEL, then the hard default).
_MODEL_ENV = {
    "text": "CMO_LLM_MODEL_TEXT",
    "score": "CMO_LLM_MODEL_SCORE",
    "lyrics": "CMO_LLM_MODEL_LYRICS",
}

# Generous output ceilings — MusicXML can be large; streaming avoids SDK HTTP timeouts.
# Gemini 2.5 models support up to 65 536 output tokens.
_MAX_TOKENS = {"text": 8000, "score": 65535, "lyrics": 65535}

# Env var names that may hold a Gemini API key (zero-config order used by the SDK).
_KEY_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

T = TypeVar("T")


def _model_for(step: str) -> str:
    """Resolve the Gemini model id for a pipeline step from the environment."""
    env_key = _MODEL_ENV.get(step)
    if env_key and os.getenv(env_key):
        return os.environ[env_key].strip()
    return os.getenv("CMO_LLM_MODEL", _DEFAULT_MODEL).strip()


def _thinking_budget() -> int:
    """Token budget for Gemini's internal "thinking" (``0`` disables it).

    Every pipeline step is *output-bound*: structured lyric extraction (step 2) and full
    MusicXML regeneration (steps 4/5) need their whole token budget for the answer. With
    thinking on, the model can spend the entire ``max_output_tokens`` reasoning and stop at
    ``MAX_TOKENS`` before emitting anything — yielding an empty parse or a truncated, invalid
    document. Disabling it by default keeps the pipeline robust; re-enable via
    ``CMO_LLM_THINKING_BUDGET`` (gemini-2.5-flash accepts 0–24576).
    """
    try:
        return max(0, int(os.getenv("CMO_LLM_THINKING_BUDGET", "0").strip()))
    except ValueError:
        return 0


def _finish_reason(response) -> Optional[str]:
    """Best-effort extraction of the first candidate's finish reason for diagnostics."""
    try:
        return str(response.candidates[0].finish_reason)
    except Exception:  # pragma: no cover - defensive
        return None


def _blocked_reason(response) -> Optional[str]:
    """Return Gemini's prompt ``block_reason`` (e.g. ``PROHIBITED_CONTENT``) if the request
    was rejected at the safety layer — which yields zero candidates and no text."""
    try:
        feedback = getattr(response, "prompt_feedback", None)
        reason = getattr(feedback, "block_reason", None) if feedback else None
        return str(reason) if reason else None
    except Exception:  # pragma: no cover - defensive
        return None


def _api_key() -> Optional[str]:
    for name in _KEY_ENV:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


@lru_cache(maxsize=1)
def _gemini_ready() -> bool:
    """True when the Gemini SDK is installed and an API key resolves (network-free probe)."""
    try:
        from google import genai  # noqa: F401
    except Exception:
        logger.info("_gemini_ready: pakiet 'google-genai' nie jest zainstalowany")
        return False
    if not _api_key():
        logger.info("_gemini_ready: brak klucza API Gemini (GEMINI_API_KEY/GOOGLE_API_KEY)")
        return False
    return True


def llm_available() -> bool:
    """Return True when ANY LLM backend can run: Gemini (SDK+key) or the local ``claude`` CLI.

    The CLI fallback means the pipeline's LLM steps stay usable when the Gemini quota is
    exhausted or no key is set, as long as Claude Code is installed and authenticated.
    """
    if _gemini_ready():
        return True
    try:
        from src.llm.claude_cli_client import claude_cli_available

        return claude_cli_available()
    except Exception:  # pragma: no cover - defensive
        return False


class LLMClient:
    """Per-step Gemini access used by the pipeline agents."""

    @staticmethod
    def available() -> bool:
        return llm_available()

    def __init__(self):
        from google import genai  # lazy — only when actually invoking the engine

        # Zero-config: genai.Client() reads GEMINI_API_KEY from the environment. We pass
        # the resolved key explicitly so GOOGLE_API_KEY is also honoured.
        key = _api_key()
        self._client = genai.Client(api_key=key) if key else genai.Client()

    def complete_text(self, system: str, user: str, *, step: str) -> str:
        """Run a single completion and return the concatenated text.

        Uses streaming with a generous ``max_output_tokens`` so large MusicXML outputs do
        not trip the SDK's non-streaming timeout guard.
        """
        from google.genai import types

        model = _model_for(step)
        max_tokens = _MAX_TOKENS.get(step, 16000)
        logger.info("LLMClient.complete_text: step=%s model=%s", step, model)

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=_thinking_budget()),
        )
        parts: list[str] = []
        finish: Optional[str] = None
        blocked: Optional[str] = None
        for chunk in self._client.models.generate_content_stream(
            model=model,
            contents=user,
            config=config,
        ):
            if chunk.text:
                parts.append(chunk.text)
            reason = _finish_reason(chunk)
            if reason:
                finish = reason
            block = _blocked_reason(chunk)
            if block:
                blocked = block

        text = "".join(parts)
        if finish and "MAX_TOKENS" in finish:
            # Partial output is still returned (the caller's music21 gate rejects it); warn
            # so a too-small max_tokens / overlong score is diagnosable.
            logger.warning(
                "complete_text: odpowiedź ucięta na limicie tokenów (step=%s, model=%s)",
                step,
                model,
            )
        if not text:
            if blocked:
                raise RuntimeError(
                    f"Gemini zablokował zapytanie filtrem treści ({blocked}; step={step})."
                )
            raise RuntimeError(
                f"Gemini zwrócił pustą odpowiedź (step={step}, finish_reason={finish})."
            )
        return text

    def parse(self, system: str, user: str, schema: Type[T], *, step: str) -> T:
        """Run a completion constrained to ``schema`` (a Pydantic model) and return it.

        Gemini structured outputs: a JSON response is requested with the Pydantic model as
        ``response_schema`` and the parsed instance is read back from ``response.parsed``.
        """
        from google.genai import types

        model = _model_for(step)
        max_tokens = _MAX_TOKENS.get(step, 8000)
        logger.info("LLMClient.parse: step=%s model=%s schema=%s", step, model, schema.__name__)

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_budget=_thinking_budget()),
        )
        response = self._client.models.generate_content(
            model=model,
            contents=user,
            config=config,
        )
        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            return parsed
        # Fallback: the SDK could not auto-parse — validate the raw JSON ourselves.
        raw = getattr(response, "text", None)
        if raw:
            return schema.model_validate_json(raw)  # type: ignore[attr-defined]
        blocked = _blocked_reason(response)
        if blocked:
            raise RuntimeError(
                f"Gemini zablokował zapytanie filtrem treści ({blocked}; step={step})."
            )
        raise RuntimeError(
            f"Gemini nie zwrócił danych strukturalnych (step={step}, schema={schema.__name__}, "
            f"finish_reason={_finish_reason(response)})."
        )


class FallbackClient:
    """Try a primary LLM client; on quota/availability errors fall back to a secondary one.

    Used to run on Gemini by default and transparently switch to the ``claude`` CLI when
    Gemini returns 429 RESOURCE_EXHAUSTED / 503 etc., so a single exhausted quota does not
    stop the pipeline.
    """

    def __init__(self, primary, fallback):
        self._primary = primary
        self._fallback = fallback

    @staticmethod
    def _is_recoverable(exc: Exception) -> bool:
        s = str(exc).lower()
        return any(
            k in s
            for k in ("429", "resource_exhausted", "quota", "503", "unavailable", "overloaded")
        )

    def complete_text(self, system: str, user: str, *, step: str) -> str:
        try:
            return self._primary.complete_text(system, user, step=step)
        except Exception as exc:
            if self._is_recoverable(exc):
                logger.warning("LLM fallback (complete_text): %s — przełączam na claude CLI",
                               str(exc)[:140])
                return self._fallback.complete_text(system, user, step=step)
            raise

    def parse(self, system: str, user: str, schema, *, step: str):
        try:
            return self._primary.parse(system, user, schema, step=step)
        except Exception as exc:
            if self._is_recoverable(exc):
                logger.warning("LLM fallback (parse): %s — przełączam na claude CLI",
                               str(exc)[:140])
                return self._fallback.parse(system, user, schema, step=step)
            raise


def make_client():
    """Return the best available LLM client for the pipeline agents.

    Honors ``CMO_LLM_BACKEND`` (``gemini`` | ``claude_cli`` | ``auto``; default ``auto``):
    * ``auto`` — Gemini wrapped in a :class:`FallbackClient` to the ``claude`` CLI when both
      exist; otherwise whichever single backend is available.
    * ``gemini`` / ``claude_cli`` — force that backend.

    Raises:
        RuntimeError: when no backend is available (or the forced one is missing).
    """
    from src.llm.claude_cli_client import ClaudeCliClient, claude_cli_available

    backend = (os.getenv("CMO_LLM_BACKEND") or "auto").strip().lower()

    if backend == "claude_cli":
        if claude_cli_available():
            return ClaudeCliClient()
        raise RuntimeError("CMO_LLM_BACKEND=claude_cli, ale CLI 'claude' jest niedostępne.")
    if backend == "gemini":
        return LLMClient()

    gem = _gemini_ready()
    cli = claude_cli_available()
    if gem and cli:
        return FallbackClient(LLMClient(), ClaudeCliClient())
    if gem:
        return LLMClient()
    if cli:
        return ClaudeCliClient()
    raise RuntimeError("Brak dostępnego backendu LLM (ani Gemini, ani claude CLI).")


def extract_musicxml(text: str) -> Optional[str]:
    """Pull a MusicXML document out of an LLM reply.

    Agents are asked to return the document inside a fenced code block; this helper
    accepts a ```` ```xml ```` / ```` ``` ```` fence or a bare ``<?xml … >`` / ``<score-…>``
    payload. Returns ``None`` when nothing XML-like is found.
    """
    if not text:
        return None

    import re

    fence = re.search(r"```(?:xml|musicxml)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidate = fence.group(1).strip() if fence else text.strip()

    # Trim any prose before the XML/score declaration.
    start = re.search(r"<\?xml|<score-partwise|<score-timewise", candidate)
    if start:
        candidate = candidate[start.start() :].strip()
    elif "<" not in candidate:
        return None

    return candidate or None
