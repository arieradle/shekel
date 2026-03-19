"""Tests for CrewAI agent/task-level budget enforcement (v1.0.0).

Domain: CrewAIExecutionAdapter — patching, agent/task gate, spend attribution,
nested budget inheritance, silent-miss warnings.
"""

from __future__ import annotations

import sys
import types
import warnings
from typing import Any

import pytest

import shekel.providers.crewai as crewai_mod
from shekel import budget
from shekel._budget import Budget
from shekel._runtime import ShekelRuntime
from shekel.exceptions import AgentBudgetExceededError, TaskBudgetExceededError

CrewAIExecutionAdapter = crewai_mod.CrewAIExecutionAdapter

# ---------------------------------------------------------------------------
# Helpers — fake crewai.agent module injection
# ---------------------------------------------------------------------------


def _make_crewai_modules(simulated_cost: float = 0.0) -> tuple[types.ModuleType, type]:
    """Return (fake_crewai_agent_mod, Agent class) injected into sys.modules."""
    fake_crewai = types.ModuleType("crewai")
    fake_agent_mod = types.ModuleType("crewai.agent")

    class Agent:
        def __init__(self, role: str = "Senior Researcher") -> None:
            self.role = role

        def execute_task(self, task: Any, context: Any = None, tools: Any = None) -> str:
            if simulated_cost > 0:
                from shekel._context import get_active_budget

                active = get_active_budget()
                if active is not None:
                    active._spent += simulated_cost
                    active._spent_direct += simulated_cost
            return "done"

    fake_agent_mod.Agent = Agent  # type: ignore[attr-defined]
    sys.modules["crewai"] = fake_crewai  # type: ignore[assignment]
    sys.modules["crewai.agent"] = fake_agent_mod  # type: ignore[assignment]
    return fake_agent_mod, Agent


def _cleanup_crewai_modules() -> None:
    for key in ["crewai", "crewai.agent"]:
        sys.modules.pop(key, None)


class MockTask:
    def __init__(self, name: str = "research", description: str = "Do research about AI") -> None:
        self.name = name
        self.description = description


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_adapter_state():
    """Restore CrewAIExecutionAdapter patch state and ShekelRuntime registry."""
    original_refcount = crewai_mod._execution_patch_refcount
    original_execute_task = crewai_mod._original_execute_task
    original_registry = ShekelRuntime._adapter_registry[:]

    yield

    # Restore module state
    crewai_mod._execution_patch_refcount = original_refcount
    crewai_mod._original_execute_task = original_execute_task

    # Restore registry
    ShekelRuntime._adapter_registry = original_registry

    # Clean up injected fake modules
    _cleanup_crewai_modules()


# ---------------------------------------------------------------------------
# Group 0: Smoke-check — Agent.execute_task signature
# ---------------------------------------------------------------------------


def test_execute_task_signature_has_task_param() -> None:
    """Fake Agent.execute_task has the expected 'task' parameter."""
    import inspect

    _, Agent = _make_crewai_modules()
    sig = inspect.signature(Agent.execute_task)
    assert "task" in sig.parameters


# ---------------------------------------------------------------------------
# Group 1: CrewAIExecutionAdapter registered in ShekelRuntime
# ---------------------------------------------------------------------------


def test_crewai_execution_adapter_in_runtime_registry() -> None:
    """CrewAIExecutionAdapter is registered in ShekelRuntime at import time."""
    assert CrewAIExecutionAdapter in ShekelRuntime._adapter_registry


# ---------------------------------------------------------------------------
# Group 2: install_patches / remove_patches lifecycle
# ---------------------------------------------------------------------------


def test_install_patches_raises_import_error_when_crewai_absent() -> None:
    """install_patches() raises ImportError when crewai.agent is not importable."""
    _cleanup_crewai_modules()
    sys.modules["crewai"] = None  # type: ignore[assignment]
    sys.modules["crewai.agent"] = None  # type: ignore[assignment]
    adapter = CrewAIExecutionAdapter()
    with pytest.raises(ImportError):
        adapter.install_patches(Budget(max_usd=5.00))


