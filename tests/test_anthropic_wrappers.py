"""Tests for Anthropic provider wrappers in shekel/_patch.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from shekel import budget

ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"


def test_anthropic_malformed_response_records_zero() -> None:
    """Response missing .usage attribute records $0 rather than crashing."""

    class NoUsage:
        model = "claude-3-5-sonnet-20241022"

    with patch(ANTHROPIC_CREATE, return_value=NoUsage()):
        with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.Anthropic(api_key="test")
            client.messages.create(model="claude-3-5-sonnet-20241022", messages=[], max_tokens=10)

    assert b.spent == pytest.approx(0.0)


def test_anthropic_sync_wrapper_raises_if_no_original() -> None:
    """RuntimeError when anthropic_sync not in _originals."""
    from shekel._patch import _anthropic_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="anthropic original not stored"):
            _anthropic_sync_wrapper(None)


def test_wrap_anthropic_stream_swallows_message_start_attribute_error() -> None:
    """Broken message_start event is handled without crashing."""
    from shekel._patch import _wrap_anthropic_stream

    class BrokenMessage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageStartEvent:
        type = "message_start"
        message = BrokenMessage()

    list(_wrap_anthropic_stream(iter([MessageStartEvent()])))


def test_wrap_anthropic_stream_swallows_message_delta_attribute_error() -> None:
    """Broken message_delta event is handled without crashing."""
    from shekel._patch import _wrap_anthropic_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageDeltaEvent:
        type = "message_delta"
        usage = BrokenUsage()

    list(_wrap_anthropic_stream(iter([MessageDeltaEvent()])))


@pytest.mark.asyncio
async def test_anthropic_async_wrapper_raises_if_no_original() -> None:
    """RuntimeError when anthropic_async not in _originals."""
    from shekel._patch import _anthropic_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="anthropic async original not stored"):
            await _anthropic_async_wrapper(None)


@pytest.mark.asyncio
async def test_wrap_anthropic_stream_async_swallows_message_start_error() -> None:
    """Broken message_start in async stream is handled without crashing."""
    from shekel._patch import _wrap_anthropic_stream_async

    class BrokenMessage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageStartEvent:
        type = "message_start"
        message = BrokenMessage()

    async def stream():  # type: ignore[return]
        yield MessageStartEvent()

    async for _ in _wrap_anthropic_stream_async(stream()):
        pass


@pytest.mark.asyncio
async def test_wrap_anthropic_stream_async_swallows_message_delta_error() -> None:
    """Broken message_delta in async stream is handled without crashing."""
    from shekel._patch import _wrap_anthropic_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    class MessageDeltaEvent:
        type = "message_delta"
        usage = BrokenUsage()

    async def stream():  # type: ignore[return]
        yield MessageDeltaEvent()

    async for _ in _wrap_anthropic_stream_async(stream()):
        pass
