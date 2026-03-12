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


# ---------------------------------------------------------------------------
# _validate_same_provider — gemini / huggingface branches (lines 77, 83)
# ---------------------------------------------------------------------------


def test_validate_same_provider_gemini_rejects_non_gemini():
    """Line 77: gemini provider + non-gemini fallback raises ValueError."""
    from shekel._patch import _validate_same_provider

    with pytest.raises(ValueError, match="Gemini"):
        _validate_same_provider("gpt-4o", "gemini")


def test_validate_same_provider_huggingface_rejects_openai():
    """Line 83: huggingface provider + openai fallback raises ValueError."""
    from shekel._patch import _validate_same_provider

    with pytest.raises(ValueError, match="HuggingFace"):
        _validate_same_provider("gpt-4o", "huggingface")


def test_validate_same_provider_huggingface_rejects_anthropic():
    """Line 83: huggingface provider + anthropic fallback raises ValueError."""
    from shekel._patch import _validate_same_provider

    with pytest.raises(ValueError, match="HuggingFace"):
        _validate_same_provider("claude-3-haiku-20240307", "huggingface")


def test_validate_same_provider_huggingface_rejects_gemini():
    """Line 83: huggingface provider + gemini fallback raises ValueError."""
    from shekel._patch import _validate_same_provider

    with pytest.raises(ValueError, match="HuggingFace"):
        _validate_same_provider("gemini-2.0-flash", "huggingface")


# ---------------------------------------------------------------------------
# _gemini_sync_wrapper (lines 442-458)
# ---------------------------------------------------------------------------


def test_gemini_sync_wrapper_raises_if_no_original():
    """Line 444: RuntimeError when gemini_sync not in _originals."""
    from shekel._patch import _gemini_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="gemini original not stored"):
            _gemini_sync_wrapper(None)


def test_gemini_sync_wrapper_records_tokens():
    """Lines 447-458: wrapper records tokens through an active budget."""
    from shekel import budget
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


def test_gemini_sync_wrapper_no_budget():
    """Lines 447-458: wrapper works with no active budget context."""
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


# ---------------------------------------------------------------------------
# _gemini_stream_wrapper (lines 462-474)
# ---------------------------------------------------------------------------


def test_gemini_stream_wrapper_raises_if_no_original():
    """Line 464: RuntimeError when gemini_stream not in _originals."""
    from shekel._patch import _gemini_stream_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="gemini stream original not stored"):
            list(_gemini_stream_wrapper(None))


def test_gemini_stream_wrapper_yields_chunks():
    """Lines 466-474: stream wrapper yields chunks from the original generator."""
    from shekel import budget
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


# ---------------------------------------------------------------------------
# _wrap_gemini_stream (lines 478-495)
# ---------------------------------------------------------------------------


def test_wrap_gemini_stream_swallows_usage_attribute_error():
    """Lines 487-488: chunk whose usage_metadata attrs raise AttributeError is handled."""
    from shekel._patch import _wrap_gemini_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage_metadata = BrokenUsage()
        yield chunk

    list(_wrap_gemini_stream(stream(), "gemini-2.0-flash"))  # must not raise


def test_wrap_gemini_stream_records_usage():
    """Lines 484-486: usage_metadata tokens are captured and recorded."""
    from shekel import budget
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


# ---------------------------------------------------------------------------
# _extract_gemini_tokens (lines 499-507)
# ---------------------------------------------------------------------------


def test_extract_gemini_tokens_attribute_error():
    """Lines 506-507: response with no attributes returns (0, 0, 'unknown')."""
    from shekel._patch import _extract_gemini_tokens

    response = MagicMock(spec=[])  # no attributes
    assert _extract_gemini_tokens(response) == (0, 0, "unknown")


def test_extract_gemini_tokens_none_usage():
    """Lines 501-502: response.usage_metadata is None returns (0, 0, 'unknown')."""
    from shekel._patch import _extract_gemini_tokens

    response = MagicMock()
    response.usage_metadata = None
    assert _extract_gemini_tokens(response) == (0, 0, "unknown")


# ---------------------------------------------------------------------------
# _huggingface_sync_wrapper (lines 516-531)
# ---------------------------------------------------------------------------


def test_huggingface_sync_wrapper_raises_if_no_original():
    """Line 518: RuntimeError when huggingface_sync not in _originals."""
    from shekel._patch import _huggingface_sync_wrapper

    with patch("shekel._patch._originals", {}):
        with pytest.raises(RuntimeError, match="huggingface original not stored"):
            _huggingface_sync_wrapper(None)


def test_huggingface_sync_wrapper_records_tokens():
    """Lines 520-531: non-stream path records tokens through active budget."""
    from shekel import budget
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


def test_huggingface_sync_wrapper_stream_path():
    """Lines 524-526: stream=True returns a generator."""
    from shekel._patch import _huggingface_sync_wrapper

    class MockChunk:
        usage = None

    def fake_original(self: object, *args: object, **kwargs: object):  # type: ignore[return]
        yield MockChunk()

    with patch.dict("shekel._patch._originals", {"huggingface_sync": fake_original}):
        gen = _huggingface_sync_wrapper(None, stream=True)
        chunks = list(gen)

    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# _wrap_huggingface_stream (lines 535-550)
# ---------------------------------------------------------------------------


def test_wrap_huggingface_stream_swallows_usage_attribute_error():
    """Lines 545-546: chunk whose usage attrs raise AttributeError is handled."""
    from shekel._patch import _wrap_huggingface_stream

    class BrokenUsage:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(name)

    def stream():  # type: ignore[return]
        chunk = MagicMock()
        chunk.usage = BrokenUsage()
        yield chunk

    list(_wrap_huggingface_stream(stream()))  # must not raise


def test_wrap_huggingface_stream_records_usage():
    """Lines 541-544: usage tokens are captured and recorded."""
    from shekel import budget
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
    with patch.dict("shekel._patch._originals", {"huggingface_sync": object()}):
        with budget(max_usd=1.0, price_per_1k_tokens={"input": 0.001, "output": 0.001}) as b:
            list(_wrap_huggingface_stream(stream()))

    assert b.spent > 0
