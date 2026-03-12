"""Tests for F5 — budget.summary() spend report."""

from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from shekel import budget
from shekel._budget import Budget
from tests.conftest import make_openai_response

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"


def _inject_spend(b: Budget, model: str, cost: float, input_t: int, output_t: int) -> None:
    """Directly inject a spend record into a budget (bypasses patching)."""
    b._record_spend(cost, model, {"input": input_t, "output": output_t})


# ---------------------------------------------------------------------------
# test_summary_data_no_calls
# ---------------------------------------------------------------------------


def test_summary_data_no_calls() -> None:
    """Empty budget returns correct zero-state summary_data."""
    b = budget(max_usd=1.00)
    data = b.summary_data()

    assert data["total_spent"] == pytest.approx(0.0)
    assert data["limit"] == pytest.approx(1.00)
    assert data["model_switched"] is False
    assert data["switched_at_usd"] is None
    assert data["total_calls"] == 0
    assert data["calls"] == []
    assert data["by_model"] == {}
    assert data["fallback_spent"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# test_summary_data_single_call
# ---------------------------------------------------------------------------


def test_summary_data_single_call() -> None:
    """Single call data recorded correctly."""
    b = budget(max_usd=1.00)
    _inject_spend(b, "gpt-4o", 0.05, 1000, 500)

    data = b.summary_data()
    assert data["total_spent"] == pytest.approx(0.05)
    assert data["total_calls"] == 1
    calls = data["calls"]
    assert isinstance(calls, list)
    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call, dict)
    assert call["model"] == "gpt-4o"
    assert call["cost"] == pytest.approx(0.05)
    assert call["input_tokens"] == 1000
    assert call["output_tokens"] == 500
    assert call["fallback"] is False


# ---------------------------------------------------------------------------
# test_summary_data_multi_call
# ---------------------------------------------------------------------------


def test_summary_data_multi_call() -> None:
    """Multiple calls aggregated correctly by model."""
    b = budget(max_usd=5.00)
    _inject_spend(b, "gpt-4o", 0.10, 1000, 500)
    _inject_spend(b, "gpt-4o", 0.15, 2000, 700)
    _inject_spend(b, "gpt-4o-mini", 0.01, 3000, 1000)

    data = b.summary_data()
    assert data["total_calls"] == 3
    assert data["total_spent"] == pytest.approx(0.26)

    by_model = data["by_model"]
    assert isinstance(by_model, dict)
    assert "gpt-4o" in by_model
    assert "gpt-4o-mini" in by_model
    assert by_model["gpt-4o"]["calls"] == 2
    assert by_model["gpt-4o"]["cost"] == pytest.approx(0.25)
    assert by_model["gpt-4o-mini"]["calls"] == 1
    assert by_model["gpt-4o-mini"]["cost"] == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# test_summary_data_with_fallback
# ---------------------------------------------------------------------------


def test_summary_data_with_fallback() -> None:
    """Fallback calls marked, by_model splits correctly."""
    fake_big = make_openai_response("gpt-4o", 10_000, 5_000)
    fake_small = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_big
        return fake_small

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])
                client.chat.completions.create(model="gpt-4o-mini", messages=[])

    data = b.summary_data()
    calls = data["calls"]
    assert isinstance(calls, list)
    # First call is primary
    assert calls[0]["fallback"] is False
    # Second call is fallback
    assert calls[1]["fallback"] is True
    assert data["model_switched"] is True
    assert data["switched_at_usd"] is not None


# ---------------------------------------------------------------------------
# test_summary_str_returns_string
# ---------------------------------------------------------------------------


def test_summary_str_returns_string() -> None:
    """summary() returns a non-empty string."""
    b = budget(max_usd=1.00)
    _inject_spend(b, "gpt-4o", 0.05, 1000, 500)
    result = b.summary()
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# test_summary_str_contains_totals
# ---------------------------------------------------------------------------


def test_summary_str_contains_totals() -> None:
    """Output contains total spend and call count."""
    b = budget(max_usd=1.00)
    _inject_spend(b, "gpt-4o", 0.05, 1000, 500)
    _inject_spend(b, "gpt-4o", 0.03, 500, 200)

    result = b.summary()
    assert "0.0800" in result  # total spend
    assert "2" in result  # call count
    assert "gpt-4o" in result


# ---------------------------------------------------------------------------
# test_summary_data_method
# ---------------------------------------------------------------------------


def test_summary_data_method() -> None:
    """summary_data() returns correct dict shape."""
    b = budget(max_usd=2.00)
    _inject_spend(b, "gpt-4o-mini", 0.002, 500, 300)

    data = b.summary_data()
    required_keys = {
        "total_spent",
        "limit",
        "model_switched",
        "switched_at_usd",
        "fallback_model",
        "fallback_spent",
        "total_calls",
        "calls",
        "by_model",
    }
    assert required_keys.issubset(data.keys())


# ---------------------------------------------------------------------------
# test_summary_after_reset
# ---------------------------------------------------------------------------


def test_summary_after_reset() -> None:
    """After reset(), summary_data() shows zero state."""
    b = budget(max_usd=1.00)
    _inject_spend(b, "gpt-4o", 0.10, 1000, 500)
    assert b.summary_data()["total_calls"] == 1

    b.reset()
    data = b.summary_data()

    assert data["total_spent"] == pytest.approx(0.0)
    assert data["total_calls"] == 0
    assert data["calls"] == []
    assert data["by_model"] == {}
    assert data["model_switched"] is False


# ---------------------------------------------------------------------------
# test_summary_data_hard_cap_default (covers _budget.py effective_hard_cap path)
# ---------------------------------------------------------------------------


def test_summary_data_fallback_shares_budget() -> None:
    """summary_data() shows that fallback shares the primary budget limit."""
    b = budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})
    _inject_spend(b, "gpt-4o", 0.50, 1000, 500)

    data = b.summary_data()
    # With the new simplified API, fallback uses the same limit as primary
    assert data["limit"] == pytest.approx(1.00)
    # No separate fallback_max_usd is present anymore
    assert "fallback_max_usd" not in data or data.get("fallback_max_usd") == pytest.approx(1.00)


def test_summary_str_shows_switched_at() -> None:
    """summary() includes 'Switched at' line when model has switched."""
    b = budget(max_usd=0.01, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})
    # Simulate switch by injecting state directly
    b._using_fallback = True
    b._switched_at_usd = 0.0123
    _inject_spend(b, "gpt-4o-mini", 0.001, 100, 50)

    result = b.summary()
    assert "Switched at" in result
    assert "0.0123" in result
