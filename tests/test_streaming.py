from __future__ import annotations

from unittest.mock import patch

import pytest

from shekel import budget
from shekel._pricing import calculate_cost
from tests.conftest import make_anthropic_stream, make_openai_stream

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
OPENAI_ASYNC_CREATE = "openai.resources.chat.completions.AsyncCompletions.create"
ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"
ANTHROPIC_ASYNC_CREATE = "anthropic.resources.messages.AsyncMessages.create"


class FakeSyncStream:
    """Iterable event stream — triggers Anthropic streaming path."""

    def __init__(self, events: list) -> None:
        self._events = events

    def __iter__(self):  # type: ignore[return]
        return iter(self._events)


class FakeAsyncStream:
    """Async iterable event stream."""

    def __init__(self, events: list) -> None:
        self._events = events

    def __aiter__(self):  # type: ignore[return]
        return self._aiter_impl()

    async def _aiter_impl(self):  # type: ignore[return]
        for e in self._events:
            yield e


# ---------------------------------------------------------------------------
# OpenAI streaming — sync
# ---------------------------------------------------------------------------


def test_openai_stream_full_consumption() -> None:
    chunks = make_openai_stream("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=iter(chunks)):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
            list(stream)

    expected = calculate_cost("gpt-4o", 500, 200)
    assert b.spent == pytest.approx(expected)


def test_openai_stream_partial_consumption() -> None:
    chunks = make_openai_stream("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=iter(chunks)):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
            for i, _ in enumerate(stream):
                if i == 0:
                    break

    assert b.spent >= 0.0


# ---------------------------------------------------------------------------
# OpenAI streaming — async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_async_stream_full_consumption() -> None:
    chunks = make_openai_stream("gpt-4o", 500, 200)

    async def fake_async_stream(*args: object, **kwargs: object) -> object:
        async def _gen() -> object:
            for chunk in chunks:
                yield chunk

        return _gen()

    with patch(OPENAI_ASYNC_CREATE, new=fake_async_stream):
        async with budget(max_usd=1.00) as b:
            import openai

            client = openai.AsyncOpenAI(api_key="test")
            stream = await client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
            async for _ in stream:
                pass

    expected = calculate_cost("gpt-4o", 500, 200)
    assert b.spent == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Anthropic streaming — sync
# ---------------------------------------------------------------------------


def test_anthropic_stream_full_consumption() -> None:
    events = make_anthropic_stream("claude-3-5-sonnet-20241022", 400, 150)
    fake_stream = FakeSyncStream(events)

    with patch(ANTHROPIC_CREATE, return_value=fake_stream):
        with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.Anthropic(api_key="test")
            stream = client.messages.create(
                model="claude-3-5-sonnet-20241022", messages=[], max_tokens=100
            )
            list(stream)

    expected = calculate_cost("claude-3-5-sonnet-20241022", 400, 150)
    assert b.spent == pytest.approx(expected)


def test_anthropic_stream_partial_consumption() -> None:
    events = make_anthropic_stream("claude-3-haiku-20240307", 200, 80)
    fake_stream = FakeSyncStream(events)

    with patch(ANTHROPIC_CREATE, return_value=fake_stream):
        with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.Anthropic(api_key="test")
            stream = client.messages.create(
                model="claude-3-haiku-20240307", messages=[], max_tokens=100
            )
            for i, _ in enumerate(stream):
                if i == 0:
                    break

    assert b.spent >= 0.0


# ---------------------------------------------------------------------------
# Anthropic streaming — async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_async_stream_full_consumption() -> None:
    events = make_anthropic_stream("claude-3-5-sonnet-20241022", 400, 150)
    fake_stream = FakeAsyncStream(events)

    async def fake_async_create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fake_stream

    with patch(ANTHROPIC_ASYNC_CREATE, new=fake_async_create):
        async with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key="test")
            stream = await client.messages.create(
                model="claude-3-5-sonnet-20241022", messages=[], max_tokens=100
            )
            async for _ in stream:
                pass

    expected = calculate_cost("claude-3-5-sonnet-20241022", 400, 150)
    assert b.spent == pytest.approx(expected)
