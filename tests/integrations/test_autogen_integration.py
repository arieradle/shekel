"""Integration tests for the AutoGen provider adapter.

All tests use mocked LLM responses — no live API key required.
The adapter is tested end-to-end: patching lifecycle, per-agent attribution,
global cap enforcement, and patch restoration.
"""

from __future__ import annotations

import pytest

from shekel import budget
from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

try:
    from autogen import ConversableAgent

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False

pytestmark = pytest.mark.skipif(not AUTOGEN_AVAILABLE, reason="pyautogen not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _charging_reply(cost_usd: float = 0.01):
    """Return a reply function that charges cost_usd to the active budget."""

    def _reply(recipient, messages, sender, config):
        from shekel._context import get_active_budget

        active = get_active_budget()
        if active is not None:
            active._record_spend(cost_usd, "gpt-4o-mini", {"input": 100, "output": 50})
        return True, "hello"

    return _reply


def _make_agent(name: str, cost_usd: float = 0.01) -> ConversableAgent:
    """Create a ConversableAgent with a charging reply function registered."""
    agent = ConversableAgent(name, llm_config=False)
    agent.register_reply(
        trigger=lambda sender: True,
        reply_func=_charging_reply(cost_usd),
        position=0,
    )
    return agent


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


class TestAutoGenAdapterLifecycle:
    """Verify that the adapter patches and restores generate_reply correctly."""

    def test_generate_reply_is_patched_inside_budget(self) -> None:
        """generate_reply is replaced with the adapter's wrapper while budget is active."""
        original = ConversableAgent.generate_reply
        with budget(max_usd=1.00):
            assert ConversableAgent.generate_reply is not original
        assert ConversableAgent.generate_reply is original

    def test_a_generate_reply_is_patched_inside_budget(self) -> None:
        """a_generate_reply is replaced with the adapter's wrapper while budget is active."""
        original = ConversableAgent.a_generate_reply
        with budget(max_usd=1.00):
            assert ConversableAgent.a_generate_reply is not original
        assert ConversableAgent.a_generate_reply is original

    def test_patch_restored_on_budget_exit(self) -> None:
        """Both methods are restored to their originals after budget context exits."""
        orig_sync = ConversableAgent.generate_reply
        orig_async = ConversableAgent.a_generate_reply
        with budget(max_usd=1.00):
            pass
        assert ConversableAgent.generate_reply is orig_sync
        assert ConversableAgent.a_generate_reply is orig_async

    def test_nested_budgets_do_not_double_patch(self) -> None:
        """Inner budget reuses the outer patch; original restored only when outermost exits."""
        original = ConversableAgent.generate_reply

        with budget(max_usd=5.00, name="outer"):
            outer_patch = ConversableAgent.generate_reply
            assert outer_patch is not original

            with budget(max_usd=1.00, name="inner"):
                assert ConversableAgent.generate_reply is outer_patch  # same wrapper

            assert ConversableAgent.generate_reply is outer_patch  # still patched

        assert ConversableAgent.generate_reply is original  # now restored

    def test_patch_restored_even_on_exception(self) -> None:
        """Patch is removed even when the budget body raises an exception."""
        original = ConversableAgent.generate_reply

        with pytest.raises(RuntimeError):
            with budget(max_usd=1.00):
                raise RuntimeError("test error")

        assert ConversableAgent.generate_reply is original


# ---------------------------------------------------------------------------
# Global budget enforcement
# ---------------------------------------------------------------------------


class TestAutoGenGlobalBudget:
    """Global budget cap stops further agent turns once limit is reached."""

    def test_spend_is_tracked_after_generate_reply(self) -> None:
        """Budget.spent reflects cost charged inside generate_reply."""
        agent = _make_agent("assistant", cost_usd=0.05)

        with budget(max_usd=1.00) as b:
            agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b.spent == pytest.approx(0.05)

    def test_global_cap_gates_second_call(self) -> None:
        """AgentBudgetExceededError raised when budget is already exhausted on entry."""
        agent = _make_agent("assistant", cost_usd=0.05)

        with pytest.raises((AgentBudgetExceededError, BudgetExceededError)):
            with budget(max_usd=0.03) as b:
                # First call: spends $0.05, bringing total to $0.05 > $0.03
                agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)
                # Second call: gate sees spent ($0.05) >= effective_limit ($0.03) → raises
                agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        _ = b  # silence unused-var linters

    def test_no_active_budget_passthrough(self) -> None:
        """Without a budget context, generate_reply works normally (no patch active)."""
        agent = _make_agent("assistant", cost_usd=0.01)
        # No budget() context — should not raise
        result = agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)
        assert result == "hello"

    def test_multiple_agents_accumulate_in_shared_budget(self) -> None:
        """Spend from multiple agents rolls up to a single global budget."""
        researcher = _make_agent("researcher", cost_usd=0.03)
        writer = _make_agent("writer", cost_usd=0.04)

        with budget(max_usd=1.00) as b:
            researcher.generate_reply(
                messages=[{"role": "user", "content": "research"}], sender=None
            )
            writer.generate_reply(messages=[{"role": "user", "content": "write"}], sender=None)

        assert b.spent == pytest.approx(0.07)
        assert b.calls_used == 2


