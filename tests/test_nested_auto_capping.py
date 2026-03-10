"""Test Decision #2: Auto-Capping to Parent Remaining

When child budget enters, its effective limit is min(requested_limit, parent.remaining).
Child knows its real limit immediately. If parent has $3 left and child asks for $5,
child gets $3. Clean, predictable, no hidden surprises.
"""

from shekel import budget


def test_child_gets_full_requested_limit_when_parent_has_capacity():
    """Child gets full requested limit when parent has enough remaining."""
    with budget(max_usd=10.00, name="parent"):
        with budget(max_usd=5.00, name="child") as child:
            # Parent has $10, child wants $5 - child gets $5
            assert child.limit == 5.00
            assert child.max_usd == 5.00


def test_child_auto_capped_to_parent_remaining():
    """Child limit is capped to parent's remaining when insufficient."""
    with budget(max_usd=10.00, name="parent") as parent:
        # Parent spends $7, has $3 remaining
        parent._spent = 7.00

        with budget(max_usd=5.00, name="child") as child:
            # Child wants $5, but parent only has $3
            # Child should be auto-capped to $3
            assert child.limit == 3.00
            assert child.max_usd == 5.00  # Original request unchanged
            assert parent.remaining == 3.00


def test_child_capped_to_exact_parent_remaining():
    """Child gets exactly parent.remaining when it matches."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 7.00  # Parent has $3 left

        with budget(max_usd=3.00, name="child") as child:
            # Child wants exactly what parent has
            assert child.limit == 3.00


def test_child_capped_to_zero_when_parent_exhausted():
    """Child gets $0 limit when parent is fully spent."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 10.00  # Parent exhausted

        with budget(max_usd=5.00, name="child") as child:
            # Child wants $5, but parent has $0
            assert child.limit == 0.0
            assert parent.remaining == 0.0


def test_multiple_children_each_capped_independently():
    """Multiple children are each capped based on current parent.remaining."""
    with budget(max_usd=10.00, name="parent"):
        with budget(max_usd=5.00, name="child1") as c1:
            assert c1.limit == 5.00  # Parent has $10
            c1._spent = 3.00
        # After child1: parent has $7 remaining

        with budget(max_usd=5.00, name="child2") as c2:
            # Child2 wants $5, parent has $7, gets $5
            assert c2.limit == 5.00
            c2._spent = 4.00
        # After child2: parent has $3 remaining

        with budget(max_usd=5.00, name="child3") as c3:
            # Child3 wants $5, parent has $3, gets capped to $3
            assert c3.limit == 3.00


def test_grandchild_capped_by_parent_not_grandparent():
    """Grandchild is capped by immediate parent, not grandparent."""
    with budget(max_usd=20.00, name="grandparent") as gp:
        gp._spent = 10.00  # Grandparent has $10 left

        with budget(max_usd=5.00, name="parent") as p:
            # Parent wants $5, grandparent has $10, gets $5
            assert p.limit == 5.00

            with budget(max_usd=8.00, name="child") as c:
                # Child wants $8, but parent only has $5
                # Capped by parent, not grandparent
                assert c.limit == 5.00


def test_track_only_child_not_capped():
    """Track-only children (max_usd=None) are not capped by parent."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 9.50  # Parent has $0.50 left

        with budget(max_usd=None, name="child") as child:
            # Track-only child has no limit, not capped
            assert child.limit is None
            assert child.max_usd is None
