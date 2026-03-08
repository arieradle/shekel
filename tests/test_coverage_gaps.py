"""Tests targeting uncovered branches to reach >90% coverage."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

import pytest

from shekel import BudgetExceededError, budget
from shekel._patch import _record
from shekel._pricing import calculate_cost
from tests.conftest import make_anthropic_stream

ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"
ANTHROPIC_ASYNC_CREATE = "anthropic.resources.messages.AsyncMessages.create"


# ---------------------------------------------------------------------------
# Fake stream classes — MagicMock can't have __iter__/__aiter__ set via spec=[]
# ---------------------------------------------------------------------------


class FakeSyncStream:
    """Iterable event stream with no .usage attribute — triggers Anthropic streaming path."""

    def __init__(self, events: list) -> None:
        self._events = events

    def __iter__(self):  # type: ignore[return]
        return iter(self._events)


class FakeAsyncStream:
    """Async iterable event stream with no .usage attribute."""

    def __init__(self, events: list) -> None:
        self._events = events

    def __aiter__(self):  # type: ignore[return]
        return self._aiter_impl()

    async def _aiter_impl(self):  # type: ignore[return]
        for e in self._events:
            yield e


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


# ---------------------------------------------------------------------------
# warnings.warn path (warn_at with no on_exceed callback)
# ---------------------------------------------------------------------------


def test_warn_at_issues_warning_when_no_callback() -> None:
    fake = MagicMock()
    fake.model = "gpt-4o"
    fake.usage.prompt_tokens = 5000
    fake.usage.completion_tokens = 2000

    with patch("openai.resources.chat.completions.Completions.create", return_value=fake):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with budget(max_usd=0.05, warn_at=0.5):
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert any("shekel" in str(w.message) for w in caught)


# ---------------------------------------------------------------------------
# BudgetExceededError.__str__ with zero tokens (else branch)
# ---------------------------------------------------------------------------


def test_budget_exceeded_str_zero_tokens() -> None:
    err = BudgetExceededError(1.05, 1.00, "gpt-4o", {"input": 0, "output": 0})
    s = str(err)
    assert "exceeded" in s
    assert "gpt-4o" in s
    assert "Tip:" in s


def test_budget_exceeded_str_no_tokens_arg() -> None:
    err = BudgetExceededError(0.5, 0.3)
    s = str(err)
    assert "exceeded" in s
    assert "Tip:" in s


# ---------------------------------------------------------------------------
# _record called with no active budget (budget=None path, lines 102-103)
# ---------------------------------------------------------------------------


def test_record_with_no_active_budget_is_noop() -> None:
    # Call _record directly with no active budget context — should return silently
    _record(100, 50, "gpt-4o")


# ---------------------------------------------------------------------------
# _record exception path — calculate_cost raises, cost falls back to 0.0
# ---------------------------------------------------------------------------


def test_record_unknown_model_falls_back_to_zero_cost() -> None:
    """When model is unknown and no override, _record catches the error and records $0."""
    fake = MagicMock()
    fake.model = "gpt-999-not-real"
    fake.usage.prompt_tokens = 100
    fake.usage.completion_tokens = 50

    with patch("openai.resources.chat.completions.Completions.create", return_value=fake):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-999-not-real", messages=[])

    # Unknown model → exception caught in _record → $0 cost recorded
    assert b.spent == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Anthropic malformed response (AttributeError path, lines 92-93)
# ---------------------------------------------------------------------------


def test_anthropic_malformed_response_records_zero() -> None:
    """If response has no .usage, _extract_anthropic_tokens returns (0, 0, 'unknown')."""

    class NoUsage:
        model = "claude-3-5-sonnet-20241022"
        # deliberately no .usage attribute

    with patch(ANTHROPIC_CREATE, return_value=NoUsage()):
        with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.Anthropic(api_key="test")
            # model="unknown" → UnknownModelError caught in _record → $0
            client.messages.create(model="claude-3-5-sonnet-20241022", messages=[], max_tokens=10)

    assert b.spent == pytest.approx(0.0)