# ---------------------------------------------------------------------------
# Per-agent cap enforcement
# ---------------------------------------------------------------------------


class TestAutoGenPerAgentCap:
    """b.agent() per-agent caps stop the capped agent while others continue."""

    def test_per_agent_cap_raises_on_second_call(self) -> None:
        """AgentBudgetExceededError when agent's own cap is hit."""
        agent = _make_agent("assistant", cost_usd=0.10)

        with pytest.raises(AgentBudgetExceededError) as exc_info:
            with budget(max_usd=5.00) as b:
                b.agent("assistant", max_usd=0.05)
                # First call: charges $0.10; cap._spent becomes $0.10 > $0.05
                agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)
                # Second call: gate sees cap._spent ($0.10) >= cap.max_usd ($0.05) → raises
                agent.generate_reply(
                    messages=[{"role": "user", "content": "hi again"}], sender=None
                )

        assert exc_info.value.agent_name == "assistant"

    def test_spend_attributed_to_agent_cap(self) -> None:
        """Spend delta from generate_reply is recorded in the agent ComponentBudget."""
        agent = _make_agent("assistant", cost_usd=0.07)

        with budget(max_usd=5.00) as b:
            b.agent("assistant", max_usd=1.00)
            agent.generate_reply(messages=[{"role": "user", "content": "hello"}], sender=None)

        cap = b._agent_budgets["assistant"]
        assert cap._spent == pytest.approx(0.07)

    def test_cap_on_one_agent_does_not_stop_another(self) -> None:
        """Exhausting one agent's cap leaves other agents unaffected."""
        agent_a = _make_agent("agent_a", cost_usd=0.10)
        agent_b = _make_agent("agent_b", cost_usd=0.02)

        with budget(max_usd=5.00) as b:
            b.agent("agent_a", max_usd=0.05)
            b.agent("agent_b", max_usd=1.00)

            # Exhaust agent_a
            agent_a.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)
            # agent_a now capped; agent_b should still work
            agent_b.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

            with pytest.raises(AgentBudgetExceededError):
                agent_a.generate_reply(
                    messages=[{"role": "user", "content": "one more"}], sender=None
                )

        assert b._agent_budgets["agent_b"]._spent == pytest.approx(0.02)

    def test_agent_cap_shown_in_tree(self) -> None:
        """b.tree() output includes the agent component cap entry."""
        agent = _make_agent("assistant", cost_usd=0.05)

        with budget(max_usd=5.00, name="root") as b:
            b.agent("assistant", max_usd=1.00)
            agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        tree_output = b.tree()
        assert "assistant" in tree_output
        assert "[agent]" in tree_output


# ---------------------------------------------------------------------------
# GroupChat-style multi-agent spend
# ---------------------------------------------------------------------------


class TestAutoGenGroupChat:
    """Multiple agents in sequence — each attributed independently."""

    def test_three_agents_each_attributed(self) -> None:
        """Three sequential agents each get their own cap spend tracked."""
        planner = _make_agent("planner", cost_usd=0.02)
        coder = _make_agent("coder", cost_usd=0.05)
        reviewer = _make_agent("reviewer", cost_usd=0.03)

        with budget(max_usd=5.00) as b:
            b.agent("planner", max_usd=0.50)
            b.agent("coder", max_usd=0.50)
            b.agent("reviewer", max_usd=0.50)

            planner.generate_reply(messages=[{"role": "user", "content": "plan"}], sender=None)
            coder.generate_reply(messages=[{"role": "user", "content": "code"}], sender=None)
            reviewer.generate_reply(messages=[{"role": "user", "content": "review"}], sender=None)

        assert b._agent_budgets["planner"]._spent == pytest.approx(0.02)
        assert b._agent_budgets["coder"]._spent == pytest.approx(0.05)
        assert b._agent_budgets["reviewer"]._spent == pytest.approx(0.03)
        assert b.spent == pytest.approx(0.10)

    def test_unregistered_agent_spend_rolls_up_to_global_only(self) -> None:
        """Agent with no cap still contributes to global budget; no attribution error."""
        uncapped = _make_agent("uncapped", cost_usd=0.04)

        with budget(max_usd=5.00) as b:
            # No b.agent("uncapped", ...) — unregistered
            uncapped.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b.spent == pytest.approx(0.04)
        assert "uncapped" not in b._agent_budgets


