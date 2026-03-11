"""OpenAI provider adapter for Shekel LLM cost tracking."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Tuple

from shekel.providers.base import ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    """Adapter for OpenAI's chat completions API."""

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "openai"

    def install_patches(self) -> None:
        """Monkey-patch OpenAI SDK methods."""
        from shekel import _patch

        try:
            import openai.resources.chat.completions as oai

            if "openai_sync" not in _patch._originals:
                _patch._originals["openai_sync"] = oai.Completions.create
                _patch._originals["openai_async"] = oai.AsyncCompletions.create
                oai.Completions.create = _patch._openai_sync_wrapper  # type: ignore[method-assign]
                oai.AsyncCompletions.create = _patch._openai_async_wrapper  # type: ignore[method-assign]
        except ImportError:
            pass

    def remove_patches(self) -> None:
        """Restore original OpenAI SDK methods."""
        from shekel import _patch

        try:
            import openai.resources.chat.completions as oai

            if "openai_sync" in _patch._originals:
                oai.Completions.create = _patch._originals.pop("openai_sync")  # type: ignore[method-assign]
            if "openai_async" in _patch._originals:
                oai.AsyncCompletions.create = _patch._originals.pop("openai_async")  # type: ignore[method-assign]
        except ImportError:
            pass

    def extract_tokens(self, response: Any) -> Tuple[int, int, str]:
        """Extract tokens from OpenAI non-streaming response."""
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
        """Detect streaming via the 'stream' kwarg."""
        return kwargs.get("stream") is True

    def wrap_stream(self, stream: Any) -> Generator[Any, None, Tuple[int, int, str]]:
        """Wrap OpenAI streaming response to collect token counts."""
        seen: list[Tuple[int, int, str]] = []
        for chunk in stream:
            if chunk.usage is not None:
                try:
                    it = chunk.usage.prompt_tokens or 0
                    ot = chunk.usage.completion_tokens or 0
                    m = getattr(chunk, "model", None) or "unknown"
                    seen.append((it, ot, m))
                except AttributeError:
                    pass
            yield chunk
        return seen[-1] if seen else (0, 0, "unknown")

    def validate_fallback(self, fallback_model: str) -> None:
        """Validate that fallback model is an OpenAI model."""
        if fallback_model.startswith("claude-"):
            raise ValueError(
                f"shekel: fallback model '{fallback_model}' appears to be an Anthropic model "
                f"but the current call is to OpenAI. Cross-provider fallback is not supported. "
                f"Use an OpenAI model as fallback (e.g. fallback='gpt-4o-mini')."
            )
