"""Tests for Call Limits feature (max_llm_calls).

Tests the counter, enforcement, fallback activation at percentage,
nested budgets, and streaming behavior.
"""

from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from shekel import BudgetExceededError, budget
from tests.conftest import (
    make_openai_response,
    make_openai_stream,
)

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"


# ---------------------------------------------------------------------------
# Basic call counting
# ---------------------------------------------------------------------------


def test_call_counter_increments() -> None:
    """Each LLM call increments the counter."""
    fake1 = make_openai_response("gpt-4o", 100, 50)
    fake2 = make_openai_response("gpt-4o", 100, 50)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake1
        return fake2

    with patch(OPENAI_CREATE, new=fake_create):
        with budget(max_llm_calls=10) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o", messages=[])
            assert b.calls_used == 1
            client.chat.completions.create(model="gpt-4o", messages=[])
            assert b.calls_used == 2


def test_calls_used_and_remaining() -> None:
    """calls_used and calls_remaining track correctly."""
    fake = make_openai_response("gpt-4o", 100, 50)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_llm_calls=10) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            assert b.calls_used == 0
            assert b.calls_remaining == 10

            client.chat.completions.create(model="gpt-4o", messages=[])
            assert b.calls_used == 1
            assert b.calls_remaining == 9


# ---------------------------------------------------------------------------
# Call limit enforcement
# ---------------------------------------------------------------------------


def test_call_limit_enforced() -> None:
    """BudgetExceededError raised when max_llm_calls exceeded."""
    fake = make_openai_response("gpt-4o", 100, 50)
    with patch(OPENAI_CREATE, return_value=fake):
        with pytest.raises(BudgetExceededError):
            with budget(max_llm_calls=2) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])  # Call 1
                client.chat.completions.create(model="gpt-4o", messages=[])  # Call 2
                # Call 3 should fail
                client.chat.completions.create(model="gpt-4o", messages=[])


def test_call_limit_with_usd_limit() -> None:
    """Both max_usd and max_llm_calls enforced; whichever is tighter."""
    fake = make_openai_response("gpt-4o", 100, 50)
    with patch(OPENAI_CREATE, return_value=fake):
        # USD limit will be hit first (each call is expensive)
        with pytest.raises(BudgetExceededError):
            with budget(max_usd=0.001, max_llm_calls=100) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])


# ---------------------------------------------------------------------------
# Fallback activation at percentage
# ---------------------------------------------------------------------------


def test_fallback_activates_at_percentage() -> None:
    """Fallback activates when reaching fallback_at_pct of tighter limit."""
    fake_expensive = make_openai_response("gpt-4o", 10_000, 5_000)
    fake_cheap = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0
    captured_models: list[str] = []

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        captured_models.append(str(kwargs.get("model", "")))
        if call_count <= 8:
            return fake_expensive
        return fake_cheap

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=10.00,
                max_llm_calls=10,
                fallback="gpt-4o-mini",
                fallback_at_pct=0.80,
                hard_cap=50.00,  # Prevent hard_cap from triggering
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                # Calls 1-8: expensive model, approaching 80% of calls (8 calls = 80% of 10)
                for i in range(8):
                    client.chat.completions.create(model="gpt-4o", messages=[])

                assert not b.model_switched, "Should not have switched yet at call 8"

                # Call 9: Should trigger fallback at 80% threshold
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.model_switched is True
    # Call 9 should be rewritten to fallback model
    assert captured_models[8] == "gpt-4o-mini"


def test_fallback_at_pct_validation() -> None:
    """fallback_at_pct must be between 0 and 1."""
    with pytest.raises(ValueError):
        budget(max_llm_calls=10, fallback="gpt-3.5", fallback_at_pct=1.5)

    with pytest.raises(ValueError):
        budget(max_llm_calls=10, fallback="gpt-3.5", fallback_at_pct=0.0)

    with pytest.raises(ValueError):
        budget(max_llm_calls=10, fallback="gpt-3.5", fallback_at_pct=-0.5)

    # Valid values should not raise
    budget(max_llm_calls=10, fallback="gpt-3.5", fallback_at_pct=0.80)
    budget(max_llm_calls=10, fallback="gpt-3.5", fallback_at_pct=1.0)
    budget(max_llm_calls=10, fallback="gpt-3.5", fallback_at_pct=0.1)


# ---------------------------------------------------------------------------
# Nested call limits
# ---------------------------------------------------------------------------


def test_nested_call_limit_auto_caps() -> None:
    """Child call limit auto-caps to parent's remaining."""
    fake = make_openai_response("gpt-4o", 100, 50)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_llm_calls=20, name="parent") as parent:
            import openai

            client = openai.OpenAI(api_key="test")
            # Make 15 calls in parent context
            for _ in range(15):
                client.chat.completions.create(model="gpt-4o", messages=[])

            # Parent has 5 calls remaining
            assert parent.calls_remaining == 5

            # Child requests 10 calls, but auto-caps to parent's remaining (5)
            with budget(max_llm_calls=10, name="child") as child:
                assert child.calls_remaining == 5  # Auto-capped to parent's remaining

                # Child can make up to 5 calls
                for _ in range(5):
                    client.chat.completions.create(model="gpt-4o", messages=[])
                assert child.calls_used == 5

            # Parent should reflect the child's spend
            assert parent.calls_used == 20


def test_nested_call_limits_propagate_to_parent() -> None:
    """Child's call spend propagates to parent on exit."""
    fake = make_openai_response("gpt-4o", 100, 50)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_llm_calls=30, name="parent") as parent:
            import openai

            client = openai.OpenAI(api_key="test")

            with budget(max_llm_calls=10, name="child") as child:
                for _ in range(8):
                    client.chat.completions.create(model="gpt-4o", messages=[])

            # Parent should know about child's 8 calls
            assert parent.calls_used == 8


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def test_streaming_counted_as_one_call() -> None:
    """Streaming call counts as 1 call, not N chunks."""
    stream_chunks = make_openai_stream("gpt-4o", 10_000, 5_000)
    with patch(OPENAI_CREATE, return_value=iter(stream_chunks)):
        with budget(max_llm_calls=2) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            # Stream is 1 call
            stream = client.chat.completions.create(
                model="gpt-4o", messages=[], stream=True
            )
            list(stream)  # Consume stream
            assert b.calls_used == 1
            assert b.calls_remaining == 1


# ---------------------------------------------------------------------------
# Interaction with max_usd
# ---------------------------------------------------------------------------


def test_min_of_both_limits() -> None:
    """Fallback triggers at min(max_usd, max_llm_calls) threshold."""
    # Setup: max_usd = 10.0, max_llm_calls = 20
    # 80% of max_usd = 8.0 USD
    # 80% of max_llm_calls = 16 calls
    # min(8.0, 16) = 8.0 USD will be reached first
    fake_expensive = make_openai_response("gpt-4o", 10_000, 5_000)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        return fake_expensive

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=10.00,
                max_llm_calls=20,
                fallback="gpt-4o-mini",
                fallback_at_pct=0.80,
                hard_cap=50.00,
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                # Make expensive calls until USD threshold is hit
                for i in range(5):
                    client.chat.completions.create(model="gpt-4o", messages=[])
                    if b.model_switched:
                        break

    assert b.model_switched is True
