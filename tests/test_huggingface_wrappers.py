"""Tests for HuggingFace provider wrappers in shekel/_patch.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shekel import budget


def test_huggingface_sync_wrapper_raises_if_no_original() -> None:
    """RuntimeError when huggingface_sync not in _originals."""
    from shekel._patch import _huggingface_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="huggingface original not stored"):
            _huggingface_sync_wrapper(None)


def test_huggingface_sync_wrapper_records_tokens() -> None:
    """Non-streaming path extracts tokens and charges the active budget."""
    from shekel._patch import _huggingface_sync_wrapper

    class MockUsage:
        prompt_tokens = 80
        completion_tokens = 40

    class MockResponse:
        model = "HuggingFaceH4/zephyr-7b-beta"
        usage = MockUsage()

    def fake_original(self: object, *args: object, **kwargs: object) -> MockResponse:
        return MockResponse()

    # Include the key so install_patches() skips re-install inside budget context
    with patch.dict("shekel._patch._originals", {"huggingface_sync": fake_original}):
        with budget(max_usd=1.0, price_per_1k_tokens={"input": 0.001, "output": 0.001}) as b:
            result = _huggingface_sync_wrapper(None)

    assert isinstance(result, MockResponse)
    assert b.spent > 0


def test_huggingface_sync_wrapper_stream_path() -> None:
    """stream=True delegates to the streaming path and returns a generator."""
    from shekel._patch import _huggingface_sync_wrapper

    class MockChunk:
        usage = None

    def fake_original(self: object, *args: object, **kwargs: object):  # type: ignore[return]
        yield MockChunk()

    with patch.dict("shekel._patch._originals", {"huggingface_sync": fake_original}):
        gen = _huggingface_sync_wrapper(None, stream=True)
        chunks = list(gen)

    assert len(chunks) == 1


def test_wrap_huggingface_stream_swallows_usage_attribute_error() -> None:
    """Chunk whose usage attrs raise AttributeError is skipped without crashing."""
    from shekel._patch import _wrap_huggingface_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    list(_wrap_huggingface_stream(stream()))  # must not raise


def test_wrap_huggingface_stream_records_usage() -> None:
    """Usage tokens from streaming chunks are charged to the active budget."""
    from shekel._patch import _wrap_huggingface_stream

    class MockUsage:
        prompt_tokens = 60
        completion_tokens = 30

    class MockChunk:
        model = "HuggingFaceH4/zephyr-7b-beta"
        usage = MockUsage()

    def stream():  # type: ignore[return]
        yield MockChunk()

    # Prevent install_patches() from overwriting _originals inside budget context
    with patch.dict(
        "shekel._patch._originals", {"huggingface_sync": object(), "huggingface_async": object()}
    ):
        with budget(max_usd=1.0, price_per_1k_tokens={"input": 0.001, "output": 0.001}) as b:
            list(_wrap_huggingface_stream(stream()))

    assert b.spent > 0


@pytest.mark.asyncio
async def test_huggingface_async_wrapper_raises_if_no_original() -> None:
    """RuntimeError when huggingface_async not in _originals."""
    from shekel._patch import _huggingface_async_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="huggingface async original not stored"):
            await _huggingface_async_wrapper(None)


@pytest.mark.asyncio
async def test_huggingface_async_wrapper_records_tokens() -> None:
    """Non-streaming async path extracts tokens and charges the active budget."""
    from shekel._patch import _huggingface_async_wrapper

    class MockUsage:
        prompt_tokens = 80
        completion_tokens = 40

    class MockResponse:
        model = "HuggingFaceH4/zephyr-7b-beta"
        usage = MockUsage()

    async def fake_async(self: object, *args: object, **kwargs: object) -> MockResponse:
        return MockResponse()

    both_keys = {"huggingface_sync": object(), "huggingface_async": fake_async}
    with patch.dict("shekel._patch._originals", both_keys):
        async with budget(max_usd=1.0, price_per_1k_tokens={"input": 0.001, "output": 0.001}) as b:
            result = await _huggingface_async_wrapper(None)

    assert isinstance(result, MockResponse)
    assert b.spent > 0


@pytest.mark.asyncio
async def test_huggingface_async_wrapper_no_budget() -> None:
    """Async wrapper works correctly when no budget context is active."""
    from shekel._patch import _huggingface_async_wrapper

    class MockUsage:
        prompt_tokens = 10
        completion_tokens = 5

    class MockResponse:
        model = "HuggingFaceH4/zephyr-7b-beta"
        usage = MockUsage()

    async def fake_async(self: object, *args: object, **kwargs: object) -> MockResponse:
        return MockResponse()

    with patch.dict("shekel._patch._originals", {"huggingface_async": fake_async}):
        result = await _huggingface_async_wrapper(None)

    assert isinstance(result, MockResponse)


@pytest.mark.asyncio
async def test_huggingface_async_wrapper_stream_path() -> None:
    """stream=True delegates to the async streaming path and returns an async generator."""
    from shekel._patch import _huggingface_async_wrapper

    class MockChunk:
        usage = None

    async def fake_async_stream(self: object, *args: object, **kwargs: object):  # type: ignore[return]
        yield MockChunk()

    async def fake_async(self: object, *args: object, **kwargs: object):  # type: ignore[return]
        # When stream=True, HF async returns an async iterable after await
        return fake_async_stream(self)

    both_keys = {"huggingface_sync": object(), "huggingface_async": fake_async}
    with patch.dict("shekel._patch._originals", both_keys):
        gen = await _huggingface_async_wrapper(None, stream=True)
        chunks = [c async for c in gen]

    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_wrap_huggingface_stream_async_records_usage() -> None:
    """Usage tokens from async streaming chunks are charged to the active budget."""
    from shekel._patch import _wrap_huggingface_stream_async

    class MockUsage:
        prompt_tokens = 60
        completion_tokens = 30

    class MockChunk:
        model = "HuggingFaceH4/zephyr-7b-beta"
        usage = MockUsage()

    async def stream():  # type: ignore[return]
        yield MockChunk()

    both_keys = {"huggingface_sync": object(), "huggingface_async": object()}
    with patch.dict("shekel._patch._originals", both_keys):
        async with budget(max_usd=1.0, price_per_1k_tokens={"input": 0.001, "output": 0.001}) as b:
            async for _ in _wrap_huggingface_stream_async(stream()):
                pass

    assert b.spent > 0


@pytest.mark.asyncio
async def test_wrap_huggingface_stream_async_swallows_attribute_error() -> None:
    """Broken usage in async stream chunk is handled without crashing."""
    from shekel._patch import _wrap_huggingface_stream_async

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    async def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    async for _ in _wrap_huggingface_stream_async(stream()):
        pass  # must not raise
