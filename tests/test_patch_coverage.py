"""Tests to reach 100% coverage of shekel/_patch.py.

Each test targets specific uncovered lines identified by coverage analysis.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _validate_same_provider (line 69)
# ---------------------------------------------------------------------------


def test_validate_same_provider_anthropic_rejects_openai_model():
    """Line 69: anthropic provider + openai fallback model raises ValueError."""
    from shekel._patch import _validate_same_provider

    with pytest.raises(ValueError, match="OpenAI model"):
        _validate_same_provider("gpt-4o", "anthropic")


# ---------------------------------------------------------------------------
# _extract_openai_tokens (lines 101-102)
# ---------------------------------------------------------------------------


def test_extract_openai_tokens_attribute_error():
    """Lines 101-102: response with no attributes returns (0, 0, 'unknown')."""
    from shekel._patch import _extract_openai_tokens

    response = MagicMock(spec=[])  # no attributes at all
    assert _extract_openai_tokens(response) == (0, 0, "unknown")


# ---------------------------------------------------------------------------
# _record (lines 121-122 and 141-143)
# ---------------------------------------------------------------------------


def test_record_swallows_pricing_exception():
    """Lines 121-122: if calculate_cost raises, cost falls back to 0.0."""
    from shekel import budget
    from shekel._patch import _record

    with budget(max_usd=1.0) as b:
        with patch("shekel._pricing.calculate_cost", side_effect=RuntimeError("bad")):
            _record(100, 50, "gpt-4o")
        assert b.spent == pytest.approx(0.0)


def test_record_swallows_adapter_emit_exception():
    """Lines 141-143: if AdapterRegistry.emit_event raises, exception is swallowed."""
    from shekel import budget
    from shekel._patch import _record

    with budget(max_usd=1.0):
        with patch(
            "shekel.integrations.AdapterRegistry.emit_event",
            side_effect=RuntimeError("adapter crash"),
        ):
            _record(100, 50, "gpt-4o-mini")  # must not raise


# ---------------------------------------------------------------------------
# _openai_sync_wrapper (line 154)
# ---------------------------------------------------------------------------


def test_openai_sync_wrapper_raises_if_no_original():
    """Line 154: RuntimeError when openai_sync not in _originals."""
    from shekel._patch import _openai_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="openai original not stored"):
            _openai_sync_wrapper(None)


# ---------------------------------------------------------------------------
# _wrap_openai_stream (lines 182-183)
# ---------------------------------------------------------------------------


def test_wrap_openai_stream_swallows_chunk_attribute_error():
    """Lines 182-183: chunk whose usage attrs raise AttributeError is handled."""
    from shekel._patch import _wrap_openai_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    list(_wrap_openai_stream(stream()))  # must not raise


# ---------------------------------------------------------------------------
# _openai_async_wrapper (line 201)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_async_wrapper_raises_if_no_original():
    """Line 201: RuntimeError when openai_async not in _originals."""
    from shekel._patch import _openai_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="openai async original not stored"):
            await _openai_async_wrapper(None)


# ---------------------------------------------------------------------------
# _wrap_openai_stream_async (lines 229-230 and 236)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_openai_stream_async_swallows_attribute_error():
    """Lines 229-230: broken usage in async stream chunk is handled."""
    from shekel._patch import _wrap_openai_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    async def stream():
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    async for _ in _wrap_openai_stream_async(stream()):
        pass


@pytest.mark.asyncio
async def test_wrap_openai_stream_async_no_usage_chunks():
    """Line 236: when no chunk has usage, falls back to (0, 0, 'unknown')."""
    from shekel import budget
    from shekel._patch import _wrap_openai_stream_async

    async def stream():
        chunk = MagicMock()
        chunk.usage = None
        yield chunk

    with budget(max_usd=1.0) as b:
        async for _ in _wrap_openai_stream_async(stream()):
            pass
    assert b.spent == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _anthropic_sync_wrapper (line 248)
# ---------------------------------------------------------------------------


def test_anthropic_sync_wrapper_raises_if_no_original():
    """Line 248: RuntimeError when anthropic_sync not in _originals."""
    from shekel._patch import _anthropic_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="anthropic original not stored"):
            _anthropic_sync_wrapper(None)


# ---------------------------------------------------------------------------
# _wrap_anthropic_stream (lines 277-278 and 282-283)
# ---------------------------------------------------------------------------


def test_wrap_anthropic_stream_swallows_message_start_attribute_error():
    """Lines 277-278: broken message_start event handled gracefully."""
    from shekel._patch import _wrap_anthropic_stream

    class BrokenMessage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageStartEvent:
        type = "message_start"
        message = BrokenMessage()

    list(_wrap_anthropic_stream(iter([MessageStartEvent()])))


def test_wrap_anthropic_stream_swallows_message_delta_attribute_error():
    """Lines 282-283: broken message_delta event handled gracefully."""
    from shekel._patch import _wrap_anthropic_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageDeltaEvent:
        type = "message_delta"
        usage = BrokenUsage()

    list(_wrap_anthropic_stream(iter([MessageDeltaEvent()])))


# ---------------------------------------------------------------------------
# _anthropic_async_wrapper (line 297)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_async_wrapper_raises_if_no_original():
    """Line 297: RuntimeError when anthropic_async not in _originals."""
    from shekel._patch import _anthropic_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="anthropic async original not stored"):
            await _anthropic_async_wrapper(None)


# ---------------------------------------------------------------------------
# _wrap_anthropic_stream_async (lines 325-326 and 330-331)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_anthropic_stream_async_swallows_message_start_error():
    """Lines 325-326: broken message_start in async stream handled."""
    from shekel._patch import _wrap_anthropic_stream_async

    class BrokenMessage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageStartEvent:
        type = "message_start"
        message = BrokenMessage()

    async def stream():
        yield MessageStartEvent()

    async for _ in _wrap_anthropic_stream_async(stream()):
        pass


@pytest.mark.asyncio
async def test_wrap_anthropic_stream_async_swallows_message_delta_error():
    """Lines 330-331: broken message_delta in async stream handled."""
    from shekel._patch import _wrap_anthropic_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageDeltaEvent:
        type = "message_delta"
        usage = BrokenUsage()

    async def stream():
        yield MessageDeltaEvent()

    async for _ in _wrap_anthropic_stream_async(stream()):
        pass


# ---------------------------------------------------------------------------
# _litellm_sync_wrapper (line 345)
# ---------------------------------------------------------------------------


def test_litellm_sync_wrapper_raises_if_no_original():
    """Line 345: RuntimeError when litellm_sync not in _originals."""
    from shekel._patch import _litellm_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="litellm original not stored"):
            _litellm_sync_wrapper()


# ---------------------------------------------------------------------------
# _wrap_litellm_stream (lines 372-373)
# ---------------------------------------------------------------------------


def test_wrap_litellm_stream_swallows_chunk_attribute_error():
    """Lines 372-373: broken usage attrs in litellm stream chunk handled."""
    from shekel._patch import _wrap_litellm_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    list(_wrap_litellm_stream(stream()))


# ---------------------------------------------------------------------------
# _litellm_async_wrapper (lines 388 and 395-397)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_litellm_async_wrapper_raises_if_no_original():
    """Line 388: RuntimeError when litellm_async not in _originals."""
    from shekel._patch import _litellm_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="litellm async original not stored"):
            await _litellm_async_wrapper()


@pytest.mark.asyncio
async def test_litellm_async_wrapper_stream_path():
    """Lines 395-397: stream=True branch in async wrapper returns async generator."""
    from shekel._patch import _litellm_async_wrapper

    async def mock_async_stream():
        chunk = MagicMock()
        chunk.usage = MagicMock()
        chunk.usage.prompt_tokens = 10
        chunk.usage.completion_tokens = 5
        chunk.model = "gpt-4o-mini"
        yield chunk

    original = AsyncMock(return_value=mock_async_stream())

    mock_budget = MagicMock()
    mock_budget._using_fallback = False

    with patch("shekel._patch._originals", {"litellm_async": original}):
        with patch("shekel._context.get_active_budget", return_value=mock_budget):
            stream = await _litellm_async_wrapper(model="gpt-4o-mini", messages=[], stream=True)
            assert stream is not None
            # drain the generator to hit the finally block
            async for _ in stream:
                pass


# ---------------------------------------------------------------------------
# _wrap_litellm_stream_async (lines 406-420)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrap_litellm_stream_async_records_cost():
    """Lines 406-414: async litellm stream records tokens from usage chunk."""
    from shekel import budget
    from shekel._patch import _wrap_litellm_stream_async

    async def stream():
        chunk = MagicMock()
        chunk.usage = None
        yield chunk
        final = MagicMock()
        final.usage = MagicMock()
        final.usage.prompt_tokens = 100
        final.usage.completion_tokens = 50
        final.model = "gpt-4o-mini"
        yield final

    with budget(max_usd=1.0) as b:
        async for _ in _wrap_litellm_stream_async(stream()):
            pass
    assert b.spent > 0


@pytest.mark.asyncio
async def test_wrap_litellm_stream_async_swallows_attribute_error():
    """Lines 415-416: broken usage in async litellm chunk handled."""
    from shekel._patch import _wrap_litellm_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    async def stream():
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    async for _ in _wrap_litellm_stream_async(stream()):
        pass


@pytest.mark.asyncio
async def test_wrap_litellm_stream_async_no_usage_fallback():
    """Line 420: no usage chunks → falls back to (0, 0, 'unknown')."""
    from shekel import budget
    from shekel._patch import _wrap_litellm_stream_async

    async def stream():
        chunk = MagicMock()
        chunk.usage = None
        yield chunk

    with budget(max_usd=1.0) as b:
        async for _ in _wrap_litellm_stream_async(stream()):
            pass
    assert b.spent == pytest.approx(0.0)
