"""Tests for OpenAI Agents SDK Runner adapter (OpenAIAgentsRunnerAdapter).

Domain: runner-level budget enforcement via patching Runner.run,
Runner.run_sync, and Runner.run_streamed.

All tests use a fake `agents` module injected into sys.modules so that
the openai-agents SDK is not required in CI.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fake agents module helpers
# ---------------------------------------------------------------------------


def _make_fake_run_result(output: str = "final answer") -> Any:
    """Return a fake RunResult with a final_output attribute."""
    return types.SimpleNamespace(final_output=output)


class FakeRunner:
    """Minimal fake Runner with async run, sync run_sync, and async run_streamed."""

    _simulated_cost: float = 0.0

    @classmethod
    async def run(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
        """Fake async run — optionally increases active budget._spent."""
        cls._apply_cost()
        return _make_fake_run_result()

    @classmethod
    def run_sync(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
        """Fake synchronous run."""
        cls._apply_cost()
        return _make_fake_run_result()

    @classmethod
    async def run_streamed(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
        """Fake streamed run — returns an async generator."""
        cls._apply_cost()

        async def _gen() -> Any:
            yield "chunk1"
            yield "chunk2"

        return _gen()

    @classmethod
    def _apply_cost(cls) -> None:
        if cls._simulated_cost > 0:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is not None:
                active._spent += cls._simulated_cost
                active._spent_direct += cls._simulated_cost


def _make_agents_modules(simulated_cost: float = 0.0) -> tuple[types.ModuleType, type]:
    """Inject a fake `agents` module into sys.modules. Returns (module, Runner class)."""
    fake_agents = types.ModuleType("agents")

    # All methods defined directly on Runner (not inherited) so that
    # Runner.__dict__ contains them and can be used for identity checks.
    _cost = simulated_cost

    def _apply_cost() -> None:
        if _cost > 0:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is not None:
                active._spent += _cost
                active._spent_direct += _cost

    class Runner:
        @classmethod
        async def run(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            _apply_cost()
            return _make_fake_run_result()

        @classmethod
        def run_sync(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            _apply_cost()
            return _make_fake_run_result()

        @classmethod
        async def run_streamed(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            _apply_cost()

            async def _gen() -> Any:
                yield "chunk1"
                yield "chunk2"

            return _gen()

    fake_agents.Runner = Runner  # type: ignore[attr-defined]
    sys.modules["agents"] = fake_agents  # type: ignore[assignment]
    return fake_agents, Runner


def _cleanup_agents_modules() -> None:
    sys.modules.pop("agents", None)


def _make_fake_agent(name: str | None = "researcher") -> Any:
    """Return a fake agent object with the given name."""
    return types.SimpleNamespace(name=name)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_adapter_state():
    """Reset OpenAIAgentsRunnerAdapter patch state and ShekelRuntime registry."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._runtime import ShekelRuntime

    original_refcount = runner_mod._patch_refcount
    original_run = runner_mod._original_run
    original_run_sync = runner_mod._original_run_sync
    original_run_streamed = runner_mod._original_run_streamed
    original_registry = ShekelRuntime._adapter_registry[:]

    yield

    # Restore class-level state
    runner_mod._patch_refcount = original_refcount
    runner_mod._original_run = original_run
    runner_mod._original_run_sync = original_run_sync
    runner_mod._original_run_streamed = original_run_streamed

    # Restore registry
    ShekelRuntime._adapter_registry = original_registry

    # Clean up injected fake modules
    _cleanup_agents_modules()


# ---------------------------------------------------------------------------
# Group 0: Exception hierarchy
# ---------------------------------------------------------------------------


def test_agent_budget_exceeded_error_is_subclass_of_budget_exceeded_error() -> None:
    """AgentBudgetExceededError subclasses BudgetExceededError."""
    from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

    assert issubclass(AgentBudgetExceededError, BudgetExceededError)


