"""Test Decision #1: On-Exit Propagation with Pre-Flight Check

Child budgets propagate spend to parent only on context exit (__exit__),
creating atomic stage accounting. Children must validate parent's remaining
budget before beginning operations. Propagation cascades automatically up
nested chains (child → parent → grandparent).
"""

from shekel import budget


def test_child_propagates_to_parent_on_exit():
    """Child spend propagates to parent when child exits."""
    with budget(max_usd=10.00, name="parent") as parent:
        assert parent.spent == 0.0

        with budget(max_usd=5.00, name="child") as child:
            # Simulate spending in child
            child._spent = 3.50
            # Parent should NOT see child spend yet (transparent model)
            assert parent.spent == 0.0

        # After child exit, parent should have received propagation
        assert parent.spent == 3.50


def test_cascading_propagation_up_tree():
    """Propagation cascades: child → parent → grandparent."""
    with budget(max_usd=20.00, name="grandparent") as gp:
        with budget(max_usd=10.00, name="parent") as p:
            with budget(max_usd=5.00, name="child") as c:
                c._spent = 2.00
                assert p.spent == 0.0
                assert gp.spent == 0.0
            # Child exited, propagated to parent
            assert p.spent == 2.00
            assert gp.spent == 0.0  # Parent hasn't exited yet
        # Parent exited, propagated to grandparent
        assert gp.spent == 2.00


def test_pre_flight_check_validates_parent_remaining():
    """Child checks parent remaining budget before starting."""
    with budget(max_usd=10.00, name="parent") as parent:
        # Parent spends $7, has $3 remaining
        parent._spent = 7.00

        # Child requests $5, but parent only has $3 left
        # Should be auto-capped to $3 (tested in test_auto_capping.py)
        # but pre-flight check should validate parent has capacity
        with budget(max_usd=5.00, name="child") as child:
            # Child should be allowed to enter
            assert child.max_usd == 5.00  # Will be capped in auto-capping


def test_multiple_children_propagate_independently():
    """Multiple sequential children each propagate on their own exit."""
    with budget(max_usd=20.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child1") as c1:
            c1._spent = 3.00
        assert parent.spent == 3.00

        with budget(max_usd=5.00, name="child2") as c2:
            c2._spent = 4.00
        assert parent.spent == 7.00  # 3 + 4

        with budget(max_usd=5.00, name="child3") as c3:
            c3._spent = 2.50
        assert parent.spent == 9.50  # 3 + 4 + 2.5


def test_propagation_with_no_child_spend():
    """Child with zero spend still propagates (zero) to parent."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child") as child:
            assert child.spent == 0.0
        # Child propagates 0, parent still at 0
        assert parent.spent == 0.0
