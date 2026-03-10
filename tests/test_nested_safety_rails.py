"""Test Phase 3 Safety Rails: Decisions #18, #20, #21, #26.

Max depth limit, async nesting detection, exception propagation, and immutability.
"""

import pytest

from shekel import budget


# Decision #18: Maximum Nesting Depth Limit
def test_max_depth_5_levels():
    """Maximum nesting depth of 5 levels is enforced."""
    with budget(max_usd=100.00, name="depth0"):  # Root = depth 0
        with budget(max_usd=50.00, name="depth1"):  # depth 1
            with budget(max_usd=25.00, name="depth2"):  # depth 2
                with budget(max_usd=12.00, name="depth3"):  # depth 3
                    with budget(max_usd=6.00, name="depth4"):  # depth 4
                        # This is depth 4 - should work
                        assert True


def test_max_depth_exceeded_raises_error():
    """Attempting to nest deeper than 5 levels raises ValueError."""
    with budget(max_usd=100.00, name="depth0"):
        with budget(max_usd=50.00, name="depth1"):
            with budget(max_usd=25.00, name="depth2"):
                with budget(max_usd=12.00, name="depth3"):
                    with budget(max_usd=6.00, name="depth4"):
                        # Depth 5 should fail
                        with pytest.raises(
                            ValueError,
                            match="Maximum budget nesting depth of 5 exceeded",
                        ):
                            with budget(max_usd=3.00, name="depth5"):
                                pass


# Decision #21: Exception Propagation
def test_spend_propagates_even_on_exception():
    """Child spend propagates to parent even if child raises exception."""
    with budget(max_usd=10.00, name="parent") as parent:
        try:
            with budget(max_usd=5.00, name="child") as child:
                child._spent = 2.50
                child._spent_direct = 2.50
                raise RuntimeError("Something went wrong!")
        except RuntimeError:
            pass

        # Parent should have received child's spend despite exception
        assert parent.spent == 2.50


def test_spend_propagates_on_keyboard_interrupt():
    """Child spend propagates even on KeyboardInterrupt."""
    with budget(max_usd=10.00, name="parent") as parent:
        try:
            with budget(max_usd=5.00, name="child") as child:
                child._spent = 1.75
                child._spent_direct = 1.75
                raise KeyboardInterrupt()
        except KeyboardInterrupt:
            pass

        assert parent.spent == 1.75


# Decision #20: No Async Nesting
@pytest.mark.asyncio
async def test_async_nesting_not_supported():
    """Async nesting raises clear error (deferred to future version)."""
    # Single-level async should work
    async with budget(max_usd=10.00, name="async_root") as root:
        assert root.name == "async_root"

    # But nesting in async contexts should raise error
    with pytest.raises(RuntimeError, match="Nested budgets not supported in async contexts"):
        async with budget(max_usd=10.00, name="async_parent"):
            async with budget(max_usd=5.00, name="async_child"):
                pass