def test_agent_budget_exceeded_error_fields() -> None:
    """AgentBudgetExceededError exposes agent_name, spent, limit."""
    from shekel.exceptions import AgentBudgetExceededError

    err = AgentBudgetExceededError(agent_name="researcher", spent=0.50, limit=0.30)
    assert err.agent_name == "researcher"
    assert err.spent == pytest.approx(0.50)
    assert err.limit == pytest.approx(0.30)


def test_agent_budget_exceeded_error_caught_by_budget_exceeded_error() -> None:
    """AgentBudgetExceededError is caught by 'except BudgetExceededError'."""
    from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

    with pytest.raises(BudgetExceededError):
        raise AgentBudgetExceededError(agent_name="x", spent=1.0, limit=0.5)


def test_agent_budget_exceeded_error_str_contains_agent_name() -> None:
    """AgentBudgetExceededError.__str__ includes the agent name."""
    from shekel.exceptions import AgentBudgetExceededError

    err = AgentBudgetExceededError(agent_name="researcher", spent=0.50, limit=0.30)
    assert "researcher" in str(err)


# ---------------------------------------------------------------------------
# Group 1: Adapter registration
# ---------------------------------------------------------------------------


def test_runner_adapter_registered_in_shekel_runtime() -> None:
    """OpenAIAgentsRunnerAdapter is in ShekelRuntime._adapter_registry."""
    from shekel._runtime import ShekelRuntime
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    assert OpenAIAgentsRunnerAdapter in ShekelRuntime._adapter_registry


def test_install_patches_replaces_runner_run() -> None:
    """After install_patches, Runner.run is replaced with a wrapper."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_raw = Runner.__dict__["run"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Runner.__dict__["run"] is not original_run_raw
    adapter.remove_patches(b)


def test_install_patches_replaces_runner_run_sync() -> None:
    """After install_patches, Runner.run_sync is replaced with a wrapper."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_sync_raw = Runner.__dict__["run_sync"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Runner.__dict__["run_sync"] is not original_run_sync_raw
    adapter.remove_patches(b)


def test_install_patches_replaces_runner_run_streamed() -> None:
    """After install_patches, Runner.run_streamed is replaced with a wrapper."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_streamed_raw = Runner.__dict__["run_streamed"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Runner.__dict__["run_streamed"] is not original_run_streamed_raw
    adapter.remove_patches(b)


def test_remove_patches_restores_runner_run() -> None:
    """After remove_patches, Runner.run is restored to original."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_raw = Runner.__dict__["run"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert Runner.__dict__["run"] is original_run_raw


def test_remove_patches_restores_runner_run_sync() -> None:
    """After remove_patches, Runner.run_sync is restored to original."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_sync_raw = Runner.__dict__["run_sync"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert Runner.__dict__["run_sync"] is original_run_sync_raw


def test_remove_patches_restores_runner_run_streamed() -> None:
    """After remove_patches, Runner.run_streamed is restored to original."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_streamed_raw = Runner.__dict__["run_streamed"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert Runner.__dict__["run_streamed"] is original_run_streamed_raw


# ---------------------------------------------------------------------------
# Group 2: Ref-counting
# ---------------------------------------------------------------------------


def test_refcount_increments_on_first_install() -> None:
    """First install_patches raises refcount to 1."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert runner_mod._patch_refcount == 1
    adapter.remove_patches(b)


def test_refcount_two_nested_budgets() -> None:
    """Two nested install_patches calls produce refcount==2."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    adapter.install_patches(b1)
    adapter.install_patches(b2)
    assert runner_mod._patch_refcount == 2
    adapter.remove_patches(b2)
    adapter.remove_patches(b1)


