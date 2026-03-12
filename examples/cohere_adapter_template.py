"""Template for adding a new LLM provider to Shekel via ProviderAdapter.

This file demonstrates how to integrate Cohere as an example.
Replace "cohere" / "Cohere" with your provider's details.

To use:
    1. Copy this file and adapt for your provider
    2. Register the adapter before opening any budget() context:
           from examples.cohere_adapter_template import CohereAdapter
           from shekel.providers.base import ADAPTER_REGISTRY
           ADAPTER_REGISTRY.register(CohereAdapter())
    3. Open a budget() context as usual — your provider is now tracked.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from shekel.providers.base import ADAPTER_REGISTRY, ProviderAdapter

# ---------------------------------------------------------------------------
# Sync wrapper (called instead of the original SDK method)
# ---------------------------------------------------------------------------


def _cohere_sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    from shekel import _context, _patch

    original = _patch._originals.get("cohere_sync")
    if original is None:
        raise RuntimeError("shekel: cohere original not stored")

    active_budget = _context.get_active_budget()
    if active_budget is not None and active_budget._using_fallback and active_budget.fallback:
        kwargs["model"] = active_budget.fallback['model']

    if kwargs.get("stream") is True:
        stream = original(self, *args, **kwargs)
        return _wrap_cohere_stream(stream)

    response = original(self, *args, **kwargs)
    adapter = ADAPTER_REGISTRY.get_by_name("cohere")
    if adapter:
        it, ot, model = adapter.extract_tokens(response)
        _patch._record(it, ot, model)
    return response


def _wrap_cohere_stream(stream: Any) -> Generator[Any, None, None]:
    from shekel import _patch

    input_tokens = 0
    output_tokens = 0
    model = "unknown"
    try:
        for event in stream:
            if hasattr(event, "meta") and hasattr(event.meta, "tokens"):
                input_tokens = getattr(event.meta.tokens, "input_tokens", 0) or 0
                output_tokens = getattr(event.meta.tokens, "output_tokens", 0) or 0
            if hasattr(event, "model"):
                model = event.model or "unknown"
            yield event
    finally:
        _patch._record(input_tokens, output_tokens, model)


# ---------------------------------------------------------------------------
# Async wrapper (optional — omit if provider has no async SDK)
# ---------------------------------------------------------------------------


async def _cohere_async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    from shekel import _context, _patch

    original = _patch._originals.get("cohere_async")
    if original is None:
        raise RuntimeError("shekel: cohere async original not stored")

    active_budget = _context.get_active_budget()
    if active_budget is not None and active_budget._using_fallback and active_budget.fallback:
        kwargs["model"] = active_budget.fallback['model']

    response = await original(self, *args, **kwargs)
    adapter = ADAPTER_REGISTRY.get_by_name("cohere")
    if adapter:
        it, ot, model = adapter.extract_tokens(response)
        _patch._record(it, ot, model)
    return response


# ---------------------------------------------------------------------------
# ProviderAdapter implementation
# ---------------------------------------------------------------------------


class CohereAdapter(ProviderAdapter):
    """Shekel adapter for the Cohere SDK.

    Tracks costs for cohere.Client.chat() and cohere.AsyncClient.chat().
    Adjust the import paths and field names to match your SDK's structure.
    """

    @property
    def name(self) -> str:
        return "cohere"

    def install_patches(self) -> None:
        from shekel import _patch

        try:
            import cohere.resources.chat as _cohere_chat  # adjust import path

            if "cohere_sync" not in _patch._originals:
                _patch._originals["cohere_sync"] = _cohere_chat.Chat.create
                _cohere_chat.Chat.create = _cohere_sync_wrapper  # type: ignore[method-assign]
            # Uncomment for async support:
            # if "cohere_async" not in _patch._originals:
            #     _patch._originals["cohere_async"] = _cohere_chat.AsyncChat.create
            #     _cohere_chat.AsyncChat.create = _cohere_async_wrapper
        except ImportError:
            pass  # Cohere SDK not installed — skip silently

    def remove_patches(self) -> None:
        from shekel import _patch

        try:
            import cohere.resources.chat as _cohere_chat

            if "cohere_sync" in _patch._originals:
                _cohere_chat.Chat.create = _patch._originals.pop("cohere_sync")  # type: ignore[method-assign]
            if "cohere_async" in _patch._originals:
                _cohere_chat.AsyncChat.create = _patch._originals.pop("cohere_async")  # type: ignore[method-assign]
        except ImportError:
            pass

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        """Extract (input_tokens, output_tokens, model) from a Cohere response.

        Adjust field paths to match your SDK's response structure.
        Must never raise — return (0, 0, 'unknown') on any error.
        """
        try:
            input_tokens = response.meta.tokens.input_tokens or 0
            output_tokens = response.meta.tokens.output_tokens or 0
            model = getattr(response, "model", None) or "unknown"
            return input_tokens, output_tokens, model
        except AttributeError:
            return 0, 0, "unknown"

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        """Return True if this call is streaming.

        For providers that use stream=True kwarg (like OpenAI/Cohere):
            return kwargs.get("stream") is True

        For providers that detect streaming from the response object (like Anthropic):
            return hasattr(response, "__iter__") and not hasattr(response, "usage")
        """
        return kwargs.get("stream") is True

    def wrap_stream(self, stream: Any) -> Generator[Any, None, tuple[int, int, str]]:
        """Yield stream chunks/events unchanged, return token counts at end.

        The return value becomes StopIteration.value when the generator
        is exhausted. Shekel's streaming wrapper reads it to record the cost.
        """
        input_tokens = 0
        output_tokens = 0
        model = "unknown"
        for event in stream:
            if hasattr(event, "meta") and hasattr(event.meta, "tokens"):
                input_tokens = getattr(event.meta.tokens, "input_tokens", 0) or 0
                output_tokens = getattr(event.meta.tokens, "output_tokens", 0) or 0
            if hasattr(event, "model"):
                model = event.model or "unknown"
            yield event
        return input_tokens, output_tokens, model

    def validate_fallback(self, fallback_model: str) -> None:
        """Raise ValueError if fallback model is from a different provider."""
        is_openai = any(fallback_model.startswith(p) for p in ("gpt-", "o1", "o2", "o3", "o4"))
        is_anthropic = fallback_model.startswith("claude-")
        if is_openai or is_anthropic:
            raise ValueError(
                f"shekel: fallback model '{fallback_model}' is not a Cohere model. "
                f"Cross-provider fallback is not supported. "
                f"Use a Cohere model as fallback (e.g. fallback={{'at_pct': 0.8, 'model': 'command-r-plus'}})."
            )