def test_install_patches_patches_execute_task() -> None:
    """install_patches() replaces Agent.execute_task with patched version."""
    _, Agent = _make_crewai_modules()
    original = Agent.execute_task
    adapter = CrewAIExecutionAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Agent.execute_task is not original
    adapter.remove_patches(b)


def test_remove_patches_restores_original_execute_task() -> None:
    """remove_patches() restores Agent.execute_task to the original."""
    _, Agent = _make_crewai_modules()
    original = Agent.execute_task
    adapter = CrewAIExecutionAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert Agent.execute_task is original


def test_remove_patches_noop_when_not_installed() -> None:
    """remove_patches() is idempotent when called without a prior install."""
    _make_crewai_modules()
    adapter = CrewAIExecutionAdapter()
    b = Budget(max_usd=5.00)
    # Should not raise
    adapter.remove_patches(b)
    adapter.remove_patches(b)


def test_refcount_nested_budgets_do_not_double_patch() -> None:
    """Second install_patches() call increments refcount but does not re-patch."""
    _, Agent = _make_crewai_modules()
    adapter = CrewAIExecutionAdapter()
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    adapter.install_patches(b1)
    patched = Agent.execute_task
    adapter.install_patches(b2)
    assert Agent.execute_task is patched  # not re-patched
    assert crewai_mod._execution_patch_refcount == 2
    adapter.remove_patches(b2)
    adapter.remove_patches(b1)


def test_refcount_patch_not_removed_until_last_budget_exits() -> None:
    """Patch is retained until the outermost budget exits."""
    _, Agent = _make_crewai_modules()
    adapter = CrewAIExecutionAdapter()
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    adapter.install_patches(b1)
    adapter.install_patches(b2)
    patched = Agent.execute_task
    adapter.remove_patches(b2)
    assert Agent.execute_task is patched  # still patched
    adapter.remove_patches(b1)


# ---------------------------------------------------------------------------
# Group 3: Pre-execution gate — agent cap
# ---------------------------------------------------------------------------


def test_agent_cap_exceeded_raises_before_execute() -> None:
    """AgentBudgetExceededError raised before execute_task body runs."""
    _, Agent = _make_crewai_modules(simulated_cost=0.05)

    with budget(max_usd=5.00) as b:
        b.agent("Senior Researcher", max_usd=0.10)
        b._agent_budgets["Senior Researcher"]._spent = 0.10  # exhaust cap

        agent = Agent(role="Senior Researcher")
        task = MockTask()
        with pytest.raises(AgentBudgetExceededError) as exc_info:
            agent.execute_task(task)

        # No spend attributed — gate fires before body runs
        assert b._spent == 0.0

    assert exc_info.value.agent_name == "Senior Researcher"