# ---------------------------------------------------------------------------
# Async generate_reply enforcement
# ---------------------------------------------------------------------------


class TestAutoGenAsync:
    """a_generate_reply is also patched, gated, and attributes spend."""

    @pytest.mark.asyncio
    async def test_a_generate_reply_is_patched(self) -> None:
        """a_generate_reply is wrapped by the adapter while budget is active."""
        original = ConversableAgent.a_generate_reply

        async with budget(max_usd=1.00):
            assert ConversableAgent.a_generate_reply is not original

        assert ConversableAgent.a_generate_reply is original

    @pytest.mark.asyncio
    async def test_a_generate_reply_tracks_spend(self) -> None:
        """Spend charged inside a_generate_reply is captured by the budget."""
        agent = _make_agent("assistant", cost_usd=0.06)

        async with budget(max_usd=1.00) as b:
            b.agent("assistant", max_usd=1.00)
            await agent.a_generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b.spent == pytest.approx(0.06)
        assert b._agent_budgets["assistant"]._spent == pytest.approx(0.06)

    @pytest.mark.asyncio
    async def test_a_generate_reply_gate_raises_when_over_limit(self) -> None:
        """Gate fires on a_generate_reply when global budget is already exhausted."""
        agent = ConversableAgent("assistant", llm_config=False)

        with pytest.raises((AgentBudgetExceededError, BudgetExceededError)):
            async with budget(max_usd=0.001) as b:
                # Manually push spend over the limit to trigger the gate
                b._spent = 0.002
                await agent.a_generate_reply(
                    messages=[{"role": "user", "content": "hi"}], sender=None
                )

    @pytest.mark.asyncio
    async def test_async_per_agent_cap_raises(self) -> None:
        """AgentBudgetExceededError raised via a_generate_reply when agent cap exhausted."""
        agent = ConversableAgent("assistant", llm_config=False)

        with pytest.raises(AgentBudgetExceededError):
            async with budget(max_usd=5.00) as b:
                b.agent("assistant", max_usd=0.01)
                # Manually exhaust the agent cap
                b._agent_budgets["assistant"]._spent = 0.02
                await agent.a_generate_reply(
                    messages=[{"role": "user", "content": "hi"}], sender=None
                )


# ---------------------------------------------------------------------------
# Edge-case coverage
# ---------------------------------------------------------------------------


class TestAutoGenEdgeCases:
    """Cover defensive branches: zero-delta spend, no-context passthroughs."""

    def test_zero_spend_does_not_attribute_to_cap(self) -> None:
        """When generate_reply produces no spend, agent cap._spent stays at zero."""
        agent = _make_agent("assistant", cost_usd=0.0)

        with budget(max_usd=1.00) as b:
            b.agent("assistant", max_usd=1.00)
            agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b._agent_budgets["assistant"]._spent == pytest.approx(0.0)

    def test_patched_sync_passthrough_without_active_budget(self) -> None:
        """Patched generate_reply falls through to original when no budget is in ContextVar."""
        import threading

        agent = _make_agent("assistant", cost_usd=0.05)
        results: list = []

        def call_in_thread() -> None:
            # Thread does not inherit ContextVar — active budget is None here
            result = agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)
            results.append(result)

        with budget(max_usd=1.00):
            # Patch is installed in this context, but the thread has no active budget
            t = threading.Thread(target=call_in_thread)
            t.start()
            t.join()

        assert results == ["hello"]

    def test_remove_patches_is_safe_when_not_patched(self) -> None:
        """remove_patches is a no-op when refcount is already zero (defensive guard)."""
        from shekel.providers.autogen import AutoGenAdapter

        adapter = AutoGenAdapter()
        # Calling remove_patches with no matching install_patches must not raise
        adapter.remove_patches(None)  # _patch_refcount is 0 → early return
