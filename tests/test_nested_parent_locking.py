"""Test Decision #4: Parent Locked During Child Execution

When a child budget context is active, the parent budget cannot track new spending.
Any attempt to spend on the parent while a child is active raises an error.
This enforces sequential execution and prevents race conditions.
"""

import pytest

from shekel import budget


def test_parent_cannot_spend_while_child_active():
    """Parent cannot track spend while child is active."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child"):
            # Try to record spend on parent while child is active
            # This should raise an error
            with pytest.raises(
                RuntimeError, match="Cannot spend on parent budget.*while child budget.*is active"
            ):
                parent._record_spend(1.00, "gpt-4o", {"input": 100, "output": 50})


def test_parent_can_spend_before_child():
    """Parent can spend before child enters."""
    with budget(max_usd=10.00, name="parent") as parent:
        # Parent can spend before child
        parent._spent = 3.00
        assert parent.spent == 3.00

        with budget(max_usd=5.00, name="child") as child:
            child._spent = 2.00

        # After child exit, parent has propagated spend
        assert parent.spent == 5.00  # 3 + 2


def test_parent_can_spend_after_child_exits():
    """Parent can spend after child exits."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child") as child:
            child._spent = 2.00
        # Child exited, parent can spend now
        assert parent.spent == 2.00

        parent._spent += 3.00  # Parent spends more
        assert parent.spent == 5.00


def test_sequential_children_no_blocking():
    """Sequential children don't block each other."""
    with budget(max_usd=20.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child1") as c1:
            c1._spent = 2.00
        # Child1 done, parent can track

        with budget(max_usd=5.00, name="child2") as c2:
            c2._spent = 3.00
        # Child2 done

        assert parent.spent == 5.00  # 2 + 3


def test_nested_grandchild_blocks_grandparent():
    """Active grandchild also blocks grandparent spending."""
    with budget(max_usd=20.00, name="grandparent") as gp:
        with budget(max_usd=10.00, name="parent"):
            with budget(max_usd=5.00, name="child"):
                # Grandchild active - grandparent is blocked
                with pytest.raises(
                    RuntimeError,
                    match="Cannot spend on parent budget.*while child budget.*is active",
                ):
                    gp._record_spend(1.00, "gpt-4o", {"input": 100, "output": 50})


def test_active_child_property_set_correctly():
    """Parent's active_child property is set when child enters."""
    with budget(max_usd=10.00, name="parent") as parent:
        assert parent.active_child is None

        with budget(max_usd=5.00, name="child") as child:
            assert parent.active_child is child

        # After child exits, active_child cleared
        assert parent.active_child is None


def test_root_budget_can_always_spend():
    """Root budget (no parent) can always track spend."""
    with budget(max_usd=10.00, name="root") as root:
        # Root has no parent, can spend freely
        root._record_spend(1.00, "gpt-4o", {"input": 100, "output": 50})
        assert root.spent > 0
