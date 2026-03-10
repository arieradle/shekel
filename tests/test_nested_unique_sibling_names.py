"""Test Decision #23: Unique Child Names Under Same Parent.

Sibling budgets must have unique names.
"""

import pytest

from shekel import budget


def test_siblings_must_have_unique_names():
    """Sequential children with duplicate names should raise ValueError."""
    with budget(max_usd=10.00, name="parent"):
        with budget(max_usd=2.00, name="stage"):
            pass

        # Second child with same name should fail
        with pytest.raises(
            ValueError, match="Child name 'stage' already exists under parent 'parent'"
        ):
            with budget(max_usd=3.00, name="stage"):
                pass


def test_different_sibling_names_allowed():
    """Siblings with different names work fine."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=2.00, name="stage1") as c1:
            c1._spent = 1.00

        with budget(max_usd=3.00, name="stage2") as c2:
            c2._spent = 2.00

        assert parent.spent == 3.00


def test_same_name_across_different_parents_allowed():
    """Same child name is allowed under different parents."""
    with budget(max_usd=10.00, name="parent1"):
        with budget(max_usd=2.00, name="stage"):
            pass

    # Different parent, same child name is OK
    with budget(max_usd=10.00, name="parent2"):
        with budget(max_usd=2.00, name="stage"):
            pass


def test_grandchild_can_have_same_name_as_uncle():
    """Grandchild can have same name as parent's sibling (different hierarchy level)."""
    with budget(max_usd=20.00, name="root"):
        with budget(max_usd=5.00, name="stage"):
            # Grandchild with same name as uncle is OK (different parent)
            with budget(max_usd=2.00, name="nested"):
                pass

        with budget(max_usd=5.00, name="processing"):
            # Another grandchild with same name is OK (under different child)
            with budget(max_usd=2.00, name="nested"):
                pass


def test_error_message_includes_parent_and_child_names():
    """Error message should be helpful with parent and child names."""
    with budget(max_usd=10.00, name="workflow"):
        with budget(max_usd=2.00, name="research"):
            pass

        with pytest.raises(
            ValueError, match="Child name 'research' already exists under parent 'workflow'"
        ):
            with budget(max_usd=3.00, name="research"):
                pass
