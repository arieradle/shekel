"""LiteLLM provider adapter for Shekel LLM cost tracking."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from shekel.providers.base import ProviderAdapter


class LiteLLMAdapter(ProviderAdapter):
    """Adapter for LiteLLM's unified completion API.

    LiteLLM exposes an OpenAI-compatible interface (litellm.completion /
    litellm.acompletion) that routes to 100+ providers. This adapter patches
    those module-level functions to track cost inside shekel budgets.
    """

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "litellm"

    def install_patches(self) -> None:
        """Monkey-patch litellm.completion and litellm.acompletion."""
        from shekel import _patch

        try:
            import litellm

            if "litellm_sync" not in _patch._originals:
                _patch._originals["litellm_sync"] = litellm.completion
                _patch._originals["litellm_async"] = litellm.acompletion
                litellm.completion = _patch._litellm_sync_wrapper  # type: ignore[assignment]
                litellm.acompletion = _patch._litellm_async_wrapper  # type: ignore[assignment]
        except ImportError:
            pass

    def remove_patches(self) -> None:
        """Restore original litellm functions."""
        from shekel import _patch

        try:
            import litellm

            if "litellm_sync" in _patch._originals:
                litellm.completion = _patch._originals.pop("litellm_sync")  # type: ignore[assignment]
            if "litellm_async" in _patch._originals:
                litellm.acompletion = _patch._originals.pop("litellm_async")  # type: ignore[assignment]
        except ImportError:
            pass

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        """Extract tokens from a LiteLLM non-streaming response.

        LiteLLM uses the OpenAI format: usage.prompt_tokens / usage.completion_tokens.
        Model names may include a provider prefix (e.g. 'openai/gpt-4o').
        """
        try:
            usage = response.usage
            if usage is None:
                model = getattr(response, "model", None) or "unknown"
                return 0, 0, model
            input_tokens = usage.prompt_tokens or 0
            output_tokens = usage.completion_tokens or 0
            model = getattr(response, "model", None) or "unknown"
            return input_tokens, output_tokens, model
        except AttributeError:
            return 0, 0, "unknown"

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        """Detect streaming via the 'stream' kwarg (same as OpenAI)."""
        return kwargs.get("stream") is True

    def wrap_stream(self, stream: Any) -> Generator[Any, None, tuple[int, int, str]]:
        """Wrap a LiteLLM streaming response to collect token counts."""
        seen: list[tuple[int, int, str]] = []
        for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                try:
                    it = chunk.usage.prompt_tokens or 0
                    ot = chunk.usage.completion_tokens or 0
                    m = getattr(chunk, "model", None) or "unknown"
                    seen.append((it, ot, m))
                except AttributeError:
                    pass
            yield chunk
        return seen[-1] if seen else (0, 0, "unknown")
