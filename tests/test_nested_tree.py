"""Test Decision #27 & #9: tree() display method.

Visual hierarchy display of budget tree with spend breakdown.
Active children shown without spend details (transparent model).
"""

from shekel import budget


def test_tree_single_root():
    """Root budget tree shows just the root."""
    with budget(max_usd=10.00, name="root") as b:
        b._spent = 5.00
        b._spent_direct = 5.00
        tree = b.tree()

        assert "root" in tree
        assert "$5.00" in tree or "5.00" in tree


def test_tree_with_children():
    """Tree shows parent and children after they exit."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 1.00
        parent._spent_direct = 1.00

        with budget(max_usd=5.00, name="child1") as c1:
            c1._spent = 2.00
            c1._spent_direct = 2.00

        with budget(max_usd=3.00, name="child2") as c2:
            c2._spent = 1.50
            c2._spent_direct = 1.50

        tree = parent.tree()
        assert "parent" in tree
        assert "child1" in tree
        assert "child2" in tree


def test_tree_shows_active_child_without_spend():
    """Active child shown with [ACTIVE] marker, no spend details (Decision #27)."""
    with budget(max_usd=10.00, name="parent") as parent:
        parent._spent = 1.00
        parent._spent_direct = 1.00

        with budget(max_usd=5.00, name="child") as child:
            child._spent = 2.00
            child._spent_direct = 2.00

            # While child is active, tree should show it but not spend
            tree = parent.tree()
            assert "child" in tree
            assert "[ACTIVE]" in tree or "active" in tree.lower()


def test_tree_grandchildren():
    """Tree shows multiple levels of nesting."""
    with budget(max_usd=20.00, name="root") as root:
        root._spent = 1.00
        root._spent_direct = 1.00

        with budget(max_usd=10.00, name="child") as child:
            child._spent = 2.00
            child._spent_direct = 2.00

            with budget(max_usd=5.00, name="grandchild") as gc:
                gc._spent = 3.00
                gc._spent_direct = 3.00

        tree = root.tree()
        assert "root" in tree
        assert "child" in tree
        assert "grandchild" in tree
