"""Test Decision #9: Required Names for Nested Budgets.

Root budgets can omit name, but nested budgets must have names.
"""

import pytest

from shekel import budget


def test_root_budget_without_name_allowed():
    """Root budgets can omit the name parameter."""
    with budget(max_usd=10.00) as b:
        assert b.name is None
        b._spent = 1.00
    assert b.spent == 1.00


def test_nested_parent_must_have_name():
    """Parent must have a name if it has children."""
    with pytest.raises(ValueError, match="Parent budget must have a name when nesting"):
        with budget(max_usd=10.00):  # No name
            with budget(max_usd=5.00, name="child"):
                pass


def test_nested_child_must_have_name():
    """Child must have a name when nesting."""
    with pytest.raises(ValueError, match="Child budget must have a name when nesting"):
        with budget(max_usd=10.00, name="parent"):
            with budget(max_usd=5.00):  # No name
                pass


def test_both_parent_and_child_must_have_names():
    """Both parent and child must have names."""
    with pytest.raises(ValueError, match="must have a name when nesting"):
        with budget(max_usd=10.00):  # No name
            with budget(max_usd=5.00):  # No name
                pass


def test_nested_budgets_with_names_work():
    """Nested budgets with names work correctly."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child") as child:
            child._spent = 2.00
        assert parent.spent == 2.00