def test_agent_cap_not_exceeded_allows_execute() -> None:
    """No exception when agent cap has remaining budget."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.agent("Senior Researcher", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask()
        result = agent.execute_task(task)

    assert result == "done"
    assert b._agent_budgets["Senior Researcher"]._spent == 0.0


def test_agent_cap_on_outer_budget_enforced_in_nested_inner_budget() -> None:
    """Agent cap on outer budget is enforced when execution runs in inner context."""
    _make_crewai_modules()
    with budget(max_usd=5.00, name="outer") as outer:
        outer.agent("Senior Researcher", max_usd=0.10)
        outer._agent_budgets["Senior Researcher"]._spent = 0.10

        with budget(max_usd=2.00, name="inner"):
            from crewai.agent import Agent

            agent = Agent(role="Senior Researcher")
            task = MockTask()
            with pytest.raises(AgentBudgetExceededError):
                agent.execute_task(task)


def test_agent_cap_found_on_grandparent_budget() -> None:
    """Agent cap registered on grandparent is enforced two levels deep."""
    _make_crewai_modules()
    with budget(max_usd=10.00, name="root") as root:
        root.agent("Senior Researcher", max_usd=0.10)
        root._agent_budgets["Senior Researcher"]._spent = 0.10

        with budget(max_usd=5.00, name="mid"):
            with budget(max_usd=2.00, name="inner"):
                from crewai.agent import Agent

                agent = Agent(role="Senior Researcher")
                task = MockTask()
                with pytest.raises(AgentBudgetExceededError):
                    agent.execute_task(task)


def test_global_budget_exhausted_raises_agent_budget_exceeded_error() -> None:
    """AgentBudgetExceededError raised when global budget is exhausted."""
    _make_crewai_modules()
    with budget(max_usd=0.10) as b:
        b._spent = 0.10  # exhaust global budget
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask()
        with pytest.raises(AgentBudgetExceededError):
            agent.execute_task(task)


# ---------------------------------------------------------------------------
# Group 4: Pre-execution gate — task cap
# ---------------------------------------------------------------------------


def test_task_cap_exceeded_raises_before_execute() -> None:
    """TaskBudgetExceededError raised before execute_task body runs."""
    _make_crewai_modules(simulated_cost=0.05)

    with budget(max_usd=5.00) as b:
        b.task("research", max_usd=0.10)
        b._task_budgets["research"]._spent = 0.10

        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="research")

        with pytest.raises(TaskBudgetExceededError) as exc_info:
            agent.execute_task(task)

        # No spend attributed — gate fires before body runs
        assert b._spent == 0.0

    assert exc_info.value.task_name == "research"


def test_task_cap_not_exceeded_allows_execute() -> None:
    """No exception when task cap has remaining budget."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("research", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="research")
        result = agent.execute_task(task)

    assert result == "done"


def test_task_cap_takes_precedence_over_agent_cap() -> None:
    """TaskBudgetExceededError fires when both task and agent caps are exceeded."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("research", max_usd=0.10)
        b.agent("Senior Researcher", max_usd=0.10)
        b._task_budgets["research"]._spent = 0.10
        b._agent_budgets["Senior Researcher"]._spent = 0.10

        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="research")
        with pytest.raises(TaskBudgetExceededError):
            agent.execute_task(task)


def test_task_name_falls_back_to_description() -> None:
    """Task name falls back to description when name is None."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("Do research about AI", max_usd=0.10)
        b._task_budgets["Do research about AI"]._spent = 0.10

        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name=None, description="Do research about AI")  # type: ignore[arg-type]
        with pytest.raises(TaskBudgetExceededError) as exc_info:
            agent.execute_task(task)

    assert exc_info.value.task_name == "Do research about AI"


def test_task_name_empty_string_falls_back_to_description() -> None:
    """Empty string task name is treated as absent, falls back to description."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("Do research about AI", max_usd=0.10)
        b._task_budgets["Do research about AI"]._spent = 0.10

        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="", description="Do research about AI")
        with pytest.raises(TaskBudgetExceededError) as exc_info:
            agent.execute_task(task)

    assert exc_info.value.task_name == "Do research about AI"


# ---------------------------------------------------------------------------
# Group 5: Spend attribution
# ---------------------------------------------------------------------------


def test_spend_attributed_to_agent_component_budget() -> None:
    """Spend delta after execute_task is attributed to agent ComponentBudget."""
    _make_crewai_modules(simulated_cost=0.05)
    with budget(max_usd=5.00) as b:
        b.agent("Senior Researcher", max_usd=2.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask()
        agent.execute_task(task)

    assert b._agent_budgets["Senior Researcher"]._spent == pytest.approx(0.05)


def test_spend_attributed_to_task_component_budget() -> None:
    """Spend delta after execute_task is attributed to task ComponentBudget."""
    _make_crewai_modules(simulated_cost=0.05)
    with budget(max_usd=5.00) as b:
        b.task("research", max_usd=2.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="research")
        agent.execute_task(task)

    assert b._task_budgets["research"]._spent == pytest.approx(0.05)


def test_spend_attributed_to_both_agent_and_task() -> None:
    """Same spend delta attributed to both agent and task ComponentBudgets."""
    _make_crewai_modules(simulated_cost=0.07)
    with budget(max_usd=5.00) as b:
        b.agent("Senior Researcher", max_usd=2.00)
        b.task("research", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="research")
        agent.execute_task(task)

    assert b._agent_budgets["Senior Researcher"]._spent == pytest.approx(0.07)
    assert b._task_budgets["research"]._spent == pytest.approx(0.07)


def test_zero_spend_task_does_not_update_component_budgets() -> None:
    """Zero-cost execution does not change ComponentBudget._spent."""
    _make_crewai_modules(simulated_cost=0.0)
    with budget(max_usd=5.00) as b:
        b.agent("Senior Researcher", max_usd=2.00)
        b.task("research", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name="research")
        agent.execute_task(task)

    assert b._agent_budgets["Senior Researcher"]._spent == 0.0
    assert b._task_budgets["research"]._spent == 0.0


# ---------------------------------------------------------------------------
# Group 6: Silent-miss warnings
# ---------------------------------------------------------------------------


def test_unnamed_task_with_registered_cap_emits_warning() -> None:
    """warnings.warn emitted when task has no name and task caps are registered."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("something", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name=None, description="Do research")  # type: ignore[arg-type]
        with pytest.warns(UserWarning, match="task has no name"):
            agent.execute_task(task)


