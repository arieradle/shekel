"""Anthropic provider adapter for Shekel LLM cost tracking."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from shekel.providers.base import ProviderAdapter


class AnthropicAdapter(ProviderAdapter):
    """Adapter for Anthropic's messages API."""

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "anthropic"

    def install_patches(self) -> None:
        """Monkey-patch Anthropic SDK methods."""
        try:
            import anthropic.resources.messages as ant

            if "anthropic_sync" not in self._originals:
                self._originals["anthropic_sync"] = ant.Messages.create
                self._originals["anthropic_async"] = ant.AsyncMessages.create

                from shekel._patch import _anthropic_sync_wrapper, _anthropic_async_wrapper
                ant.Messages.create = _anthropic_sync_wrapper  # type: ignore[method-assign]
                ant.AsyncMessages.create = _anthropic_async_wrapper  # type: ignore[method-assign]
        except ImportError:
            pass

    def remove_patches(self) -> None:
        """Restore original Anthropic SDK methods."""
        try:
            import anthropic.resources.messages as ant

            if "anthropic_sync" in self._originals:
                ant.Messages.create = self._originals.pop("anthropic_sync")  # type: ignore[method-assign]
            if "anthropic_async" in self._originals:
                ant.AsyncMessages.create = self._originals.pop("anthropic_async")  # type: ignore[method-assign]
        except ImportError:
            pass

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        """Extract tokens from Anthropic non-streaming response."""
        try:
            usage = response.usage
            if usage is None:
                model = getattr(response, "model", None) or "unknown"
                return 0, 0, model
            input_tokens = usage.input_tokens or 0
            output_tokens = usage.output_tokens or 0
            model = getattr(response, "model", None) or "unknown"
            return input_tokens, output_tokens, model
        except AttributeError:
            return 0, 0, "unknown"

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        """Detect streaming by inspecting the response object."""
        if response is None:
            return False
        return hasattr(response, "__iter__") and not hasattr(response, "usage")

    def wrap_stream(self, stream: Any) -> Generator[Any, None, tuple[int, int, str]]:
        """Wrap Anthropic streaming response to collect token counts."""
        input_tokens = 0
        output_tokens = 0
        model = "unknown"
        for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "message_start":
                try:
                    input_tokens = event.message.usage.input_tokens or 0
                    model = getattr(event.message, "model", None) or "unknown"
                except AttributeError:
                    pass
            elif event_type == "message_delta":
                try:
                    output_tokens = event.usage.output_tokens or 0
                except AttributeError:
                    pass
            yield event
        return input_tokens, output_tokens, model

    def validate_fallback(self, fallback_model: str) -> None:
        """Validate that fallback model is an Anthropic model."""
        is_openai = any(fallback_model.startswith(p) for p in ("gpt-", "o1", "o2", "o3", "o4", "text-"))
        if is_openai:
            raise ValueError(
                f"shekel: fallback model '{fallback_model}' appears to be an OpenAI model "
                f"but the current call is to Anthropic. Cross-provider fallback is not supported. "
                f"Use an Anthropic model as fallback (e.g. fallback='claude-3-haiku-20240307')."
            )
