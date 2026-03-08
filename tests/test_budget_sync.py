from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shekel import BudgetExceededError, budget
from shekel._pricing import calculate_cost
from tests.conftest import (
    make_anthropic_response,
    make_openai_response,
    make_openai_stream,
)

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"


# ---------------------------------------------------------------------------
# Basic spend tracking
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
# Track-only mode (max_usd=None)
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
# Budget exceeded
# ---------------------------------------------------------------------------


def test_budget_exceeded_raises() -> None:
    fake = make_openai_response("gpt-4o", 10000, 5000)  # large call
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


def test_budget_exceeded_str_format() -> None:
    err = BudgetExceededError(1.05, 1.00, "gpt-4o", {"input": 500, "output": 200})
    s = str(err)
    assert "exceeded" in s
    assert "gpt-4o" in s
    assert "Tip:" in s


# ---------------------------------------------------------------------------
# warn_at callback
# ---------------------------------------------------------------------------


def test_warn_at_fires_once() -> None:
    callback = MagicMock()
    # gpt-4o 5000 input + 2000 output = $0.0325
    # max_usd=0.05: warn fires at $0.025 (50%), budget not exceeded at $0.0325
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
    """AC16: _warn_fired prevents callback from firing more than once."""
    callback = MagicMock()
    # Small responses — each cheap, but accumulate past threshold
    fake = make_openai_response("gpt-4o-mini", 1000, 500)
    expected_per_call = calculate_cost("gpt-4o-mini", 1000, 500)
    # Set budget so 2nd call crosses warn threshold
    budget_limit = expected_per_call * 1.5  # warn at ~67%
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=budget_limit * 10, warn_at=0.1, on_exceed=callback):
            import openai

            client = openai.OpenAI(api_key="test")
            for _ in range(5):
                client.chat.completions.create(model="gpt-4o-mini", messages=[])

    callback.assert_called_once()


# ---------------------------------------------------------------------------
# Nested contexts
# ---------------------------------------------------------------------------


def test_nested_contexts_isolated() -> None:
    fake = make_openai_response("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=10.00) as outer:
            with budget(max_usd=5.00) as inner:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])
            # Inner call should only affect inner budget
            assert inner.spent > 0.0
            assert outer.spent == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Streaming — full consumption
# ---------------------------------------------------------------------------


def test_openai_stream_full_consumption() -> None:
    chunks = make_openai_stream("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=iter(chunks)):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
            list(stream)  # consume all chunks

    expected = calculate_cost("gpt-4o", 500, 200)
    assert b.spent == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Streaming — partial consumption (break)
# ---------------------------------------------------------------------------


def test_openai_stream_partial_consumption() -> None:
    chunks = make_openai_stream("gpt-4o", 500, 200)
    with patch(OPENAI_CREATE, return_value=iter(chunks)):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
            for i, _ in enumerate(stream):
                if i == 0:
                    break  # break after first chunk

    # try/finally should have recorded whatever usage was seen
    # (may be 0 if usage chunk not yet reached, but no crash)
    assert b.spent >= 0.0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_warn_at_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="warn_at must be a fraction"):
        budget(max_usd=1.00, warn_at=1.5)


def test_price_override_missing_output_raises() -> None:
    with pytest.raises(ValueError, match="price_per_1k_tokens"):
        budget(max_usd=1.00, price_per_1k_tokens={"input": 0.001})