def test_unnamed_task_warning_includes_description() -> None:
    """Warning message includes (truncated) task description."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("something", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name=None, description="A" * 100)  # type: ignore[arg-type]
        with pytest.warns(UserWarning, match="description:"):
            agent.execute_task(task)


def test_unnamed_task_no_description_warning_message() -> None:
    """Warning message uses alternate text when task has no name AND no description."""
    _make_crewai_modules()
    with budget(max_usd=5.00) as b:
        b.task("something", max_usd=1.00)
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name=None, description="")  # type: ignore[arg-type]
        with pytest.warns(UserWarning, match="no name and no description"):
            agent.execute_task(task)


def test_unnamed_task_without_registered_cap_no_warning() -> None:
    """No warning emitted when task has no name but no task caps are registered."""
    _make_crewai_modules()
    with budget(max_usd=5.00):
        from crewai.agent import Agent

        agent = Agent(role="Senior Researcher")
        task = MockTask(name=None, description="Do research")  # type: ignore[arg-type]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            agent.execute_task(task)  # must not raise WarningException


# ---------------------------------------------------------------------------
# Group 7: Passthrough — no active budget
# ---------------------------------------------------------------------------


def test_no_active_budget_execute_task_passthrough() -> None:
    """execute_task runs normally when no budget() context is active."""
    _make_crewai_modules()
    adapter = CrewAIExecutionAdapter()
    adapter.install_patches(Budget(max_usd=5.00))

    from crewai.agent import Agent

    agent = Agent(role="Senior Researcher")
    task = MockTask()
    # No budget context — should run through without error
    result = agent.execute_task(task)
    assert result == "done"


# ---------------------------------------------------------------------------
# Group 8: ShekelRuntime integration
# ---------------------------------------------------------------------------


def test_runtime_probe_installs_crewai_adapter_when_crewai_installed() -> None:
    """ShekelRuntime.probe() activates CrewAIExecutionAdapter when crewai is present."""
    _, Agent = _make_crewai_modules()
    original = Agent.execute_task
    b = Budget(max_usd=5.00)
    ShekelRuntime._adapter_registry = [CrewAIExecutionAdapter]
    runtime = ShekelRuntime(b)
    runtime.probe()
    assert Agent.execute_task is not original
    runtime.release()


def test_runtime_release_removes_crewai_adapter() -> None:
    """ShekelRuntime.release() restores Agent.execute_task."""
    _, Agent = _make_crewai_modules()
    original = Agent.execute_task
    b = Budget(max_usd=5.00)
    ShekelRuntime._adapter_registry = [CrewAIExecutionAdapter]
    runtime = ShekelRuntime(b)
    runtime.probe()
    runtime.release()
    assert Agent.execute_task is original