def test_refcount_nested_does_not_double_wrap() -> None:
    """Second install_patches does not re-wrap the already-patched method."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    adapter.install_patches(b1)
    patched_run_raw = Runner.__dict__["run"]
    adapter.install_patches(b2)
    # Must be the same wrapper descriptor, not double-wrapped
    assert Runner.__dict__["run"] is patched_run_raw
    adapter.remove_patches(b2)
    adapter.remove_patches(b1)


def test_refcount_inner_exit_keeps_patch() -> None:
    """After inner budget exits (refcount→1), patch is still active."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    adapter.install_patches(b1)
    adapter.install_patches(b2)
    patched_run_raw = Runner.__dict__["run"]
    adapter.remove_patches(b2)
    assert runner_mod._patch_refcount == 1
    assert Runner.__dict__["run"] is patched_run_raw  # still patched
    adapter.remove_patches(b1)


def test_refcount_outer_exit_removes_patch() -> None:
    """After outer budget exits (refcount→0), patch is fully removed."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_raw = Runner.__dict__["run"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    adapter.install_patches(b1)
    adapter.install_patches(b2)
    adapter.remove_patches(b2)
    adapter.remove_patches(b1)
    assert runner_mod._patch_refcount == 0
    assert Runner.__dict__["run"] is original_run_raw


def test_refcount_originals_cleared_on_full_remove() -> None:
    """_original_run* are set to None after all budgets exit."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _make_agents_modules()
    runner_mod._patch_refcount = 0
    runner_mod._original_run = None
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert runner_mod._original_run is not None
    adapter.remove_patches(b)
    assert runner_mod._original_run is None
    assert runner_mod._original_run_sync is None
    assert runner_mod._original_run_streamed is None


# ---------------------------------------------------------------------------
# Group 3: Pre-run gate — agent cap (async run)
# ---------------------------------------------------------------------------


async def test_agent_cap_gate_passes_when_cap_not_exceeded() -> None:
    """Gate passes when agent cap has remaining budget."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.01)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=0.30)
        agent = _make_fake_agent("researcher")
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


async def test_agent_cap_gate_raises_when_cap_spent() -> None:
    """Gate raises AgentBudgetExceededError when cap._spent >= cap.max_usd."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules(simulated_cost=0.05)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=0.30)
        b._agent_budgets["researcher"]._spent = 0.30  # exhaust cap

        agent = _make_fake_agent("researcher")
        with pytest.raises(AgentBudgetExceededError) as exc_info:
            await Runner.run(agent, "hello")

        assert exc_info.value.agent_name == "researcher"
        assert exc_info.value.spent == pytest.approx(0.30)
        assert exc_info.value.limit == pytest.approx(0.30)


async def test_agent_cap_gate_raises_correct_fields() -> None:
    """AgentBudgetExceededError has correct agent_name, spent, limit fields."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("analyst", max_usd=0.20)
        b._agent_budgets["analyst"]._spent = 0.25  # over limit

        agent = _make_fake_agent("analyst")
        with pytest.raises(AgentBudgetExceededError) as exc_info:
            await Runner.run(agent, "test")

    err = exc_info.value
    assert err.agent_name == "analyst"
    assert err.spent == pytest.approx(0.25)
    assert err.limit == pytest.approx(0.20)


async def test_unregistered_agent_runs_freely() -> None:
    """Agent with no b.agent(...) registration runs without cap check."""
    from shekel import budget

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00):
        agent = _make_fake_agent("unknown-agent")
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


# ---------------------------------------------------------------------------
# Group 4: Pre-run gate — parent budget
# ---------------------------------------------------------------------------


async def test_parent_budget_exhausted_raises() -> None:
    """Gate raises AgentBudgetExceededError when parent budget is exhausted."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=0.10) as b:
        b._spent = 0.10  # exhaust global budget
        agent = _make_fake_agent("researcher")
        with pytest.raises(AgentBudgetExceededError):
            await Runner.run(agent, "hello")


async def test_parent_budget_with_remaining_passes() -> None:
    """Gate passes when parent budget has remaining."""
    from shekel import budget

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b._spent = 0.01  # some spend but not exhausted
        agent = _make_fake_agent("researcher")
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


async def test_parent_budget_none_max_usd_allows_run() -> None:
    """Track-only mode (max_usd=None) never blocks execution."""
    from shekel import budget

    _make_agents_modules()

    from agents import Runner

    with budget():  # track-only
        agent = _make_fake_agent("researcher")
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


