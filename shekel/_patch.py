from __future__ import annotations

import threading
from collections.abc import Generator
from typing import Any

from shekel import _context, _pricing

# ---------------------------------------------------------------------------
# Ref-count + lock — patch once when first budget() opens, unpatch when last closes
# ---------------------------------------------------------------------------
_patch_refcount: int = 0
_refcount_lock: threading.Lock = threading.Lock()
_originals: dict[str, Any] = {}


def apply_patches() -> None:
    global _patch_refcount
    with _refcount_lock:
        _patch_refcount += 1
        if _patch_refcount == 1:
            _install_patches()


def remove_patches() -> None:
    global _patch_refcount
    with _refcount_lock:
        _patch_refcount -= 1
        if _patch_refcount == 0:
            _restore_patches()


# ---------------------------------------------------------------------------
# Install / restore
# ---------------------------------------------------------------------------


def _install_patches() -> None:
    # Lazy import to avoid circular dependency with shekel.providers
    from shekel.providers import ADAPTER_REGISTRY

    ADAPTER_REGISTRY.install_all()


def _restore_patches() -> None:
    # Lazy import to avoid circular dependency with shekel.providers
    from shekel.providers import ADAPTER_REGISTRY

    ADAPTER_REGISTRY.remove_all()


# ---------------------------------------------------------------------------
# Fallback helpers (F1)
# ---------------------------------------------------------------------------


def _validate_same_provider(fallback_model: str, current_provider: str) -> None:
    """Raise ValueError if fallback model is from a different provider."""
    is_anthropic = fallback_model.startswith("claude-")
    is_openai = any(fallback_model.startswith(p) for p in ("gpt-", "o1", "o2", "o3", "o4", "text-"))
    is_gemini = fallback_model.startswith("gemini-")

    if current_provider == "openai" and is_anthropic:
        raise ValueError(
            f"shekel: fallback model '{fallback_model}' appears to be an Anthropic model "
            f"but the current call is to OpenAI. Cross-provider fallback is not supported in v0.2. "
            f"Use an OpenAI model as fallback (e.g. fallback='gpt-4o-mini')."
        )
    if current_provider == "anthropic" and is_openai:
        raise ValueError(
            f"shekel: fallback model '{fallback_model}' appears to be an OpenAI model "
            f"but the current call is to Anthropic. "
            f"Cross-provider fallback is not supported in v0.2. "
            f"Use an Anthropic model as fallback (e.g. fallback='claude-3-haiku-20240307')."
        )
    if current_provider == "gemini" and not is_gemini:
        raise ValueError(
            f"shekel: fallback model '{fallback_model}' does not appear to be a Gemini model "
            f"but the current call is to Gemini. Cross-provider fallback is not supported. "
            f"Use a Gemini model as fallback (e.g. fallback='gemini-2.0-flash')."
        )
    if current_provider == "huggingface" and (is_openai or is_anthropic or is_gemini):
        raise ValueError(
            f"shekel: fallback model '{fallback_model}' does not appear to be a HuggingFace model "
            f"but the current call is to HuggingFace. Cross-provider fallback is not supported. "
            f"Use a HuggingFace model as fallback (e.g. fallback='HuggingFaceH4/zephyr-7b-beta')."
        )


def _apply_fallback_if_needed(active_budget: Any, kwargs: dict[str, Any], provider: str) -> None:
    """Rewrite model kwarg to fallback if budget has switched. Validates same-provider."""
    # --- NEW in v0.2.6 (call limits): Check if fallback should activate based on call count ---
    active_budget._check_call_limit_for_fallback()

    if not active_budget._using_fallback or active_budget.fallback is None:
        return

    fallback_model: str = active_budget.fallback["model"]
    _validate_same_provider(fallback_model, provider)
    kwargs["model"] = fallback_model


# ---------------------------------------------------------------------------
# Token extraction helpers
# ---------------------------------------------------------------------------


def _extract_openai_tokens(response: Any) -> tuple[int, int, str]:
    try:
        input_tokens = response.usage.prompt_tokens or 0
        output_tokens = response.usage.completion_tokens or 0
        model = response.model or "unknown"
        return input_tokens, output_tokens, model
    except AttributeError:
        return 0, 0, "unknown"


def _extract_anthropic_tokens(response: Any) -> tuple[int, int, str]:
    try:
        input_tokens = response.usage.input_tokens or 0
        output_tokens = response.usage.output_tokens or 0
        model = response.model or "unknown"
        return input_tokens, output_tokens, model
    except AttributeError:
        return 0, 0, "unknown"


