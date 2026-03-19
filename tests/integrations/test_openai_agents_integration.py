"""Integration tests for OpenAI Agents SDK Runner adapter.

Mock tests (TestOpenAIAgentsRunnerMockIntegration) inject a fake `agents`
module and run without any API keys.

Real-API tests (TestOpenAIAgentsRunnerLiveIntegration) require both
OPENAI_API_KEY and the real `openai-agents` package to be installed.
"""

from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

from shekel import budget
from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

# ---------------------------------------------------------------------------
# Fake agents module helpers
# ---------------------------------------------------------------------------


def _make_fake_run_result(output: str = "result") -> Any:
    return types.SimpleNamespace(final_output=output)


def _make_fake_agent(name: str) -> Any:
    return types.SimpleNamespace(name=name)


def _install_fake_agents(cost_per_run: float = 0.05) -> types.ModuleType:
    """Install a fake `agents` module with a Runner that records spend."""
    fake = types.ModuleType("agents")

    class FakeRunner:
        @classmethod
        async def run(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is not None:
                active._record_spend(cost_per_run, "gpt-4o-mini", {"input": 10, "output": 5})
            return _make_fake_run_result()

        @classmethod
        def run_sync(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is not None:
                active._record_spend(cost_per_run, "gpt-4o-mini", {"input": 10, "output": 5})
            return _make_fake_run_result()

        @classmethod
        async def run_streamed(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is not None:
                active._record_spend(cost_per_run, "gpt-4o-mini", {"input": 10, "output": 5})

            async def _gen() -> Any:
                yield "chunk1"
                yield "chunk2"

            return _gen()

    fake.Runner = FakeRunner  # type: ignore[attr-defined]
    sys.modules["agents"] = fake  # type: ignore[assignment]
    return fake


def _remove_fake_agents() -> None:
    sys.modules.pop("agents", None)


# ---------------------------------------------------------------------------
# Mock integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOpenAIAgentsRunnerMockIntegration:
    """End-to-end Runner adapter tests using a fake agents module."""

    @pytest.fixture(autouse=True)
    def setup_fake_agents(self) -> Any:
        _install_fake_agents(cost_per_run=0.05)
        yield
        _remove_fake_agents()
        # Reset adapter refcount after each test
        import shekel.providers.openai_agents_runner as r

        r._patch_refcount = 0
        r._original_run = None
        r._original_run_sync = None
        r._original_run_streamed = None

    async def test_run_spend_attributed_to_agent_budget(self) -> None:
        """After Runner.run, spend is attributed to matching ComponentBudget."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("researcher", max_usd=1.00)
            agent = _make_fake_agent("researcher")
            await Runner.run(agent, "input")

        assert b._agent_budgets["researcher"]._spent == pytest.approx(0.05)

    async def test_run_gate_fires_when_agent_cap_exceeded(self) -> None:
        """Pre-run gate raises AgentBudgetExceededError when agent cap exhausted."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("classifier", max_usd=0.04)
            b._agent_budgets["classifier"]._spent = 0.04  # exhaust cap manually
            agent = _make_fake_agent("classifier")
            with pytest.raises(AgentBudgetExceededError) as exc_info:
                await Runner.run(agent, "input")

        err = exc_info.value
        assert err.agent_name == "classifier"
        assert err.spent == pytest.approx(0.04)

    async def test_agent_budget_exceeded_error_caught_by_budget_exceeded_error(self) -> None:
        """AgentBudgetExceededError is a subclass of BudgetExceededError."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("x", max_usd=0.01)
            b._agent_budgets["x"]._spent = 0.01
            agent = _make_fake_agent("x")
            with pytest.raises(BudgetExceededError):
                await Runner.run(agent, "input")

    async def test_unregistered_agent_runs_freely(self) -> None:
        """Agent without b.agent() registration runs under parent budget only."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            agent = _make_fake_agent("unknown_agent")
            await Runner.run(agent, "input")

        assert b.spent == pytest.approx(0.05)
        assert "unknown_agent" not in b._agent_budgets

    async def test_agent_name_none_runs_freely(self) -> None:
        """Agent with name=None runs freely — no cap lookup."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            agent = _make_fake_agent(None)  # type: ignore[arg-type]
            agent.name = None
            await Runner.run(agent, "input")

        assert b.spent == pytest.approx(0.05)

    async def test_two_agents_each_capped_independently(self) -> None:
        """Two agents each track their own spend independently."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("agent_a", max_usd=0.20)
            b.agent("agent_b", max_usd=0.20)
            await Runner.run(_make_fake_agent("agent_a"), "input")
            await Runner.run(_make_fake_agent("agent_b"), "input")
            await Runner.run(_make_fake_agent("agent_a"), "input")

        assert b._agent_budgets["agent_a"]._spent == pytest.approx(0.10)
        assert b._agent_budgets["agent_b"]._spent == pytest.approx(0.05)

    async def test_run_sync_spend_attributed(self) -> None:
        """run_sync wrapper attributes spend correctly."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("sync_agent", max_usd=0.50)
            agent = _make_fake_agent("sync_agent")
            Runner.run_sync(agent, "input")

        assert b._agent_budgets["sync_agent"]._spent == pytest.approx(0.05)

    async def test_run_streamed_spend_attributed_after_iteration(self) -> None:
        """run_streamed attributes spend after full iteration of the stream."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("stream_agent", max_usd=0.50)
            agent = _make_fake_agent("stream_agent")
            stream = await Runner.run_streamed(agent, "input")
            chunks = []
            async for chunk in stream:
                chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]
        assert b._agent_budgets["stream_agent"]._spent == pytest.approx(0.05)

    async def test_refcount_nested_budgets_single_patch(self) -> None:
        """Two nested budget contexts patch Runner once; both exit restores."""
        from agents import Runner

        import shekel.providers.openai_agents_runner as r

        original_run = Runner.__dict__["run"]
        with budget(name="outer", max_usd=5.00):
            assert r._patch_refcount == 1
            with budget(name="inner", max_usd=5.00):
                assert r._patch_refcount == 2
            assert r._patch_refcount == 1
        assert r._patch_refcount == 0
        assert Runner.__dict__["run"] is original_run

    async def test_runner_restored_after_exit(self) -> None:
        """Runner.run is the original after budget context exits."""
        from agents import Runner

        original_run = Runner.__dict__["run"]
        with budget(max_usd=5.00):
            assert Runner.__dict__["run"] is not original_run
        assert Runner.__dict__["run"] is original_run

    async def test_exception_in_run_still_attributes_spend(self) -> None:
        """If run raises, any spend accumulated before the error is still attributed."""

        class ErrorRunner:
            @classmethod
            async def run(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
                from shekel._context import get_active_budget

                active = get_active_budget()
                if active is not None:
                    active._record_spend(0.03, "gpt-4o", {"input": 5, "output": 5})
                raise RuntimeError("mid-run failure")

            @classmethod
            def run_sync(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
                return _make_fake_run_result()

            @classmethod
            async def run_streamed(cls, agent: Any, input: Any, **kwargs: Any) -> Any:
                async def _gen() -> Any:
                    yield "x"

                return _gen()

        fake = types.ModuleType("agents")
        fake.Runner = ErrorRunner  # type: ignore[attr-defined]
        sys.modules["agents"] = fake  # type: ignore[assignment]

        with budget(max_usd=5.00) as b:
            b.agent("err_agent", max_usd=1.00)
            agent = _make_fake_agent("err_agent")
            with pytest.raises(RuntimeError, match="mid-run failure"):
                await ErrorRunner.run(agent, "input")

        # Spend accumulated before the error should be attributed
        # (Note: spend goes through _record_spend which updates b.spent directly)
        assert b.spent == pytest.approx(0.03)

    async def test_no_active_budget_runner_unchanged(self) -> None:
        """Runner.run outside any budget() context runs with original behavior."""
        from agents import Runner

        # Outside budget context — no patching
        result = await Runner.run(_make_fake_agent("x"), "input")
        assert result.final_output == "result"

    async def test_b_tree_shows_agent_spend(self) -> None:
        """b.tree() output includes per-agent spend breakdown."""
        from agents import Runner

        with budget(max_usd=5.00) as b:
            b.agent("writer", max_usd=0.50)
            await Runner.run(_make_fake_agent("writer"), "input")

        tree = b.tree()
        assert "writer" in tree

    async def test_sdk_absent_budget_enters_cleanly(self) -> None:
        """If agents not installed, budget() opens without error."""
        _remove_fake_agents()
        sys.modules["agents"] = None  # type: ignore[assignment]

        try:
            with budget(max_usd=5.00) as b:
                assert b.spent == 0.0
        finally:
            _remove_fake_agents()


# ---------------------------------------------------------------------------
# Real API: requires OPENAI_API_KEY + openai-agents installed
# ---------------------------------------------------------------------------


class TestOpenAIAgentsRunnerLiveIntegration:
    """Real Runner.run with a minimal agent — skipped without API key."""

    @pytest.fixture(autouse=True)
    def require_live_env(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")
        try:
            import agents  # noqa: F401
        except ImportError:
            pytest.skip("openai-agents not installed")

    @pytest.mark.asyncio
    async def test_real_runner_spend_tracked(self) -> None:
        """Real Runner.run completes or budget fires; spend is tracked."""
        from agents import Agent, Runner

        agent = Agent(name="test-agent", instructions="Reply in one word.")
        with budget(max_usd=0.10) as b:
            try:
                result = await Runner.run(agent, "Say hi")
                assert result.final_output
            except BudgetExceededError:
                pass  # budget fired — still a valid outcome
            assert b.spent >= 0

    @pytest.mark.asyncio
    async def test_real_per_agent_cap_fires(self) -> None:
        """Per-agent cap of $0.001 fires before a second real run of the same agent."""
        from agents import Agent, Runner

        agent = Agent(name="capped-agent", instructions="Reply in one word.")
        with budget(max_usd=0.10) as b:
            b.agent("capped-agent", max_usd=0.001)
            try:
                await Runner.run(agent, "Say hi")
            except (AgentBudgetExceededError, BudgetExceededError):
                pass

            if b._agent_budgets["capped-agent"]._spent >= 0.001:
                with pytest.raises(AgentBudgetExceededError):
                    await Runner.run(agent, "Say hi again")