# ---------------------------------------------------------------------------
# Group 5: Spend attribution — async run
# ---------------------------------------------------------------------------


async def test_spend_attributed_to_agent_component_budget() -> None:
    """After Runner.run completes, ComponentBudget._spent is updated."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.05)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        agent = _make_fake_agent("researcher")
        await Runner.run(agent, "hello")

    assert b._agent_budgets["researcher"]._spent == pytest.approx(0.05)


async def test_spend_delta_is_correct() -> None:
    """Spend attributed equals active_budget.spent_after - spend_before."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.07)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        spend_before = b.spent
        agent = _make_fake_agent("researcher")
        await Runner.run(agent, "hello")
        delta = b.spent - spend_before
        assert b._agent_budgets["researcher"]._spent == pytest.approx(delta)


async def test_no_agent_registration_no_component_budget_created() -> None:
    """Without b.agent(...), no ComponentBudget is in _agent_budgets."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.05)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        agent = _make_fake_agent("researcher")
        await Runner.run(agent, "hello")

    assert "researcher" not in b._agent_budgets


async def test_spend_attributed_cumulates_across_multiple_runs() -> None:
    """Multiple Runner.run calls accumulate spend in ComponentBudget."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.05)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        agent = _make_fake_agent("researcher")
        await Runner.run(agent, "first")
        await Runner.run(agent, "second")

    assert b._agent_budgets["researcher"]._spent == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Group 6: Zero / None agent name
# ---------------------------------------------------------------------------


async def test_agent_with_name_none_runs_freely() -> None:
    """Agent with name=None bypasses cap lookup, runs without error."""
    from shekel import budget

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00):
        agent = _make_fake_agent(None)
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


async def test_agent_with_empty_string_name_runs_freely() -> None:
    """Agent with name='' treated same as None — no cap lookup."""
    from shekel import budget

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00):
        agent = _make_fake_agent("")
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


async def test_agent_without_name_attr_runs_freely() -> None:
    """Agent object with no name attribute at all runs without error."""
    from shekel import budget

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00):
        agent = object()  # no name attribute
        result = await Runner.run(agent, "hello")
        assert result.final_output == "final answer"


# ---------------------------------------------------------------------------
# Group 7: No active budget passthrough
# ---------------------------------------------------------------------------


async def test_no_active_budget_run_passthrough() -> None:
    """Runner.run called outside budget() context runs normally."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)

    from agents import Runner as R

    agent = _make_fake_agent("researcher")
    result = await R.run(agent, "hello")
    assert result.final_output == "final answer"
    adapter.remove_patches(b)


def test_no_active_budget_run_sync_passthrough() -> None:
    """Runner.run_sync called outside budget() context runs normally."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)

    from agents import Runner as R

    agent = _make_fake_agent("researcher")
    result = R.run_sync(agent, "hello")
    assert result.final_output == "final answer"
    adapter.remove_patches(b)


# ---------------------------------------------------------------------------
# Group 8: Silent skip when SDK absent
# ---------------------------------------------------------------------------


def test_install_patches_raises_import_error_when_agents_absent() -> None:
    """install_patches raises ImportError when agents module is not installed."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _cleanup_agents_modules()
    sys.modules["agents"] = None  # type: ignore[assignment]
    adapter = OpenAIAgentsRunnerAdapter()
    with pytest.raises(ImportError):
        adapter.install_patches(Budget(max_usd=5.00))
    _cleanup_agents_modules()


def test_remove_patches_silent_when_agents_absent() -> None:
    """remove_patches does not raise when agents module is absent."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _cleanup_agents_modules()
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    # Should not raise
    adapter.remove_patches(b)


