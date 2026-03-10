"""Tests for F2 — Session (Persistent) Budgets."""

from __future__ import annotations

import asyncio
import warnings
from unittest.mock import patch

import pytest

from shekel import budget
from shekel._pricing import calculate_cost
from tests.conftest import make_openai_response

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
ASYNC_OPENAI_CREATE = "openai.resources.chat.completions.AsyncCompletions.create"


# ---------------------------------------------------------------------------
# test_non_persistent_resets_on_entry
# ---------------------------------------------------------------------------


def test_budget_accumulates_across_entries() -> None:
    """v0.2.3: Budget variables now accumulate across multiple entries."""
    fake = make_openai_response("gpt-4o", 500, 200)
    b = budget(max_usd=1.00)

    with patch(OPENAI_CREATE, return_value=fake):
        with b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o", messages=[])
        spent_after_first = b.spent
        assert spent_after_first > 0.0

        # Second entry — spend should accumulate, not reset (NEW in v0.2.3)
        with b:
            assert b.spent == pytest.approx(spent_after_first)
            client.chat.completions.create(model="gpt-4o", messages=[])

        spent_after_second = b.spent
        assert spent_after_second == pytest.approx(spent_after_first * 2)


# ---------------------------------------------------------------------------
# test_persistent_accumulates
# ---------------------------------------------------------------------------


def test_persistent_accumulates() -> None:
    """persistent=True: spend accumulates across 3 entries."""
    fake = make_openai_response("gpt-4o", 500, 200)
    expected_per_call = calculate_cost("gpt-4o", 500, 200)
    session = budget(max_usd=5.00, persistent=True)

    with patch(OPENAI_CREATE, return_value=fake):
        import openai

        client = openai.OpenAI(api_key="test")
        for _ in range(3):
            with session:
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert session.spent == pytest.approx(expected_per_call * 3)


# ---------------------------------------------------------------------------
# test_persistent_remaining_decreases
# ---------------------------------------------------------------------------


def test_persistent_remaining_decreases() -> None:
    """remaining decreases correctly across entries."""
    fake = make_openai_response("gpt-4o", 500, 200)
    expected_per_call = calculate_cost("gpt-4o", 500, 200)
    session = budget(max_usd=5.00, persistent=True)

    with patch(OPENAI_CREATE, return_value=fake):
        import openai

        client = openai.OpenAI(api_key="test")
        for i in range(3):
            with session:
                client.chat.completions.create(model="gpt-4o", messages=[])
            assert session.remaining == pytest.approx(5.00 - expected_per_call * (i + 1))


# ---------------------------------------------------------------------------
# test_persistent_fallback_carries_over
# ---------------------------------------------------------------------------


def test_persistent_fallback_carries_over() -> None:
    """Once switched in entry 1, fallback active in entry 2."""
    big = make_openai_response("gpt-4o", 10_000, 5_000)
    small = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0
    captured: list[str] = []

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        captured.append(str(kwargs.get("model", "")))
        if call_count == 1:
            return big
        return small

    session = budget(max_usd=0.001, fallback="gpt-4o-mini", persistent=True, hard_cap=10.0)

    with patch(OPENAI_CREATE, new=fake_create):
        import openai

        client = openai.OpenAI(api_key="test")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with session:
                client.chat.completions.create(model="gpt-4o", messages=[])
            # After first entry, switch should have activated
            assert session.model_switched is True

            # Second entry — should still be using fallback
            with session:
                client.chat.completions.create(model="gpt-4o", messages=[])

    # Second call should have been rewritten to fallback
    assert captured[1] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# test_warn_fires_once_across_entries
# ---------------------------------------------------------------------------


def test_warn_fires_once_across_entries() -> None:
    """warn_at fires exactly once even across multiple entries."""
    warn_count = 0

    def on_warn(spent: float, limit: float) -> None:
        nonlocal warn_count
        warn_count += 1

    # gpt-4o: $0.0025/1k input, $0.010/1k output
    # 5000 input + 2000 output = $0.0125 + $0.020 = $0.0325 per call
    # limit = $0.50, warn_at = 0.05 → threshold = $0.025
    # Call 1: $0.0325 — above threshold → warn fires
    # Calls 2-5: above threshold, but warn already fired
    fake = make_openai_response("gpt-4o", 5000, 2000)
    session = budget(max_usd=0.50, warn_at=0.05, on_exceed=on_warn, persistent=True)

    with patch(OPENAI_CREATE, return_value=fake):
        import openai

        client = openai.OpenAI(api_key="test")
        for _ in range(5):
            with session:
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert warn_count == 1


