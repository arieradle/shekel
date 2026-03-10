"""Test Decision #24: Zero/Negative Budget Validation.

max_usd=0 and max_usd < 0 raise ValueError at __init__.
Fractions of cents are allowed (e.g., max_usd=0.001).
"""

import pytest

from shekel import budget


def test_zero_budget_raises_error():
    """max_usd=0 raises ValueError."""
    with pytest.raises(ValueError, match="max_usd must be positive or None for track-only mode"):
        budget(max_usd=0.0)


def test_negative_budget_raises_error():
    """Negative max_usd raises ValueError."""
    with pytest.raises(ValueError, match="max_usd must be positive or None for track-only mode"):
        budget(max_usd=-5.00)


def test_tiny_positive_budget_allowed():
    """Tiny positive values like $0.001 are allowed."""
    with budget(max_usd=0.001, name="tiny") as b:
        assert b.limit == 0.001


def test_none_budget_allowed():
    """max_usd=None (track-only) is explicitly allowed."""
    with budget(max_usd=None, name="tracker") as b:
        assert b.limit is None


def test_large_positive_budget_allowed():
    """Normal positive budgets work."""
    with budget(max_usd=100.00, name="normal") as b:
        assert b.limit == 100.00