def _record(input_tokens: int, output_tokens: int, model: str) -> None:
    budget = _context.get_active_budget()
    if budget is None:
        return
    try:
        cost = _pricing.calculate_cost(model, input_tokens, output_tokens, budget.price_override)
    except Exception:
        cost = 0.0
    budget._record_spend(cost, model, {"input": input_tokens, "output": output_tokens})

    # Emit cost update event to registered adapters
    try:
        from shekel.integrations import AdapterRegistry

        AdapterRegistry.emit_event(
            "on_cost_update",
            {
                "spent": budget.spent,
                "limit": budget.limit,
                "name": budget.name,
                "full_name": budget.full_name,
                "depth": budget._depth,
                "model": model,
                "call_cost": cost,
            },
        )
    except Exception:
        # Don't break LLM calls if adapter system fails
        pass


# ---------------------------------------------------------------------------
# OpenAI sync wrapper
# ---------------------------------------------------------------------------


def _openai_sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("openai_sync")
    if original is None:
        raise RuntimeError("shekel: openai original not stored")

    # Apply fallback model rewrite before the call
    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "openai")

    if kwargs.get("stream") is True:
        kwargs.setdefault("stream_options", {})["include_usage"] = True
        stream = original(self, *args, **kwargs)
        return _wrap_openai_stream(stream)

    response = original(self, *args, **kwargs)
    input_tokens, output_tokens, model = _extract_openai_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


def _wrap_openai_stream(stream: Any) -> Generator[Any, None, None]:
    seen: list[tuple[int, int, str]] = []
    try:
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
    finally:
        if seen:
            it, ot, m = seen[-1]
        else:
            it, ot, m = 0, 0, "unknown"
        _record(it, ot, m)


# ---------------------------------------------------------------------------
# OpenAI async wrapper
# ---------------------------------------------------------------------------


async def _openai_async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("openai_async")
    if original is None:
        raise RuntimeError("shekel: openai async original not stored")

    # Apply fallback model rewrite before the call
    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "openai")

    if kwargs.get("stream") is True:
        kwargs.setdefault("stream_options", {})["include_usage"] = True
        stream = await original(self, *args, **kwargs)
        return _wrap_openai_stream_async(stream)

    response = await original(self, *args, **kwargs)
    input_tokens, output_tokens, model = _extract_openai_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


async def _wrap_openai_stream_async(stream: Any) -> Any:
    seen: list[tuple[int, int, str]] = []
    try:
        async for chunk in stream:
            if chunk.usage is not None:
                try:
                    it = chunk.usage.prompt_tokens or 0
                    ot = chunk.usage.completion_tokens or 0
                    m = getattr(chunk, "model", None) or "unknown"
                    seen.append((it, ot, m))
                except AttributeError:
                    pass
            yield chunk
    finally:
        if seen:
            it, ot, m = seen[-1]
        else:
            it, ot, m = 0, 0, "unknown"
        _record(it, ot, m)


# ---------------------------------------------------------------------------
# Anthropic sync wrapper
# ---------------------------------------------------------------------------


def _anthropic_sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("anthropic_sync")
    if original is None:
        raise RuntimeError("shekel: anthropic original not stored")

    # Apply fallback model rewrite before the call
    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "anthropic")

    response = original(self, *args, **kwargs)

    # Detect streaming: Anthropic returns an iterable event stream
    if hasattr(response, "__iter__") and not hasattr(response, "usage"):
        return _wrap_anthropic_stream(response)

    input_tokens, output_tokens, model = _extract_anthropic_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


def _wrap_anthropic_stream(stream: Any) -> Generator[Any, None, None]:
    input_tokens = 0
    output_tokens = 0
    model = "unknown"
    try:
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
    finally:
        _record(input_tokens, output_tokens, model)


# ---------------------------------------------------------------------------
# Anthropic async wrapper
# ---------------------------------------------------------------------------


async def _anthropic_async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("anthropic_async")
    if original is None:
        raise RuntimeError("shekel: anthropic async original not stored")

    # Apply fallback model rewrite before the call
    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "anthropic")

    response = await original(self, *args, **kwargs)

    if hasattr(response, "__aiter__") and not hasattr(response, "usage"):
        return _wrap_anthropic_stream_async(response)

    input_tokens, output_tokens, model = _extract_anthropic_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


async def _wrap_anthropic_stream_async(stream: Any) -> Any:
    input_tokens = 0
    output_tokens = 0
    model = "unknown"
    try:
        async for event in stream:
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
    finally:
        _record(input_tokens, output_tokens, model)


# ---------------------------------------------------------------------------
# LiteLLM sync wrapper
# ---------------------------------------------------------------------------


