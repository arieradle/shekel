from __future__ import annotations

import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shekel import BudgetExceededError, budget
from shekel._pricing import calculate_cost
from tests.conftest import (
    make_anthropic_response,
    make_openai_response,
)

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
OPENAI_ASYNC_CREATE = "openai.resources.chat.completions.AsyncCompletions.create"
ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"
ANTHROPIC_ASYNC_CREATE = "anthropic.resources.messages.AsyncMessages.create"


# ---------------------------------------------------------------------------
# Basic spend tracking — sync
# ---------------------------------------------------------------------------


def test_openai_spend_tracked() -> None:
    fake = make_openai_response("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o", messages=[])

    expected = calculate_cost("gpt-4o", 500, 200)
    assert b.spent == pytest.approx(expected)
    assert b.remaining == pytest.approx(1.00 - expected)


def test_anthropic_spend_tracked() -> None:
    fake = make_anthropic_response("claude-3-5-sonnet-20241022", 400, 150)
    with patch(ANTHROPIC_CREATE, return_value=fake):
        with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.Anthropic(api_key="test")
            client.messages.create(model="claude-3-5-sonnet-20241022", messages=[], max_tokens=100)

    expected = calculate_cost("claude-3-5-sonnet-20241022", 400, 150)
    assert b.spent == pytest.approx(expected)


def test_remaining_decrements() -> None:
    fake = make_openai_response("gpt-4o-mini", 1000, 500)
    expected = calculate_cost("gpt-4o-mini", 1000, 500)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o-mini", messages=[])
    assert b.remaining == pytest.approx(1.00 - expected)


# ---------------------------------------------------------------------------
# Track-only mode
# ---------------------------------------------------------------------------


def test_track_only_no_exception() -> None:
    fake = make_openai_response("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget() as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o", messages=[])
    assert b.spent > 0.0
    assert b.limit is None
    assert b.remaining is None


# ---------------------------------------------------------------------------
# Budget exceeded — sync
# ---------------------------------------------------------------------------


def test_budget_exceeded_raises() -> None:
    fake = make_openai_response("gpt-4o", 10000, 5000)
    with patch(OPENAI_CREATE, return_value=fake):
        with pytest.raises(BudgetExceededError) as exc_info:
            with budget(max_usd=0.001):
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])

    err = exc_info.value
    assert err.spent > 0.001
    assert err.limit == pytest.approx(0.001)
    assert err.model == "gpt-4o"
    assert "input" in err.tokens
    assert "output" in err.tokens


# ---------------------------------------------------------------------------
# warn_at
# ---------------------------------------------------------------------------


def test_warn_at_fires_once() -> None:
    callback = MagicMock()
    fake = make_openai_response("gpt-4o", 5000, 2000)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=0.05, warn_at=0.5, on_exceed=callback):
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o", messages=[])

    callback.assert_called_once()
    spent_arg, limit_arg = callback.call_args[0]
    assert spent_arg >= 0.05 * 0.5
    assert limit_arg == pytest.approx(0.05)


def test_warn_at_fires_only_once_across_multiple_calls() -> None:
    callback = MagicMock()
    fake = make_openai_response("gpt-4o-mini", 1000, 500)
    expected_per_call = calculate_cost("gpt-4o-mini", 1000, 500)
    budget_limit = expected_per_call * 1.5
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=budget_limit * 10, warn_at=0.1, on_exceed=callback):
            import openai

            client = openai.OpenAI(api_key="test")
            for _ in range(5):
                client.chat.completions.create(model="gpt-4o-mini", messages=[])

    callback.assert_called_once()


def test_warn_at_issues_warning_when_no_callback() -> None:
    fake = MagicMock()
    fake.model = "gpt-4o"
    fake.usage.prompt_tokens = 5000
    fake.usage.completion_tokens = 2000

    with patch(OPENAI_CREATE, return_value=fake):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with budget(max_usd=0.05, warn_at=0.5):
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert any("shekel" in str(w.message) for w in caught)


# ---------------------------------------------------------------------------
# Nested contexts
# ---------------------------------------------------------------------------


def test_nested_contexts_propagate() -> None:
    """v0.2.3: Nested contexts now have parent/child relationship."""
    fake = make_openai_response("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=10.00, name="outer") as outer:
            with budget(max_usd=5.00, name="inner") as inner:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])
            assert inner.spent > 0.0
            # NEW in v0.2.3: outer receives propagated spend from inner
            assert outer.spent == pytest.approx(inner.spent)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_warn_at_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="warn_at must be a fraction"):
        budget(max_usd=1.00, warn_at=1.5)


def test_price_override_missing_output_raises() -> None:
    with pytest.raises(ValueError, match="price_per_1k_tokens"):
        budget(max_usd=1.00, price_per_1k_tokens={"input": 0.001})


# ---------------------------------------------------------------------------
# Basic spend tracking — async
# ---------------------------------------------------------------------------


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
            async with budget(max_usd=0.001):
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
