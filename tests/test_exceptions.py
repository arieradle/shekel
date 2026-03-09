from __future__ import annotations

from shekel import BudgetExceededError


def test_str_with_tokens() -> None:
    err = BudgetExceededError(1.05, 1.00, "gpt-4o", {"input": 500, "output": 200})
    s = str(err)
    assert "exceeded" in s
    assert "gpt-4o" in s
    assert "500" in s
    assert "200" in s
    assert "Tip:" in s


def test_str_with_zero_tokens() -> None:
    err = BudgetExceededError(1.05, 1.00, "gpt-4o", {"input": 0, "output": 0})
    s = str(err)
    assert "exceeded" in s
    assert "gpt-4o" in s
    assert "Tip:" in s


def test_str_without_tokens_arg() -> None:
    err = BudgetExceededError(0.5, 0.3)
    s = str(err)
    assert "exceeded" in s
    assert "Tip:" in s


def test_attributes() -> None:
    err = BudgetExceededError(1.05, 1.00, "gpt-4o", {"input": 500, "output": 200})
    assert err.spent == 1.05
    assert err.limit == 1.00
    assert err.model == "gpt-4o"
    assert err.tokens == {"input": 500, "output": 200}
