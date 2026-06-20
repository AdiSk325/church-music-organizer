"""LLM-powered pipeline agents (text cleaning, score correction, lyric underlay).

This package wraps the Google Gemini SDK (``google-genai``) behind
:class:`~src.llm.client.LLMClient` and exposes three task-specific agents used by
``PipelineService``:

* :func:`~src.llm.lyrics_cleaner.clean_lyrics` — step 2 (OCR text → clean lyrics)
* :func:`~src.llm.score_corrector.correct_score` — step 4 (MusicXML harmonic/melodic fixes)
* :func:`~src.llm.lyric_underlayer.underlay_lyrics` — step 5 (lyrics → under the notes)

All ``google-genai`` imports are deferred to call time so the rest of the application
(and the test suite, which mocks the client) keeps working even when the package is
not installed — mirroring how the OCR/OMR engines gate on optional system tools.
"""

from src.llm.client import LLMClient, llm_available

__all__ = ["LLMClient", "llm_available"]
