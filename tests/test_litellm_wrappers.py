"""Tests for LiteLLM provider wrappers in shekel/_patch.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shekel import budget


def test_litellm_sync_wrapper_raises_if_no_original() -> None:
    """RuntimeError when litellm_sync not in _originals."""
    from shekel._patch import _litellm_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="litellm original not stored"):
            _litellm_sync_wrapper()


def test_wrap_litellm_stream_swallows_chunk_attribute_error() -> None:
    """Broken usage attrs in litellm stream chunk handled without crashing."""
    from shekel._patch import _wrap_litellm_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    list(_wrap_litellm_stream(stream()))


@pytest.mark.asyncio
async def test_litellm_async_wrapper_raises_if_no_original() -> None:
    """RuntimeError when litellm_async not in _originals."""
    from shekel._patch import _litellm_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="litellm async original not stored"):
            await _litellm_async_wrapper()


@pytest.mark.asyncio
async def test_litellm_async_wrapper_stream_path() -> None:
    """stream=True branch in async wrapper returns an async generator."""
    from shekel._patch import _litellm_async_wrapper

    async def mock_async_stream():  # type: ignore[return]
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
            async for _ in stream:
                pass


@pytest.mark.asyncio
async def test_wrap_litellm_stream_async_records_cost() -> None:
    """Async litellm stream records tokens from the final usage chunk."""
    from shekel._patch import _wrap_litellm_stream_async

    async def stream():  # type: ignore[return]
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
async def test_wrap_litellm_stream_async_swallows_attribute_error() -> None:
    """Broken usage in async litellm chunk is handled without crashing."""
    from shekel._patch import _wrap_litellm_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    async def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    async for _ in _wrap_litellm_stream_async(stream()):
        pass


@pytest.mark.asyncio
async def test_wrap_litellm_stream_async_no_usage_fallback() -> None:
    """No usage chunks — records $0 rather than crashing."""
    from shekel._patch import _wrap_litellm_stream_async

    async def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = None
        yield chunk

    with budget(max_usd=1.0) as b:
        async for _ in _wrap_litellm_stream_async(stream()):
            pass
    assert b.spent == pytest.approx(0.0)