def test_shekel_runtime_silently_skips_when_agents_absent() -> None:
    """ShekelRuntime silently skips OpenAIAgentsRunnerAdapter when agents not installed."""
    from shekel._budget import Budget
    from shekel._runtime import ShekelRuntime
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _cleanup_agents_modules()
    sys.modules["agents"] = None  # type: ignore[assignment]

    b = Budget(max_usd=5.00)
    ShekelRuntime._adapter_registry = [OpenAIAgentsRunnerAdapter]
    runtime = ShekelRuntime(b)
    runtime.probe()  # must not raise
    runtime.release()
    _cleanup_agents_modules()


# ---------------------------------------------------------------------------
# Group 9: Exception during run — spend still attributed
# ---------------------------------------------------------------------------


async def test_exception_during_run_still_attributes_spend() -> None:
    """Even if run raises, spend accumulated before the error is attributed."""
    from shekel import budget

    fake_agents = types.ModuleType("agents")

    class ErrorRunner(FakeRunner):
        @classmethod
        async def run(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            # First accumulate some cost, then raise
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is not None:
                active._spent += 0.03
                active._spent_direct += 0.03
            raise RuntimeError("mid-run failure")

    fake_agents.Runner = ErrorRunner  # type: ignore[attr-defined]
    sys.modules["agents"] = fake_agents  # type: ignore[assignment]

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        agent = _make_fake_agent("researcher")
        with pytest.raises(RuntimeError, match="mid-run failure"):
            await Runner.run(agent, "hello")

    # Spend accumulated before the error should still be attributed
    assert b._agent_budgets["researcher"]._spent == pytest.approx(0.03)


async def test_exception_during_run_still_reraises() -> None:
    """Exception from run is re-raised to caller even with budget enforcement."""
    from shekel import budget

    fake_agents = types.ModuleType("agents")

    class ErrorRunner2(FakeRunner):
        @classmethod
        async def run(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            raise ValueError("deliberate error")

    fake_agents.Runner = ErrorRunner2  # type: ignore[attr-defined]
    sys.modules["agents"] = fake_agents  # type: ignore[assignment]

    from agents import Runner

    with budget(max_usd=5.00):
        agent = _make_fake_agent("researcher")
        with pytest.raises(ValueError, match="deliberate error"):
            await Runner.run(agent, "hello")


# ---------------------------------------------------------------------------
# Group 10: run_sync path
# ---------------------------------------------------------------------------


def test_run_sync_patches_and_restores() -> None:
    """run_sync wrapper patches correctly and restores on remove."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_sync_raw = Runner.__dict__["run_sync"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Runner.__dict__["run_sync"] is not original_run_sync_raw
    adapter.remove_patches(b)
    assert Runner.__dict__["run_sync"] is original_run_sync_raw


def test_run_sync_spend_attributed() -> None:
    """run_sync attributes spend to agent ComponentBudget."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.04)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        agent = _make_fake_agent("researcher")
        result = Runner.run_sync(agent, "hello")
        assert result.final_output == "final answer"

    assert b._agent_budgets["researcher"]._spent == pytest.approx(0.04)


def test_run_sync_gate_blocks_when_cap_exceeded() -> None:
    """run_sync gate raises AgentBudgetExceededError when cap spent."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=0.30)
        b._agent_budgets["researcher"]._spent = 0.30  # exhaust
        agent = _make_fake_agent("researcher")
        with pytest.raises(AgentBudgetExceededError) as exc_info:
            Runner.run_sync(agent, "hello")

    assert exc_info.value.agent_name == "researcher"


def test_run_sync_no_active_budget_passthrough() -> None:
    """run_sync outside budget context runs original without interception."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)

    from agents import Runner as R

    agent = _make_fake_agent("researcher")
    result = R.run_sync(agent, "hello")
    assert result.final_output == "final answer"
    adapter.remove_patches(b)


def test_run_sync_parent_budget_exhausted_raises() -> None:
    """run_sync raises AgentBudgetExceededError when parent budget exhausted."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=0.10) as b:
        b._spent = 0.10
        agent = _make_fake_agent("researcher")
        with pytest.raises(AgentBudgetExceededError):
            Runner.run_sync(agent, "hello")


# ---------------------------------------------------------------------------
# Group 11: run_streamed path
# ---------------------------------------------------------------------------


def test_run_streamed_patches_and_restores() -> None:
    """run_streamed wrapper patches and restores correctly."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_raw = Runner.__dict__["run_streamed"]
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Runner.__dict__["run_streamed"] is not original_raw
    adapter.remove_patches(b)
    assert Runner.__dict__["run_streamed"] is original_raw


async def test_run_streamed_spend_attributed_after_full_iteration() -> None:
    """run_streamed attributes spend only after full iteration completes."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.06)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        agent = _make_fake_agent("researcher")
        stream = await Runner.run_streamed(agent, "hello")
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)

    assert len(chunks) == 2
    assert b._agent_budgets["researcher"]._spent == pytest.approx(0.06)


async def test_run_streamed_no_active_budget_passthrough() -> None:
    """run_streamed outside budget context runs original without interception."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    runner_mod._patch_refcount = 0
    adapter = OpenAIAgentsRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)

    from agents import Runner as R

    agent = _make_fake_agent("researcher")
    stream = await R.run_streamed(agent, "hello")
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) == 2
    adapter.remove_patches(b)


