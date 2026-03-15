from __future__ import annotations

import pytest

from shekel._budget import Budget
from shekel.exceptions import BudgetExceededError, ToolBudgetExceededError

# ---------------------------------------------------------------------------
# Story 11: Budget(warn_only=True) — enforce silently, never raise
# ---------------------------------------------------------------------------


def test_warn_only_does_not_raise_on_usd_exceeded() -> None:
    b = Budget(max_usd=0.001, warn_only=True)
    with b:
        b._record_spend(1.0, "gpt-4o", {"input": 100, "output": 50})
    # No BudgetExceededError raised


def test_warn_only_false_still_raises_on_usd_exceeded() -> None:
    b = Budget(max_usd=0.001, warn_only=False)
    with pytest.raises(BudgetExceededError):
        with b:
            b._record_spend(1.0, "gpt-4o", {"input": 100, "output": 50})


def test_warn_only_does_not_raise_on_call_limit_exceeded() -> None:
    b = Budget(max_usd=10.0, max_llm_calls=1, warn_only=True)
    with b:
        # First call — within limit
        b._record_spend(0.001, "gpt-4o", {"input": 10, "output": 5})
        # Second call — exceeds max_llm_calls=1, but warn_only so no raise
        b._record_spend(0.001, "gpt-4o", {"input": 10, "output": 5})


def test_warn_only_false_raises_on_call_limit_exceeded() -> None:
    b = Budget(max_usd=10.0, max_llm_calls=1, warn_only=False)
    with pytest.raises(BudgetExceededError):
        with b:
            b._record_spend(0.001, "gpt-4o", {"input": 10, "output": 5})
            b._record_spend(0.001, "gpt-4o", {"input": 10, "output": 5})


def test_warn_only_does_not_raise_on_tool_limit_exceeded() -> None:
    b = Budget(max_tool_calls=1, warn_only=True)
    with b:
        b._check_tool_limit("web_search", "manual")
        b._record_tool_call("web_search", 0.0, "manual")
        # Second call — exceeds max_tool_calls=1, but warn_only so no raise
        b._check_tool_limit("web_search", "manual")


def test_warn_only_false_raises_on_tool_limit_exceeded() -> None:
    b = Budget(max_tool_calls=1, warn_only=False)
    with pytest.raises(ToolBudgetExceededError):
        with b:
            b._check_tool_limit("web_search", "manual")
            b._record_tool_call("web_search", 0.0, "manual")
            b._check_tool_limit("web_search", "manual")


def test_warn_only_still_fires_warn_callback_when_exceeded() -> None:
    fired: list[tuple[float, float]] = []
    b = Budget(
        max_usd=1.0,
        warn_at=0.5,
        on_warn=lambda s, l: fired.append((s, l)),
        warn_only=True,
    )
    with b:
        b._record_spend(2.0, "gpt-4o", {"input": 100, "output": 50})
    assert len(fired) == 1
    assert fired[0][1] == 1.0  # limit


def test_warn_only_spent_is_tracked_correctly() -> None:
    b = Budget(max_usd=0.001, warn_only=True)
    with b:
        b._record_spend(1.5, "gpt-4o", {"input": 100, "output": 50})
    assert b.spent == pytest.approx(1.5)


def test_warn_only_tool_usd_limit_does_not_raise() -> None:
    """Tool USD limit check also respects warn_only."""
    b = Budget(max_usd=0.01, tool_prices={"web_search": 0.05}, warn_only=True)
    with b:
        # This would raise ToolBudgetExceededError without warn_only
        b._check_tool_limit("web_search", "manual")


def test_warn_only_default_is_false() -> None:
    b = Budget(max_usd=0.001)
    assert b.warn_only is False


def test_warn_only_stored_on_budget() -> None:
    b = Budget(max_usd=1.0, warn_only=True)
    assert b.warn_only is True