# ---------------------------------------------------------------------------
# test_reset_clears_state
# ---------------------------------------------------------------------------


def test_reset_clears_state() -> None:
    """reset() sets spent=0, clears _using_fallback, etc."""
    fake = make_openai_response("gpt-4o", 10_000, 5_000)
    session = budget(max_usd=0.001, fallback="gpt-4o-mini", persistent=True, hard_cap=10.0)

    with patch(OPENAI_CREATE, return_value=fake):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with session:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert session.spent > 0.0
    assert session.model_switched is True

    session.reset()

    assert session.spent == pytest.approx(0.0)
    assert session.model_switched is False
    assert session.switched_at_usd is None
    assert session.fallback_spent == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# test_reset_inside_block_raises
# ---------------------------------------------------------------------------


def test_reset_inside_block_raises() -> None:
    """reset() inside with session: raises RuntimeError."""
    session = budget(max_usd=1.00, persistent=True)
    with pytest.raises(RuntimeError, match="cannot be called inside an active with-block"):
        with session:
            session.reset()


# ---------------------------------------------------------------------------
# test_persistent_async
# ---------------------------------------------------------------------------


def test_persistent_async() -> None:
    """Async context manager accumulates correctly."""
    fake = make_openai_response("gpt-4o", 500, 200)
    expected_per_call = calculate_cost("gpt-4o", 500, 200)
    session = budget(max_usd=5.00, persistent=True)

    async def run() -> None:
        async def fake_create_async(self: object, *args: object, **kwargs: object) -> object:
            return fake

        with patch(ASYNC_OPENAI_CREATE, new=fake_create_async):
            import openai

            client = openai.AsyncOpenAI(api_key="test")
            for _ in range(3):
                async with session:
                    await client.chat.completions.create(model="gpt-4o", messages=[])

    asyncio.get_event_loop().run_until_complete(run())
    assert session.spent == pytest.approx(expected_per_call * 3)


# ---------------------------------------------------------------------------
# test_persistent_false_is_default
# ---------------------------------------------------------------------------


def test_budget_always_accumulates() -> None:
    """v0.2.3: All budgets accumulate (persistent flag is deprecated)."""
    fake = make_openai_response("gpt-4o", 500, 200)
    b = budget(max_usd=1.00)
    assert b.persistent is False  # Default value

    with patch(OPENAI_CREATE, return_value=fake):
        import openai

        client = openai.OpenAI(api_key="test")
        with b:
            client.chat.completions.create(model="gpt-4o", messages=[])
        first_spent = b.spent

        # v0.2.3: Now accumulates instead of resetting
        with b:
            assert b.spent == pytest.approx(first_spent)
            client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.spent == pytest.approx(first_spent * 2)


# ---------------------------------------------------------------------------
# test_persistent_with_fallback_combo
# ---------------------------------------------------------------------------


def test_persistent_with_fallback_combo() -> None:
    """Session budget + fallback: full combined scenario test."""
    big = make_openai_response("gpt-4o", 10_000, 5_000)
    small = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return big
        return small

    session = budget(max_usd=0.001, fallback="gpt-4o-mini", persistent=True, hard_cap=10.0)

    with patch(OPENAI_CREATE, new=fake_create):
        import openai

        client = openai.OpenAI(api_key="test")
        # Entry 1: triggers switch
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with session:
                client.chat.completions.create(model="gpt-4o", messages=[])

        assert session.model_switched is True
        assert session.switched_at_usd is not None
        spent_after_1 = session.spent

        # Entry 2: accumulates on fallback model
        with session:
            client.chat.completions.create(model="gpt-4o-mini", messages=[])

    assert session.spent > spent_after_1
    assert session.fallback_spent > 0.0

    # Reset and verify clean state
    session.reset()
    assert session.spent == pytest.approx(0.0)
    assert session.model_switched is False
