"""Google Gemini provider adapter for Shekel LLM cost tracking.

Patches google.genai.models.Models.generate_content (non-streaming) and
google.genai.models.Models.generate_content_stream (streaming) to intercept
API calls and record token costs inside active budgets.

Usage metadata comes from response.usage_metadata with fields:
  - prompt_token_count
  - candidates_token_count

The model name is NOT included in the response object; the wrapper captures it
from the 'model' kwarg before the call and passes it to _record().
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from shekel.providers.base import ProviderAdapter


class GeminiAdapter(ProviderAdapter):
    """Adapter for Google Gemini's generate_content API (google-genai SDK)."""

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "gemini"

    def install_patches(self) -> None:
        """Monkey-patch google.genai.models.Models generate_content methods."""
        from shekel import _patch

        try:
            import google.genai.models as gm

            if "gemini_sync" not in _patch._originals:
                _patch._originals["gemini_sync"] = gm.Models.generate_content
                _patch._originals["gemini_stream"] = gm.Models.generate_content_stream
                _patch._originals["gemini_async"] = gm.AsyncModels.generate_content
                _patch._originals["gemini_async_stream"] = gm.AsyncModels.generate_content_stream
                gm.Models.generate_content = _patch._gemini_sync_wrapper  # type: ignore[method-assign]
                gm.Models.generate_content_stream = _patch._gemini_stream_wrapper  # type: ignore[method-assign]
                gm.AsyncModels.generate_content = _patch._gemini_async_wrapper  # type: ignore[method-assign]
                gm.AsyncModels.generate_content_stream = _patch._gemini_async_stream_wrapper  # type: ignore[method-assign]
        except ImportError:
            pass

    def remove_patches(self) -> None:
        """Restore original google.genai.models.Models methods."""
        from shekel import _patch

        try:
            import google.genai.models as gm

            if "gemini_sync" in _patch._originals:
                gm.Models.generate_content = _patch._originals.pop("gemini_sync")  # type: ignore[method-assign]
            if "gemini_stream" in _patch._originals:
                gm.Models.generate_content_stream = _patch._originals.pop("gemini_stream")  # type: ignore[method-assign]
            if "gemini_async" in _patch._originals:
                gm.AsyncModels.generate_content = _patch._originals.pop("gemini_async")  # type: ignore[method-assign]
            if "gemini_async_stream" in _patch._originals:
                gm.AsyncModels.generate_content_stream = _patch._originals.pop(  # type: ignore[method-assign]
                    "gemini_async_stream"
                )
        except ImportError:
            pass

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        """Extract tokens from Gemini non-streaming response.

        Uses response.usage_metadata.prompt_token_count /
        response.usage_metadata.candidates_token_count.

        Model name is NOT available in the response — returns 'unknown'.
        The wrapper captures the model name from kwargs before the call.
        """
        try:
            usage = response.usage_metadata
            if usage is None:
                return 0, 0, "unknown"
            input_tokens = usage.prompt_token_count or 0
            output_tokens = usage.candidates_token_count or 0
            return input_tokens, output_tokens, "unknown"
        except AttributeError:
            return 0, 0, "unknown"

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        """Gemini streaming uses a separate method — never stream=True kwarg."""
        return False

    def wrap_stream(self, stream: Any) -> Generator[Any, None, tuple[int, int, str]]:
        """Wrap Gemini streaming response to collect usage_metadata from chunks."""
        seen: list[tuple[int, int]] = []
        for chunk in stream:
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                try:
                    it = usage.prompt_token_count or 0
                    ot = usage.candidates_token_count or 0
                    seen.append((it, ot))
                except AttributeError:
                    pass
            yield chunk
        if seen:
            it, ot = seen[-1]
        else:
            it, ot = 0, 0
        return it, ot, "unknown"

    def validate_fallback(self, fallback_model: str) -> None:
        """Validate that fallback model is a Gemini model."""
        if not fallback_model.startswith("gemini-"):
            raise ValueError(
                f"shekel: fallback model '{fallback_model}' does not appear to be a "
                f"Google Gemini model but the current call is to Gemini. "
                f"Cross-provider fallback is not supported. "
                f"Use a Gemini model as fallback (e.g. fallback='gemini-2.0-flash')."
            )
