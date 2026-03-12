"""Tests for OpenAI provider wrappers in shekel/_patch.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shekel import budget

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"


def test_record_unknown_model_falls_back_to_zero_cost() -> None:
    """Unknown model with no price override records $0 rather than crashing."""
    fake = MagicMock()
    fake.model = "gpt-999-not-real"
    fake.usage.prompt_tokens = 100
    fake.usage.completion_tokens = 50

    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-999-not-real", messages=[])

    assert b.spent == pytest.approx(0.0)


def test_extract_openai_tokens_attribute_error() -> None:
    """Response with no attributes returns (0, 0, 'unknown')."""
    from shekel._patch import _extract_openai_tokens

    response = MagicMock(spec=[])  # no attributes at all
    assert _extract_openai_tokens(response) == (0, 0, "unknown")


def test_openai_sync_wrapper_raises_if_no_original() -> None:
    """RuntimeError when openai_sync not in _originals."""
    from shekel._patch import _openai_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="openai original not stored"):
            _openai_sync_wrapper(None)


def test_wrap_openai_stream_swallows_chunk_attribute_error() -> None:
    """Chunk whose usage attrs raise AttributeError is handled without crashing."""
    from shekel._patch import _wrap_openai_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    list(_wrap_openai_stream(stream()))  # must not raise


@pytest.mark.asyncio
async def test_openai_async_wrapper_raises_if_no_original() -> None:
    """RuntimeError when openai_async not in _originals."""
    from shekel._patch import _openai_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="openai async original not stored"):
            await _openai_async_wrapper(None)


@pytest.mark.asyncio
async def test_wrap_openai_stream_async_swallows_attribute_error() -> None:
    """Broken usage in async stream chunk is handled without crashing."""
    from shekel._patch import _wrap_openai_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    async def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    async for _ in _wrap_openai_stream_async(stream()):
        pass


@pytest.mark.asyncio
async def test_wrap_openai_stream_async_no_usage_chunks() -> None:
    """When no chunk has usage, records $0 rather than crashing."""
    from shekel._patch import _wrap_openai_stream_async

    async def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = None
        yield chunk

    with budget(max_usd=1.0) as b:
        async for _ in _wrap_openai_stream_async(stream()):
            pass
    assert b.spent == pytest.approx(0.0)