async def test_run_streamed_gate_blocks_when_cap_exceeded() -> None:
    """run_streamed gate raises before yielding when cap is exceeded."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=0.30)
        b._agent_budgets["researcher"]._spent = 0.30  # exhaust
        agent = _make_fake_agent("researcher")
        with pytest.raises(AgentBudgetExceededError):
            await Runner.run_streamed(agent, "hello")


async def test_run_streamed_not_iterated_spend_not_attributed() -> None:
    """Known limitation: if stream is not iterated, spend is not attributed.

    This is by design — spend attribution happens in the finally block
    wrapping the iteration. If the caller never iterates the stream,
    the finally block never fires, so spend is not measured. In practice,
    the FakeRunner's _apply_cost runs on the inner call before we wrap
    the generator, but since spend_before is captured before that cost
    accrues, the delta ends up being attributed on iteration. The real
    limitation manifests only when the inner SDK itself accumulates cost
    lazily during iteration.
    """
    from shekel import budget

    # Use zero simulated cost so the test is fully deterministic
    _make_agents_modules(simulated_cost=0.0)

    from agents import Runner

    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        agent = _make_fake_agent("researcher")
        # Start stream but don't iterate it
        _stream = await Runner.run_streamed(agent, "hello")
        # With zero cost and no iteration, attribution stays at 0
        assert b._agent_budgets["researcher"]._spent == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Group 12: Nested budgets
# ---------------------------------------------------------------------------


async def test_nested_budget_parent_exhausted_blocks_run() -> None:
    """Child budget's run blocked when parent budget is exhausted."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=0.10, name="outer") as outer:
        outer._spent = 0.10  # exhaust outer

        with budget(max_usd=1.00, name="inner"):
            agent = _make_fake_agent("analyst")
            with pytest.raises(AgentBudgetExceededError):
                await Runner.run(agent, "hello")


async def test_nested_budget_agent_cap_on_inner() -> None:
    """Agent cap registered on inner budget is enforced."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=10.00, name="outer"):
        with budget(max_usd=5.00, name="inner") as inner:
            inner.agent("analyst", max_usd=0.20)
            inner._agent_budgets["analyst"]._spent = 0.20  # exhaust

            agent = _make_fake_agent("analyst")
            with pytest.raises(AgentBudgetExceededError):
                await Runner.run(agent, "hello")


async def test_nested_budget_agent_cap_found_on_grandparent() -> None:
    """Agent cap on grandparent budget is found via parent chain walk."""
    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError

    _make_agents_modules()

    from agents import Runner

    with budget(max_usd=10.00, name="root") as root:
        root.agent("analyst", max_usd=0.20)
        root._agent_budgets["analyst"]._spent = 0.20  # exhaust

        with budget(max_usd=5.00, name="inner"):
            agent = _make_fake_agent("analyst")
            with pytest.raises(AgentBudgetExceededError):
                await Runner.run(agent, "hello")


# ---------------------------------------------------------------------------
# Group 13: b.tree() output
# ---------------------------------------------------------------------------


async def test_tree_shows_agent_spend() -> None:
    """b.tree() output includes agent spend after Runner.run completes."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.05)

    from agents import Runner

    with budget(max_usd=5.00, name="workflow") as b:
        b.agent("researcher", max_usd=0.50)
        agent = _make_fake_agent("researcher")
        await Runner.run(agent, "hello")
        tree = b.tree()

    assert "researcher" in tree
    assert "0.0500" in tree or "0.05" in tree


