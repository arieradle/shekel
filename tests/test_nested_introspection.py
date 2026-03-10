"""Test Decision #11: Rich Introspection API for Nested Budgets.

Budgets expose comprehensive parent/child relationship and spend tracking.
"""

from shekel import budget


def test_full_name_for_root():
    """Root budget full_name is just its name."""
    with budget(max_usd=10.00, name="root") as b:
        assert b.full_name == "root"


def test_full_name_for_child():
    """Child budget full_name is parent.child."""
    with budget(max_usd=10.00, name="parent"):
        with budget(max_usd=5.00, name="child") as c:
            assert c.full_name == "parent.child"


def test_full_name_for_grandchild():
    """Grandchild budget full_name is parent.child.grandchild."""
    with budget(max_usd=10.00, name="root"):
        with budget(max_usd=5.00, name="stage1"):
            with budget(max_usd=2.00, name="substage") as gc:
                assert gc.full_name == "root.stage1.substage"


def test_spent_direct_excludes_children():
    """spent_direct shows only direct spend, not children."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 1.50  # Total spent
        parent._spent_direct = 1.50  # Direct parent spend

        with budget(max_usd=5.00, name="child") as child:
            child._spent = 2.00  # Child spend
            child._spent_direct = 2.00

        # After child exits, parent.spent includes child
        assert parent.spent == 3.50
        # But spent_direct shows only parent's direct spend
        assert parent.spent_direct == 1.50


def test_spent_by_children():
    """spent_by_children shows sum of all child spend."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 1.00
        parent._spent_direct = 1.00

        with budget(max_usd=3.00, name="child1") as c1:
            c1._spent = 1.50
            c1._spent_direct = 1.50

        with budget(max_usd=3.00, name="child2") as c2:
            c2._spent = 2.00
            c2._spent_direct = 2.00

        assert parent.spent == 4.50
        assert parent.spent_direct == 1.00
        assert parent.spent_by_children == 3.50


def test_spent_by_children_zero_for_root_without_children():
    """Root without children has spent_by_children = 0."""
    with budget(max_usd=10.00, name="root") as b:
        b._spent = 5.00
        b._spent_direct = 5.00
        assert b.spent_by_children == 0.0


def test_spent_by_children_includes_grandchildren():
    """spent_by_children includes all descendant spend."""
    with budget(max_usd=20.00, name="root") as root:
        root._spent = 1.00
        root._spent_direct = 1.00

        with budget(max_usd=10.00, name="child") as child:
            child._spent = 2.00
            child._spent_direct = 2.00

            with budget(max_usd=5.00, name="grandchild") as gc:
                gc._spent = 3.00
                gc._spent_direct = 3.00

        # Grandchild propagates to child: 2 + 3 = 5
        # Child propagates to root: 1 + 5 = 6
        assert root.spent == 6.00
        assert root.spent_direct == 1.00
        assert root.spent_by_children == 5.00


def test_parent_reference():
    """Child has reference to parent."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=5.00, name="child") as child:
            assert child.parent is parent
            assert parent.parent is None


def test_children_list():
    """Parent has list of all children."""
    with budget(max_usd=10.00, name="parent") as parent:
        with budget(max_usd=2.00, name="child1"):
            pass

        with budget(max_usd=3.00, name="child2"):
            pass

        assert len(parent.children) == 2
        assert parent.children[0].name == "child1"
        assert parent.children[1].name == "child2"
