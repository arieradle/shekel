"""Tests for ShekelRuntime and component budget API (v0.3.1).

Domain: runtime framework detection scaffold and per-component budget registration.
"""

from __future__ import annotations

import pytest

from shekel import budget
from shekel._budget import Budget, ComponentBudget
from shekel._runtime import ShekelRuntime
from shekel.exceptions import (
    AgentBudgetExceededError,
    BudgetExceededError,
    NodeBudgetExceededError,
    SessionBudgetExceededError,
    TaskBudgetExceededError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_runtime_registry():
    """Save and restore ShekelRuntime._adapter_registry between tests."""
    original = ShekelRuntime._adapter_registry[:]
    yield
    ShekelRuntime._adapter_registry = original


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_node_budget_exceeded_error_is_budget_exceeded_error() -> None:
    err = NodeBudgetExceededError(node_name="fetch", spent=0.05, limit=0.01)
    assert isinstance(err, BudgetExceededError)


def test_agent_budget_exceeded_error_is_budget_exceeded_error() -> None:
    err = AgentBudgetExceededError(agent_name="researcher", spent=1.50, limit=1.00)
    assert isinstance(err, BudgetExceededError)


def test_task_budget_exceeded_error_is_budget_exceeded_error() -> None:
    err = TaskBudgetExceededError(task_name="write_report", spent=0.60, limit=0.50)
    assert isinstance(err, BudgetExceededError)


def test_session_budget_exceeded_error_is_budget_exceeded_error() -> None:
    err = SessionBudgetExceededError(agent_name="assistant", spent=6.00, limit=5.00)
    assert isinstance(err, BudgetExceededError)


def test_node_error_carries_node_name_spent_limit() -> None:
    err = NodeBudgetExceededError(node_name="summarize", spent=0.20, limit=0.10)
    assert err.node_name == "summarize"
    assert err.spent == pytest.approx(0.20)
    assert err.limit == pytest.approx(0.10)


def test_agent_error_carries_agent_name_spent_limit() -> None:
    err = AgentBudgetExceededError(agent_name="writer", spent=2.00, limit=1.50)
    assert err.agent_name == "writer"
    assert err.spent == pytest.approx(2.00)
    assert err.limit == pytest.approx(1.50)


def test_task_error_carries_task_name_spent_limit() -> None:
    err = TaskBudgetExceededError(task_name="research", spent=0.80, limit=0.50)
    assert err.task_name == "research"
    assert err.spent == pytest.approx(0.80)
    assert err.limit == pytest.approx(0.50)


def test_session_error_carries_agent_name_and_window() -> None:
    err = SessionBudgetExceededError(agent_name="bot", spent=6.00, limit=5.00, window=86400.0)
    assert err.agent_name == "bot"
    assert err.spent == pytest.approx(6.00)
    assert err.limit == pytest.approx(5.00)
    assert err.window == pytest.approx(86400.0)


def test_session_error_window_defaults_to_none() -> None:
    err = SessionBudgetExceededError(agent_name="bot", spent=6.00, limit=5.00)
    assert err.window is None


def test_existing_except_budget_exceeded_error_catches_node_error() -> None:
    """Existing catch-all still works after adding subclasses."""
    with pytest.raises(BudgetExceededError):
        raise NodeBudgetExceededError(node_name="x", spent=1.0, limit=0.5)


def test_existing_except_budget_exceeded_error_catches_agent_error() -> None:
    with pytest.raises(BudgetExceededError):
        raise AgentBudgetExceededError(agent_name="x", spent=1.0, limit=0.5)


def test_existing_except_budget_exceeded_error_catches_task_error() -> None:
    with pytest.raises(BudgetExceededError):
        raise TaskBudgetExceededError(task_name="x", spent=1.0, limit=0.5)


def test_existing_except_budget_exceeded_error_catches_session_error() -> None:
    with pytest.raises(BudgetExceededError):
        raise SessionBudgetExceededError(agent_name="x", spent=1.0, limit=0.5)


# ---------------------------------------------------------------------------
# ShekelRuntime — registry and probe/release
# ---------------------------------------------------------------------------


def test_runtime_probe_is_noop_with_empty_registry() -> None:
    """probe() with no registered adapters does nothing and does not raise."""
    b = Budget(max_usd=5.00)
    runtime = ShekelRuntime(b)
    runtime.probe()  # must not raise
    assert runtime._active_adapters == []


def test_runtime_register_adds_to_registry() -> None:
    class FakeAdapter:
        def install_patches(self, budget: Budget) -> None:
            pass

        def remove_patches(self, budget: Budget) -> None:
            pass

    ShekelRuntime.register(FakeAdapter)
    assert FakeAdapter in ShekelRuntime._adapter_registry


def test_runtime_probe_activates_registered_adapter() -> None:
    installed: list[Budget] = []

    class FakeAdapter:
        def install_patches(self, b: Budget) -> None:
            installed.append(b)

        def remove_patches(self, b: Budget) -> None:
            pass

    ShekelRuntime.register(FakeAdapter)
    b = Budget(max_usd=5.00)
    runtime = ShekelRuntime(b)
    runtime.probe()

    assert len(installed) == 1
    assert installed[0] is b
    assert len(runtime._active_adapters) == 1


def test_runtime_probe_skips_adapter_that_raises_import_error() -> None:
    class BadAdapter:
        def install_patches(self, b: Budget) -> None:
            raise ImportError("framework not installed")

        def remove_patches(self, b: Budget) -> None:
            pass

    ShekelRuntime.register(BadAdapter)
    b = Budget(max_usd=5.00)
    runtime = ShekelRuntime(b)
    runtime.probe()  # must not raise

    assert runtime._active_adapters == []


def test_runtime_release_calls_remove_patches_on_active_adapters() -> None:
    removed: list[Budget] = []

    class FakeAdapter:
        def install_patches(self, b: Budget) -> None:
            pass

        def remove_patches(self, b: Budget) -> None:
            removed.append(b)

    ShekelRuntime.register(FakeAdapter)
    b = Budget(max_usd=5.00)
    runtime = ShekelRuntime(b)
    runtime.probe()
    runtime.release()

    assert len(removed) == 1
    assert removed[0] is b
    assert runtime._active_adapters == []


def test_runtime_release_clears_active_adapters() -> None:
    class FakeAdapter:
        def install_patches(self, b: Budget) -> None:
            pass

        def remove_patches(self, b: Budget) -> None:
            pass

    ShekelRuntime.register(FakeAdapter)
    b = Budget(max_usd=5.00)
    runtime = ShekelRuntime(b)
    runtime.probe()
    assert len(runtime._active_adapters) == 1
    runtime.release()
    assert runtime._active_adapters == []


def test_runtime_release_tolerates_remove_patches_exception() -> None:
    """release() does not propagate exceptions from remove_patches."""

    class BrokenAdapter:
        def install_patches(self, b: Budget) -> None:
            pass

        def remove_patches(self, b: Budget) -> None:
            raise RuntimeError("unexpected error during cleanup")

    ShekelRuntime.register(BrokenAdapter)
    b = Budget(max_usd=5.00)
    runtime = ShekelRuntime(b)
    runtime.probe()
    runtime.release()  # must not raise


# ---------------------------------------------------------------------------
# ShekelRuntime — integration with Budget lifecycle
# ---------------------------------------------------------------------------


def test_runtime_probe_called_on_budget_enter() -> None:
    probed: list[Budget] = []

    class TrackingAdapter:
        def install_patches(self, b: Budget) -> None:
            probed.append(b)

        def remove_patches(self, b: Budget) -> None:
            pass

    ShekelRuntime.register(TrackingAdapter)

    with budget(max_usd=5.00) as b:
        assert len(probed) == 1
        assert probed[0] is b


def test_runtime_release_called_on_budget_exit() -> None:
    released: list[Budget] = []

    class TrackingAdapter:
        def install_patches(self, b: Budget) -> None:
            pass

        def remove_patches(self, b: Budget) -> None:
            released.append(b)

    ShekelRuntime.register(TrackingAdapter)

    with budget(max_usd=5.00) as b:
        pass

    assert len(released) == 1
    assert released[0] is b


def test_runtime_release_called_on_budget_exit_even_on_exception() -> None:
    released: list[bool] = []

    class TrackingAdapter:
        def install_patches(self, b: Budget) -> None:
            pass

        def remove_patches(self, b: Budget) -> None:
            released.append(True)

    ShekelRuntime.register(TrackingAdapter)

    with pytest.raises(ValueError):
        with budget(max_usd=5.00):
            raise ValueError("simulated error")

    assert released == [True]


async def _async_budget_helper(probed: list[Budget]) -> None:
    class TrackingAdapter:
        def install_patches(self, b: Budget) -> None:
            probed.append(b)

        def remove_patches(self, b: Budget) -> None:
            pass

    ShekelRuntime.register(TrackingAdapter)

    async with budget(max_usd=5.00) as b:
        assert len(probed) == 1
        assert probed[0] is b


@pytest.mark.asyncio
async def test_runtime_probe_called_on_async_budget_enter() -> None:
    probed: list[Budget] = []
    await _async_budget_helper(probed)


# ---------------------------------------------------------------------------
# Budget.node() / .agent() / .task() API
# ---------------------------------------------------------------------------


def test_budget_node_registers_component_budget() -> None:
    b = Budget(max_usd=5.00)
    b.node("fetch_data", max_usd=0.50)
    assert "fetch_data" in b._node_budgets
    assert b._node_budgets["fetch_data"].max_usd == pytest.approx(0.50)


def test_budget_agent_registers_component_budget() -> None:
    b = Budget(max_usd=5.00)
    b.agent("researcher", max_usd=1.50)
    assert "researcher" in b._agent_budgets
    assert b._agent_budgets["researcher"].max_usd == pytest.approx(1.50)


def test_budget_task_registers_component_budget() -> None:
    b = Budget(max_usd=5.00)
    b.task("write_report", max_usd=0.50)
    assert "write_report" in b._task_budgets
    assert b._task_budgets["write_report"].max_usd == pytest.approx(0.50)


def test_component_methods_return_self_for_chaining() -> None:
    b = Budget(max_usd=5.00)
    result = b.node("a", max_usd=0.50).agent("b", max_usd=1.00).task("c", max_usd=0.30)
    assert result is b


def test_node_max_usd_must_be_positive() -> None:
    b = Budget(max_usd=5.00)
    with pytest.raises(ValueError, match="positive"):
        b.node("fetch", max_usd=0.0)


def test_node_max_usd_must_not_be_negative() -> None:
    b = Budget(max_usd=5.00)
    with pytest.raises(ValueError, match="positive"):
        b.node("fetch", max_usd=-1.0)


def test_agent_max_usd_must_be_positive() -> None:
    b = Budget(max_usd=5.00)
    with pytest.raises(ValueError, match="positive"):
        b.agent("researcher", max_usd=0.0)


def test_task_max_usd_must_be_positive() -> None:
    b = Budget(max_usd=5.00)
    with pytest.raises(ValueError, match="positive"):
        b.task("write", max_usd=0.0)


def test_component_budgets_accessible_via_internal_dicts() -> None:
    b = Budget(max_usd=5.00)
    b.node("n1", max_usd=0.50)
    b.agent("a1", max_usd=1.00)
    b.task("t1", max_usd=0.30)

    assert isinstance(b._node_budgets["n1"], ComponentBudget)
    assert isinstance(b._agent_budgets["a1"], ComponentBudget)
    assert isinstance(b._task_budgets["t1"], ComponentBudget)


def test_component_budgets_can_be_registered_before_enter() -> None:
    """Registering component caps before opening the context is valid."""
    b = Budget(max_usd=5.00)
    b.node("fetch", max_usd=0.50)
    with b:
        assert "fetch" in b._node_budgets


def test_component_budgets_can_be_registered_inside_context() -> None:
    """Registering component caps inside the context is also valid."""
    with budget(max_usd=5.00) as b:
        b.node("fetch", max_usd=0.50)
        assert "fetch" in b._node_budgets


def test_component_budget_initial_spent_is_zero() -> None:
    b = Budget(max_usd=5.00)
    b.node("fetch", max_usd=0.50)
    cb = b._node_budgets["fetch"]
    assert cb._spent == pytest.approx(0.0)


def test_overwriting_node_budget_replaces_previous() -> None:
    b = Budget(max_usd=5.00)
    b.node("fetch", max_usd=0.50)
    b.node("fetch", max_usd=1.00)
    assert b._node_budgets["fetch"].max_usd == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# ComponentBudget dataclass
# ---------------------------------------------------------------------------


def test_component_budget_has_name_and_max_usd() -> None:
    cb = ComponentBudget(name="my_node", max_usd=0.50)
    assert cb.name == "my_node"
    assert cb.max_usd == pytest.approx(0.50)


def test_component_budget_spent_starts_at_zero() -> None:
    cb = ComponentBudget(name="my_node", max_usd=0.50)
    assert cb._spent == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# tree() output includes component budgets
# ---------------------------------------------------------------------------


def test_tree_includes_registered_node_budgets() -> None:
    with budget(max_usd=5.00) as b:
        b.node("fetch_data", max_usd=0.50)
        output = b.tree()
    assert "fetch_data" in output
    assert "node" in output


def test_tree_includes_registered_agent_budgets() -> None:
    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=1.50)
        output = b.tree()
    assert "researcher" in output
    assert "agent" in output


def test_tree_includes_registered_task_budgets() -> None:
    with budget(max_usd=5.00) as b:
        b.task("write_report", max_usd=0.50)
        output = b.tree()
    assert "write_report" in output
    assert "task" in output


def test_tree_shows_zero_spend_for_fresh_component_budgets() -> None:
    with budget(max_usd=5.00) as b:
        b.node("fetch_data", max_usd=0.50)
        output = b.tree()
    assert "$0.0000" in output


def test_tree_shows_multiple_component_types() -> None:
    with budget(max_usd=5.00) as b:
        b.node("n1", max_usd=0.50)
        b.agent("a1", max_usd=1.00)
        b.task("t1", max_usd=0.30)
        output = b.tree()
    assert "n1" in output
    assert "a1" in output
    assert "t1" in output


def test_tree_without_component_budgets_unchanged() -> None:
    """tree() with no component budgets must still work (no regression)."""
    with budget(max_usd=5.00) as b:
        output = b.tree()
    assert "unnamed" in output or output  # just must not raise