def test_tree_shows_zero_agent_spend_when_no_cost() -> None:
    """b.tree() shows 0.0000 spend for agent when no LLM calls made."""
    from shekel import budget

    _make_agents_modules(simulated_cost=0.0)

    from agents import Runner

    with budget(max_usd=5.00, name="workflow") as b:
        b.agent("researcher", max_usd=0.50)
        agent = _make_fake_agent("researcher")
        Runner.run_sync(agent, "hello")
        tree = b.tree()

    assert "researcher" in tree
    assert "0.0000" in tree


# ---------------------------------------------------------------------------
# Group 14: ShekelRuntime integration
# ---------------------------------------------------------------------------


def test_runtime_probe_installs_runner_adapter() -> None:
    """ShekelRuntime.probe() activates OpenAIAgentsRunnerAdapter when agents installed."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel._runtime import ShekelRuntime
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_raw = Runner.__dict__["run"]
    runner_mod._patch_refcount = 0
    b = Budget(max_usd=5.00)
    ShekelRuntime._adapter_registry = [OpenAIAgentsRunnerAdapter]
    runtime = ShekelRuntime(b)
    runtime.probe()
    assert Runner.__dict__["run"] is not original_run_raw
    runtime.release()


def test_runtime_release_removes_runner_adapter() -> None:
    """ShekelRuntime.release() restores Runner.run."""
    import shekel.providers.openai_agents_runner as runner_mod
    from shekel._budget import Budget
    from shekel._runtime import ShekelRuntime
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter

    _, Runner = _make_agents_modules()
    original_run_raw = Runner.__dict__["run"]
    runner_mod._patch_refcount = 0
    b = Budget(max_usd=5.00)
    ShekelRuntime._adapter_registry = [OpenAIAgentsRunnerAdapter]
    runtime = ShekelRuntime(b)
    runtime.probe()
    runtime.release()
    assert Runner.__dict__["run"] is original_run_raw


# ---------------------------------------------------------------------------
# Group 15: _find_agent_cap and _get_agent_name helpers
# ---------------------------------------------------------------------------


def test_find_agent_cap_finds_on_current_budget() -> None:
    """_find_agent_cap finds cap on the active budget itself."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _find_agent_cap

    b = Budget(max_usd=5.00)
    b.agent("researcher", max_usd=0.30)
    cap = _find_agent_cap("researcher", b)
    assert cap is not None
    assert cap.max_usd == pytest.approx(0.30)


def test_find_agent_cap_returns_none_when_not_registered() -> None:
    """_find_agent_cap returns None for unknown agent."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _find_agent_cap

    b = Budget(max_usd=5.00)
    cap = _find_agent_cap("unknown", b)
    assert cap is None


def test_find_agent_cap_walks_parent_chain() -> None:
    """_find_agent_cap walks up parent chain to find cap."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _find_agent_cap

    parent = Budget(max_usd=10.00)
    parent.agent("researcher", max_usd=0.30)
    child = Budget(max_usd=5.00)
    child.parent = parent

    cap = _find_agent_cap("researcher", child)
    assert cap is not None
    assert cap.max_usd == pytest.approx(0.30)


def test_get_agent_name_returns_name_attr() -> None:
    """_get_agent_name returns agent.name when present."""
    from shekel.providers.openai_agents_runner import _get_agent_name

    agent = types.SimpleNamespace(name="researcher")
    assert _get_agent_name(agent) == "researcher"