def _litellm_sync_wrapper(*args: Any, **kwargs: Any) -> Any:
    original = _originals.get("litellm_sync")
    if original is None:
        raise RuntimeError("shekel: litellm original not stored")

    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "litellm")

    if kwargs.get("stream") is True:
        kwargs.setdefault("stream_options", {})["include_usage"] = True
        stream = original(*args, **kwargs)
        return _wrap_litellm_stream(stream)

    response = original(*args, **kwargs)
    input_tokens, output_tokens, model = _extract_openai_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


def _wrap_litellm_stream(stream: Any) -> Generator[Any, None, None]:
    seen: list[tuple[int, int, str]] = []
    try:
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
    finally:
        it, ot, m = seen[-1] if seen else (0, 0, "unknown")
        _record(it, ot, m)


# ---------------------------------------------------------------------------
# LiteLLM async wrapper
# ---------------------------------------------------------------------------


async def _litellm_async_wrapper(*args: Any, **kwargs: Any) -> Any:
    original = _originals.get("litellm_async")
    if original is None:
        raise RuntimeError("shekel: litellm async original not stored")

    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "litellm")

    if kwargs.get("stream") is True:
        kwargs.setdefault("stream_options", {})["include_usage"] = True
        stream = await original(*args, **kwargs)
        return _wrap_litellm_stream_async(stream)

    response = await original(*args, **kwargs)
    input_tokens, output_tokens, model = _extract_openai_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


async def _wrap_litellm_stream_async(stream: Any) -> Any:
    seen: list[tuple[int, int, str]] = []
    try:
        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                try:
                    it = chunk.usage.prompt_tokens or 0
                    ot = chunk.usage.completion_tokens or 0
                    m = getattr(chunk, "model", None) or "unknown"
                    seen.append((it, ot, m))
                except AttributeError:
                    pass
            yield chunk
    finally:
        it, ot, m = seen[-1] if seen else (0, 0, "unknown")
        _record(it, ot, m)


# ---------------------------------------------------------------------------
# Gemini sync wrapper (google-genai SDK)
# ---------------------------------------------------------------------------


def _gemini_sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("gemini_sync")
    if original is None:
        raise RuntimeError("shekel: gemini original not stored")

    # Capture model name from kwargs before call (not available in response)
    model_name: str = kwargs.get("model", None) or "unknown"

    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "gemini")
        # Re-read model in case fallback rewrote it
        model_name = kwargs.get("model", None) or model_name

    response = original(self, *args, **kwargs)
    input_tokens, output_tokens, _ = _extract_gemini_tokens(response)
    _record(input_tokens, output_tokens, model_name)
    return response


def _gemini_stream_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("gemini_stream")
    if original is None:
        raise RuntimeError("shekel: gemini stream original not stored")

    model_name: str = kwargs.get("model", None) or "unknown"

    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "gemini")
        model_name = kwargs.get("model", None) or model_name

    stream = original(self, *args, **kwargs)
    return _wrap_gemini_stream(stream, model_name)


def _wrap_gemini_stream(stream: Any, model_name: str) -> Generator[Any, None, None]:
    seen: list[tuple[int, int]] = []
    try:
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
    finally:
        if seen:
            it, ot = seen[-1]
        else:
            it, ot = 0, 0
        _record(it, ot, model_name)


def _extract_gemini_tokens(response: Any) -> tuple[int, int, str]:
    try:
        usage = response.usage_metadata
        if usage is None:
            return 0, 0, "unknown"
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        return input_tokens, output_tokens, "unknown"
    except AttributeError:
        return 0, 0, "unknown"


# ---------------------------------------------------------------------------
# HuggingFace sync wrapper (huggingface-hub SDK)
# ---------------------------------------------------------------------------


def _huggingface_sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
    original = _originals.get("huggingface_sync")
    if original is None:
        raise RuntimeError("shekel: huggingface original not stored")

    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "huggingface")

    if kwargs.get("stream") is True:
        stream = original(self, *args, **kwargs)
        return _wrap_huggingface_stream(stream)

    response = original(self, *args, **kwargs)
    input_tokens, output_tokens, model = _extract_openai_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response


def _wrap_huggingface_stream(stream: Any) -> Generator[Any, None, None]:
    seen: list[tuple[int, int, str]] = []
    try:
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                try:
                    it = usage.prompt_tokens or 0
                    ot = usage.completion_tokens or 0
                    m = getattr(chunk, "model", None) or "unknown"
                    seen.append((it, ot, m))
                except AttributeError:
                    pass
            yield chunk
    finally:
        it, ot, m = seen[-1] if seen else (0, 0, "unknown")
        _record(it, ot, m)
