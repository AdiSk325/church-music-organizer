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

_DEFAULT_MODEL = "gemini-2.5-flash"

# Per-step model override env vars (fall back to CMO_LLM_MODEL, then the hard default).
_MODEL_ENV = {
    "text": "CMO_LLM_MODEL_TEXT",
    "score": "CMO_LLM_MODEL_SCORE",
    "lyrics": "CMO_LLM_MODEL_LYRICS",
}

# Generous output ceilings — MusicXML can be large; streaming avoids SDK HTTP timeouts.
# Gemini 2.5 models support up to 65 536 output tokens.
_MAX_TOKENS = {"text": 8000, "score": 64000, "lyrics": 64000}

# Env var names that may hold a Gemini API key (zero-config order used by the SDK).
_KEY_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

T = TypeVar("T")


def _model_for(step: str) -> str:
    """Resolve the Gemini model id for a pipeline step from the environment."""
    env_key = _MODEL_ENV.get(step)
    if env_key and os.getenv(env_key):
        return os.environ[env_key].strip()
    return os.getenv("CMO_LLM_MODEL", _DEFAULT_MODEL).strip()


def _api_key() -> Optional[str]:
    for name in _KEY_ENV:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


@lru_cache(maxsize=1)
def llm_available() -> bool:
    """Return True when the Gemini SDK is installed and an API key resolves.

    A cheap, network-free probe: it checks that ``google-genai`` imports and that a
    ``GEMINI_API_KEY`` / ``GOOGLE_API_KEY`` is present. The result is cached for the
    process lifetime.
    """
    try:
        from google import genai  # noqa: F401
    except Exception:
        logger.info("llm_available: pakiet 'google-genai' nie jest zainstalowany")
        return False
    if not _api_key():
        logger.info("llm_available: brak klucza API Gemini (GEMINI_API_KEY/GOOGLE_API_KEY)")
        return False
    return True


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
        )
        chunks = self._client.models.generate_content_stream(
            model=model,
            contents=user,
            config=config,
        )
        return "".join(chunk.text or "" for chunk in chunks)

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
        return schema.model_validate_json(response.text)  # type: ignore[attr-defined]


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
