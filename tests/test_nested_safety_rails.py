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


# Decision #20: Async Nesting (supported via ContextVar)
@pytest.mark.asyncio
async def test_async_single_level_works():
    """Single-level async budget works."""
    async with budget(max_usd=10.00, name="async_root") as root:
        assert root.name == "async_root"


@pytest.mark.asyncio
async def test_async_nested_budget_propagates_spend():
    """Child spend propagates to async parent on exit."""
    async with budget(max_usd=10.00, name="async_parent") as parent:
        async with budget(max_usd=5.00, name="async_child") as child:
            child._spent = 1.50
            child._spent_direct = 1.50

    assert parent.spent == pytest.approx(1.50)


@pytest.mark.asyncio
async def test_async_nested_requires_named_parent():
    """Unnamed parent in async context raises ValueError."""
    with pytest.raises(ValueError, match="Parent budget must have a name"):
        async with budget(max_usd=10.00):
            async with budget(max_usd=5.00, name="child"):
                pass


@pytest.mark.asyncio
async def test_async_nested_requires_named_child():
    """Unnamed child in async context raises ValueError."""
    with pytest.raises(ValueError, match="Child budget must have a name"):
        async with budget(max_usd=10.00, name="parent"):
            async with budget(max_usd=5.00):
                pass


@pytest.mark.asyncio
async def test_async_max_depth_exceeded():
    """Exceeding max nesting depth in async context raises ValueError."""
    with pytest.raises(ValueError, match="Maximum budget nesting depth of 5 exceeded"):
        async with budget(max_usd=100.00, name="d0"):
            async with budget(max_usd=50.00, name="d1"):
                async with budget(max_usd=25.00, name="d2"):
                    async with budget(max_usd=12.00, name="d3"):
                        async with budget(max_usd=6.00, name="d4"):
                            async with budget(max_usd=3.00, name="d5"):
                                pass


@pytest.mark.asyncio
async def test_async_duplicate_sibling_name_raises():
    """Two children with the same name under an async parent raises ValueError."""
    with pytest.raises(ValueError, match="Child name 'worker' already exists"):
        async with budget(max_usd=10.00, name="parent"):
            async with budget(max_usd=2.00, name="worker"):
                pass
            async with budget(max_usd=2.00, name="worker"):
                pass


@pytest.mark.asyncio
async def test_async_nested_track_only_parent_uses_child_limit():
    """Track-only async parent (no max_usd) takes the else branch for effective limit."""
    async with budget(name="parent") as parent:
        async with budget(max_usd=2.00, name="child") as child:
            assert child._effective_limit == pytest.approx(2.00)
        assert parent.spent == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_async_nested_call_limit_capped_to_parent_remaining():
    """Child call limit is capped to parent's remaining calls in async context."""
    async with budget(max_llm_calls=10, name="parent"):
        async with budget(max_llm_calls=20, name="child") as child:
            # Child wants 20 calls but parent only allows 10 total
            assert child._effective_call_limit == 10


@pytest.mark.asyncio
async def test_async_concurrent_tasks_isolated():
    """Concurrent async tasks each get isolated budget contexts via ContextVar."""
    import asyncio

    results: dict[str, float] = {}

    async def task_a() -> None:
        async with budget(max_usd=5.00, name="task_a") as b:
            b._spent = 1.00
            b._spent_direct = 1.00
            await asyncio.sleep(0)  # yield to let task_b run concurrently
        results["a"] = b.spent

    async def task_b() -> None:
        async with budget(max_usd=5.00, name="task_b") as b:
            b._spent = 2.00
            b._spent_direct = 2.00
            await asyncio.sleep(0)
        results["b"] = b.spent

    await asyncio.gather(task_a(), task_b())

    assert results["a"] == pytest.approx(1.00)
    assert results["b"] == pytest.approx(2.00)
