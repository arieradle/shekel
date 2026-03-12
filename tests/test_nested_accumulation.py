"""Test Decision #12: Budget Variables Always Accumulate.

Budget objects always accumulate spend across multiple with blocks.
The persistent flag is deprecated - same variable = same accumulated state.
"""

import warnings

import pytest

from shekel import budget


def test_budget_variable_accumulates_by_default():
    """Budget variables naturally accumulate across multiple with blocks."""
    b = budget(max_usd=10.00, name="accumulator")

    # First entry
    with b:
        b._spent = 2.00
        b._spent_direct = 2.00

    assert b.spent == 2.00

    # Second entry - should accumulate, not reset
    with b:
        b._spent += 1.50
        b._spent_direct += 1.50

    assert b.spent == 3.50


def test_new_budget_instance_starts_fresh():
    """Creating a new budget instance starts with zero spend."""
    # First budget
    with budget(max_usd=10.00, name="first") as b1:
        b1._spent = 5.00
        b1._spent_direct = 5.00

    assert b1.spent == 5.00

    # New budget instance - fresh start
    with budget(max_usd=10.00, name="second") as b2:
        assert b2.spent == 0.0


def test_persistent_param_removed():
    """persistent parameter was removed in v0.2.6 — passing it raises TypeError."""
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        budget(max_usd=10.00, persistent=True, name="old")


def test_no_persistent_no_warning():
    """No warnings emitted when creating a budget without persistent."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        budget(max_usd=10.00, name="normal")

        assert len(w) == 0


def test_nested_budgets_accumulate():
    """Nested budgets also accumulate across entries."""
    parent = budget(max_usd=20.00, name="parent")

    # First entry
    with parent:
        with budget(max_usd=5.00, name="child") as child:
            child._spent = 2.00
            child._spent_direct = 2.00

    assert parent.spent == 2.00

    # Second entry - parent accumulates
    with parent:
        # Simulate parent spending directly
        parent._spent += 1.00
        parent._spent_direct += 1.00

        with budget(max_usd=5.00, name="child2") as child2:
            child2._spent = 1.50
            child2._spent_direct = 1.50

    # Parent accumulated: 2.00 (from child) + 1.00 (direct) + 1.50 (from child2) = 4.50
    assert parent.spent == 4.50