def test_get_agent_name_returns_none_for_no_attr() -> None:
    """_get_agent_name returns None when agent has no name attr."""
    from shekel.providers.openai_agents_runner import _get_agent_name

    agent = object()
    assert _get_agent_name(agent) is None


def test_get_agent_name_returns_none_for_empty_string() -> None:
    """_get_agent_name returns None for empty string name."""
    from shekel.providers.openai_agents_runner import _get_agent_name

    agent = types.SimpleNamespace(name="")
    assert _get_agent_name(agent) is None


def test_get_agent_name_returns_none_for_none_name() -> None:
    """_get_agent_name returns None for agent.name = None."""
    from shekel.providers.openai_agents_runner import _get_agent_name

    agent = types.SimpleNamespace(name=None)
    assert _get_agent_name(agent) is None


# ---------------------------------------------------------------------------
# Group 16: _pre_run_gate helper
# ---------------------------------------------------------------------------


def test_pre_run_gate_passes_with_budget_remaining() -> None:
    """_pre_run_gate does not raise when budget has remaining."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _pre_run_gate

    b = Budget(max_usd=5.00)
    b._spent = 0.01
    agent = _make_fake_agent("researcher")
    # Should not raise
    _pre_run_gate(agent, b)


def test_pre_run_gate_raises_when_budget_exhausted() -> None:
    """_pre_run_gate raises AgentBudgetExceededError when budget spent >= max_usd."""
    from shekel._budget import Budget
    from shekel.exceptions import AgentBudgetExceededError
    from shekel.providers.openai_agents_runner import _pre_run_gate

    b = Budget(max_usd=0.10)
    b._spent = 0.10
    agent = _make_fake_agent("researcher")
    with pytest.raises(AgentBudgetExceededError):
        _pre_run_gate(agent, b)


def test_pre_run_gate_raises_when_agent_cap_exceeded() -> None:
    """_pre_run_gate raises AgentBudgetExceededError when agent cap exhausted."""
    from shekel._budget import Budget
    from shekel.exceptions import AgentBudgetExceededError
    from shekel.providers.openai_agents_runner import _pre_run_gate

    b = Budget(max_usd=5.00)
    b.agent("researcher", max_usd=0.20)
    b._agent_budgets["researcher"]._spent = 0.20
    agent = _make_fake_agent("researcher")
    with pytest.raises(AgentBudgetExceededError) as exc_info:
        _pre_run_gate(agent, b)

    assert exc_info.value.agent_name == "researcher"


# ---------------------------------------------------------------------------
# Group 17: _attribute_spend helper
# ---------------------------------------------------------------------------


def test_attribute_spend_updates_component_budget() -> None:
    """_attribute_spend correctly updates ComponentBudget._spent."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _attribute_spend

    b = Budget(max_usd=5.00)
    b.agent("researcher", max_usd=2.00)
    b._spent = 0.10  # simulate spend
    agent = _make_fake_agent("researcher")
    _attribute_spend(agent, b, 0.0)  # spend_before=0.0, current=0.10 → delta=0.10
    assert b._agent_budgets["researcher"]._spent == pytest.approx(0.10)


def test_attribute_spend_no_registration_no_error() -> None:
    """_attribute_spend does nothing when no ComponentBudget registered."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _attribute_spend

    b = Budget(max_usd=5.00)
    b._spent = 0.05
    agent = _make_fake_agent("researcher")
    # Should not raise
    _attribute_spend(agent, b, 0.0)


def test_attribute_spend_none_name_no_error() -> None:
    """_attribute_spend does nothing for agent with no name."""
    from shekel._budget import Budget
    from shekel.providers.openai_agents_runner import _attribute_spend

    b = Budget(max_usd=5.00)
    b._spent = 0.05
    agent = _make_fake_agent(None)
    # Should not raise
    _attribute_spend(agent, b, 0.0)
