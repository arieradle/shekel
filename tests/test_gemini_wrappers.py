"""Tests for Google Gemini provider wrappers in shekel/_patch.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shekel import budget


def test_gemini_sync_wrapper_raises_if_no_original() -> None:
    """RuntimeError when gemini_sync not in _originals."""
    from shekel._patch import _gemini_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="gemini original not stored"):
            _gemini_sync_wrapper(None)


def test_gemini_sync_wrapper_records_tokens() -> None:
    """Wrapper records token counts through an active budget."""
    from shekel._patch import _gemini_sync_wrapper

    class MockUsage:
        prompt_token_count = 100
        candidates_token_count = 50

    class MockResponse:
        usage_metadata = MockUsage()

    def fake_sync(self: object, *args: object, **kwargs: object) -> MockResponse:
        return MockResponse()

    def fake_stream(self: object, *args: object, **kwargs: object) -> MockResponse:
        return MockResponse()

    # Include both gemini_sync and gemini_stream so install_patches() skips re-install
    with patch.dict(
        "shekel._patch._originals",
        {"gemini_sync": fake_sync, "gemini_stream": fake_stream},
    ):
        with budget(max_usd=1.0) as b:
            result = _gemini_sync_wrapper(None, model="gemini-2.0-flash")

    assert isinstance(result, MockResponse)
    assert b.spent > 0


def test_gemini_sync_wrapper_no_budget() -> None:
    """Wrapper works correctly when no budget context is active."""
    from shekel._patch import _gemini_sync_wrapper

    class MockUsage:
        prompt_token_count = 10
        candidates_token_count = 5

    class MockResponse:
        usage_metadata = MockUsage()

    def fake_original(self: object, *args: object, **kwargs: object) -> MockResponse:
        return MockResponse()

    with patch.dict("shekel._patch._originals", {"gemini_sync": fake_original}):
        result = _gemini_sync_wrapper(None, model="gemini-2.0-flash")

    assert isinstance(result, MockResponse)


def test_gemini_stream_wrapper_raises_if_no_original() -> None:
    """RuntimeError when gemini_stream not in _originals."""
    from shekel._patch import _gemini_stream_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="gemini stream original not stored"):
            list(_gemini_stream_wrapper(None))


def test_gemini_stream_wrapper_yields_chunks() -> None:
    """Stream wrapper yields all chunks from the underlying generator."""
    from shekel._patch import _gemini_stream_wrapper

    class MockChunk:
        usage_metadata = None

    def fake_sync(self: object, *args: object, **kwargs: object) -> None:
        return None

    def fake_stream(self: object, *args: object, **kwargs: object):  # type: ignore[return]
        yield MockChunk()
        yield MockChunk()

    # Include both keys so budget's install_patches() skips re-installing
    with patch.dict(
        "shekel._patch._originals",
        {"gemini_sync": fake_sync, "gemini_stream": fake_stream},
    ):
        with budget(max_usd=1.0):
            chunks = list(_gemini_stream_wrapper(None, model="gemini-2.0-flash"))

    assert len(chunks) == 2


def test_wrap_gemini_stream_swallows_usage_attribute_error() -> None:
    """Chunk whose usage_metadata attrs raise AttributeError is skipped."""
    from shekel._patch import _wrap_gemini_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage_metadata = BrokenUsage()
        yield chunk

    list(_wrap_gemini_stream(stream(), "gemini-2.0-flash"))  # must not raise


def test_wrap_gemini_stream_records_usage() -> None:
    """usage_metadata tokens are captured and charged to the active budget."""
    from shekel._patch import _wrap_gemini_stream

    class MockUsage:
        prompt_token_count = 50
        candidates_token_count = 25

    class MockChunk:
        usage_metadata = MockUsage()

    def stream():  # type: ignore[return]
        yield MockChunk()

    # Include both gemini keys so install_patches() is skipped inside budget context
    with patch.dict(
        "shekel._patch._originals",
        {"gemini_sync": object(), "gemini_stream": object()},
    ):
        with budget(max_usd=1.0) as b:
            list(_wrap_gemini_stream(stream(), "gemini-2.0-flash"))

    assert b.spent > 0


def test_extract_gemini_tokens_attribute_error() -> None:
    """Response with no attributes returns (0, 0, 'unknown')."""
    from shekel._patch import _extract_gemini_tokens

    response = MagicMock(spec=[])  # no attributes
    assert _extract_gemini_tokens(response) == (0, 0, "unknown")


def test_extract_gemini_tokens_none_usage() -> None:
    """response.usage_metadata is None returns (0, 0, 'unknown')."""
    from shekel._patch import _extract_gemini_tokens

    response = MagicMock()
    response.usage_metadata = None
    assert _extract_gemini_tokens(response) == (0, 0, "unknown")
