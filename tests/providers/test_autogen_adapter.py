"""Unit tests for shekel/providers/autogen.py.

Covers AutoGenAdapter lifecycle and the module-level gate/attribute helpers.
These run in the unit-test job (not ignored like tests/integrations/) so that
codecov/patch tracks coverage of the new provider file.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

try:
    from autogen import ConversableAgent

    AUTOGEN_AVAILABLE = True
except ImportError:
    AUTOGEN_AVAILABLE = False

pytestmark = pytest.mark.skipif(not AUTOGEN_AVAILABLE, reason="pyautogen not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_budget(spent: float = 0.0, limit: float | None = 1.0) -> MagicMock:
    b = MagicMock()
    b._spent = spent
    b._effective_limit = limit
    b._agent_budgets = {}
    b.parent = None
    return b


def _make_cap(spent: float = 0.0, max_usd: float = 0.50) -> MagicMock:
    cap = MagicMock()
    cap._spent = spent
    cap.max_usd = max_usd
    return cap


# ---------------------------------------------------------------------------
# AutoGenAdapter lifecycle
# ---------------------------------------------------------------------------


class TestAutoGenAdapterLifecycle:
    def setup_method(self) -> None:
        from shekel.providers.autogen import AutoGenAdapter

        self._original_sync = ConversableAgent.generate_reply
        self._original_async = ConversableAgent.a_generate_reply
        self.adapter = AutoGenAdapter()

    def teardown_method(self) -> None:
        ConversableAgent.generate_reply = self._original_sync
        ConversableAgent.a_generate_reply = self._original_async
        import shekel.providers.autogen as _m

        _m._patch_refcount = 0
        _m._original_generate_reply = None
        _m._original_a_generate_reply = None

    def test_install_patches_replaces_generate_reply(self) -> None:
        self.adapter.install_patches(None)
        assert ConversableAgent.generate_reply is not self._original_sync

    def test_install_patches_replaces_a_generate_reply(self) -> None:
        self.adapter.install_patches(None)
        assert ConversableAgent.a_generate_reply is not self._original_async

    def test_remove_patches_restores_generate_reply(self) -> None:
        self.adapter.install_patches(None)
        self.adapter.remove_patches(None)
        assert ConversableAgent.generate_reply is self._original_sync

    def test_remove_patches_restores_a_generate_reply(self) -> None:
        self.adapter.install_patches(None)
        self.adapter.remove_patches(None)
        assert ConversableAgent.a_generate_reply is self._original_async

    def test_refcount_prevents_double_patch(self) -> None:
        self.adapter.install_patches(None)
        patched = ConversableAgent.generate_reply
        self.adapter.install_patches(None)  # second call — early return
        assert ConversableAgent.generate_reply is patched  # same wrapper

    def test_refcount_prevents_premature_restore(self) -> None:
        self.adapter.install_patches(None)
        self.adapter.install_patches(None)
        self.adapter.remove_patches(None)  # refcount → 1, not restored yet
        assert ConversableAgent.generate_reply is not self._original_sync

    def test_remove_patches_is_noop_when_not_installed(self) -> None:
        import shekel.providers.autogen as _m

        assert _m._patch_refcount == 0
        self.adapter.remove_patches(None)  # should not raise


# ---------------------------------------------------------------------------
# _find_agent_cap
# ---------------------------------------------------------------------------


class TestFindAgentCap:
    def test_returns_none_when_no_budgets(self) -> None:
        from shekel.providers.autogen import _find_agent_cap

        b = _make_mock_budget()
        assert _find_agent_cap("assistant", b) is None

    def test_returns_cap_when_registered(self) -> None:
        from shekel.providers.autogen import _find_agent_cap

        b = _make_mock_budget()
        cap = _make_cap()
        b._agent_budgets["assistant"] = cap
        assert _find_agent_cap("assistant", b) is cap

    def test_walks_parent_chain(self) -> None:
        from shekel.providers.autogen import _find_agent_cap

        parent = _make_mock_budget()
        cap = _make_cap()
        parent._agent_budgets["assistant"] = cap
        child = _make_mock_budget()
        child.parent = parent
        assert _find_agent_cap("assistant", child) is cap

    def test_returns_none_for_unknown_agent(self) -> None:
        from shekel.providers.autogen import _find_agent_cap

        b = _make_mock_budget()
        b._agent_budgets["other"] = _make_cap()
        assert _find_agent_cap("assistant", b) is None


# ---------------------------------------------------------------------------
# _gate
# ---------------------------------------------------------------------------


class TestGate:
    def test_no_raise_when_under_limits(self) -> None:
        from shekel.providers.autogen import _gate

        b = _make_mock_budget(spent=0.10, limit=1.00)
        _gate("assistant", b)  # should not raise

    def test_raises_on_agent_cap_exceeded(self) -> None:
        from shekel.exceptions import AgentBudgetExceededError
        from shekel.providers.autogen import _gate

        b = _make_mock_budget(spent=0.10, limit=5.00)
        cap = _make_cap(spent=0.60, max_usd=0.50)
        b._agent_budgets["assistant"] = cap

        with pytest.raises(AgentBudgetExceededError) as exc_info:
            _gate("assistant", b)
        assert exc_info.value.agent_name == "assistant"

    def test_raises_on_global_limit_exceeded(self) -> None:
        from shekel.exceptions import AgentBudgetExceededError
        from shekel.providers.autogen import _gate

        b = _make_mock_budget(spent=1.10, limit=1.00)
        with pytest.raises(AgentBudgetExceededError):
            _gate("assistant", b)

    def test_no_raise_when_no_effective_limit(self) -> None:
        from shekel.providers.autogen import _gate

        b = _make_mock_budget(spent=9999.0, limit=None)
        _gate("assistant", b)  # no limit set → no raise

    def test_agent_cap_exactly_at_limit_raises(self) -> None:
        from shekel.exceptions import AgentBudgetExceededError
        from shekel.providers.autogen import _gate

        b = _make_mock_budget(spent=0.0, limit=5.00)
        cap = _make_cap(spent=0.50, max_usd=0.50)
        b._agent_budgets["assistant"] = cap

        with pytest.raises(AgentBudgetExceededError):
            _gate("assistant", b)


# ---------------------------------------------------------------------------
# _attribute_spend
# ---------------------------------------------------------------------------


class TestAttributeSpend:
    def test_attributes_delta_to_cap(self) -> None:
        from shekel.providers.autogen import _attribute_spend

        b = _make_mock_budget(spent=0.15)
        cap = _make_cap(spent=0.0)
        b._agent_budgets["assistant"] = cap

        _attribute_spend("assistant", b, spend_before=0.05)
        assert cap._spent == pytest.approx(0.10)

    def test_no_attribution_when_delta_is_zero(self) -> None:
        from shekel.providers.autogen import _attribute_spend

        b = _make_mock_budget(spent=0.10)
        cap = _make_cap(spent=0.0)
        b._agent_budgets["assistant"] = cap

        _attribute_spend("assistant", b, spend_before=0.10)
        assert cap._spent == 0.0  # unchanged

    def test_no_attribution_when_no_cap_registered(self) -> None:
        from shekel.providers.autogen import _attribute_spend

        b = _make_mock_budget(spent=0.20)
        # No cap registered — should not raise
        _attribute_spend("assistant", b, spend_before=0.10)

    def test_negative_delta_is_no_op(self) -> None:
        from shekel.providers.autogen import _attribute_spend

        b = _make_mock_budget(spent=0.05)
        cap = _make_cap(spent=0.30)
        b._agent_budgets["assistant"] = cap

        _attribute_spend("assistant", b, spend_before=0.10)
        assert cap._spent == pytest.approx(0.30)  # unchanged


# ---------------------------------------------------------------------------
# Patched generate_reply and a_generate_reply end-to-end (unit-level)
# ---------------------------------------------------------------------------


def _charging_reply(cost_usd: float = 0.01):
    def _reply(recipient, messages, sender, config):
        from shekel._context import get_active_budget

        active = get_active_budget()
        if active is not None:
            active._record_spend(cost_usd, "gpt-4o-mini", {"input": 100, "output": 50})
        return True, "hello"

    return _reply


class TestPatchedGenerateReply:
    """Exercise the patched generate_reply body through a budget context."""

    def test_spend_tracked_via_budget_context(self) -> None:
        from shekel import budget

        agent = ConversableAgent("assistant", llm_config=False)
        agent.register_reply(trigger=lambda s: True, reply_func=_charging_reply(0.03), position=0)

        with budget(max_usd=1.00) as b:
            agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b.spent == pytest.approx(0.03)

    def test_agent_cap_attributed_via_budget_context(self) -> None:
        from shekel import budget

        agent = ConversableAgent("assistant", llm_config=False)
        agent.register_reply(trigger=lambda s: True, reply_func=_charging_reply(0.05), position=0)

        with budget(max_usd=1.00) as b:
            b.agent("assistant", max_usd=1.00)
            agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b._agent_budgets["assistant"]._spent == pytest.approx(0.05)

    def test_gate_fires_on_exceeded_limit(self) -> None:
        from shekel import budget
        from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

        agent = ConversableAgent("assistant", llm_config=False)
        agent.register_reply(trigger=lambda s: True, reply_func=_charging_reply(0.10), position=0)

        with pytest.raises((AgentBudgetExceededError, BudgetExceededError)):
            with budget(max_usd=0.05):
                agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)
                agent.generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

    @pytest.mark.asyncio
    async def test_async_spend_tracked_via_budget_context(self) -> None:
        from shekel import budget

        agent = ConversableAgent("assistant", llm_config=False)
        agent.register_reply(trigger=lambda s: True, reply_func=_charging_reply(0.04), position=0)

        async with budget(max_usd=1.00) as b:
            b.agent("assistant", max_usd=1.00)
            await agent.a_generate_reply(messages=[{"role": "user", "content": "hi"}], sender=None)

        assert b.spent == pytest.approx(0.04)
        assert b._agent_budgets["assistant"]._spent == pytest.approx(0.04)

    @pytest.mark.asyncio
    async def test_async_gate_fires_on_exceeded_agent_cap(self) -> None:
        from shekel import budget
        from shekel.exceptions import AgentBudgetExceededError

        agent = ConversableAgent("assistant", llm_config=False)

        with pytest.raises(AgentBudgetExceededError):
            async with budget(max_usd=5.00) as b:
                b.agent("assistant", max_usd=0.01)
                b._agent_budgets["assistant"]._spent = 0.02
                await agent.a_generate_reply(
                    messages=[{"role": "user", "content": "hi"}], sender=None
                )
