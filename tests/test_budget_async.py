from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shekel import BudgetExceededError, budget
from shekel._pricing import calculate_cost
from tests.conftest import (
    make_anthropic_response,
    make_openai_response,
    make_openai_stream,
)

OPENAI_ASYNC_CREATE = "openai.resources.chat.completions.AsyncCompletions.create"
ANTHROPIC_ASYNC_CREATE = "anthropic.resources.messages.AsyncMessages.create"


@pytest.mark.asyncio
async def test_async_openai_spend_tracked() -> None:
    fake = make_openai_response("gpt-4o", 500, 200)
    with patch(OPENAI_ASYNC_CREATE, new=AsyncMock(return_value=fake)):
        async with budget(max_usd=1.00) as b:
            import openai

            client = openai.AsyncOpenAI(api_key="test")
            await client.chat.completions.create(model="gpt-4o", messages=[])

    expected = calculate_cost("gpt-4o", 500, 200)
    assert b.spent == pytest.approx(expected)


@pytest.mark.asyncio
async def test_async_anthropic_spend_tracked() -> None:
    fake = make_anthropic_response("claude-3-haiku-20240307", 300, 100)
    with patch(ANTHROPIC_ASYNC_CREATE, new=AsyncMock(return_value=fake)):
        async with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key="test")
            await client.messages.create(
                model="claude-3-haiku-20240307", messages=[], max_tokens=100
            )

    expected = calculate_cost("claude-3-haiku-20240307", 300, 100)
    assert b.spent == pytest.approx(expected)


@pytest.mark.asyncio
async def test_async_budget_exceeded_raises() -> None:
    fake = make_openai_response("gpt-4o", 10000, 5000)
    with patch(OPENAI_ASYNC_CREATE, new=AsyncMock(return_value=fake)):
        with pytest.raises(BudgetExceededError):
            async with budget(max_usd=0.001) as b:
                import openai

                client = openai.AsyncOpenAI(api_key="test")
                await client.chat.completions.create(model="gpt-4o", messages=[])


@pytest.mark.asyncio
async def test_async_track_only_no_exception() -> None:
    fake = make_openai_response("gpt-4o", 500, 200)
    with patch(OPENAI_ASYNC_CREATE, new=AsyncMock(return_value=fake)):
        async with budget() as b:
            import openai

            client = openai.AsyncOpenAI(api_key="test")
            await client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.spent > 0.0
    assert b.limit is None


@pytest.mark.asyncio
async def test_async_streaming_full_consumption() -> None:
    chunks = make_openai_stream("gpt-4o", 500, 200)

    async def fake_async_stream(*args: object, **kwargs: object) -> object:
        # Return an async iterable
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
