"""AutoGen provider adapter for Shekel — per-agent budget enforcement.

Patches ConversableAgent.generate_reply (sync) and a_generate_reply (async)
to gate and attribute LLM spend per agent turn. Spend tracking itself is
handled by the underlying OpenAI/Anthropic patches; this adapter adds
per-agent attribution and per-agent caps on top.

How it works:
1. On budget.__enter__(), ShekelRuntime.probe() calls AutoGenAdapter().install_patches(budget).
2. Each generate_reply / a_generate_reply call:
   a. Pre-gate: check per-agent cap (b.agent("name", max_usd=X)) and global budget.
   b. Call original — OpenAI/Anthropic patches record spend as usual.
   c. Post-attribute: spend delta → agent ComponentBudget._spent.
3. On budget.__exit__(), remove_patches() restores the originals.

A reference counter ensures nested budgets don't double-patch or prematurely
restore the original methods.
"""

from __future__ import annotations

from typing import Any

_original_generate_reply: Any = None
_original_a_generate_reply: Any = None
_patch_refcount: int = 0


def _find_agent_cap(agent_name: str, active: Any) -> Any:
    """Walk the budget parent chain to find a registered agent cap."""
    b: Any = active
    while b is not None:
        cb = b._agent_budgets.get(agent_name)
        if cb is not None:
            return cb
        b = b.parent
    return None


def _gate(agent_name: str, active: Any) -> None:
    """Pre-execution check: raise if per-agent cap or global limit already exceeded."""
    from shekel.exceptions import AgentBudgetExceededError

    cb = _find_agent_cap(agent_name, active)
    if cb is not None and cb._spent >= cb.max_usd:
        raise AgentBudgetExceededError(agent_name=agent_name, spent=cb._spent, limit=cb.max_usd)

    if active._effective_limit is not None and active._spent >= active._effective_limit:
        raise AgentBudgetExceededError(
            agent_name=agent_name, spent=active._spent, limit=active._effective_limit
        )


def _attribute_spend(agent_name: str, active: Any, spend_before: float) -> None:
    """Post-execution: add spend delta to the agent's ComponentBudget."""
    delta = active._spent - spend_before
    if delta <= 0:
        return
    cb = _find_agent_cap(agent_name, active)
    if cb is not None:
        cb._spent += delta


class AutoGenAdapter:
    """Patches ConversableAgent.generate_reply and a_generate_reply for per-agent
    budget enforcement.

    Activated transparently by ShekelRuntime.probe() on budget().__enter__().
    A reference counter ensures nested budgets don't double-patch or prematurely
    restore the original methods.
    """

    def install_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Patch ConversableAgent.generate_reply and a_generate_reply.

        Raises ImportError when autogen is not installed so that
        ShekelRuntime.probe() silently skips it.
        """
        global _original_generate_reply, _original_a_generate_reply, _patch_refcount

        import autogen.agentchat.conversable_agent  # noqa: F401  # raises ImportError if absent
        from autogen.agentchat.conversable_agent import ConversableAgent

        _patch_refcount += 1
        if _patch_refcount > 1:
            return  # already patched — just increment refcount

        orig_sync = ConversableAgent.generate_reply
        orig_async = ConversableAgent.a_generate_reply
        _original_generate_reply = orig_sync
        _original_a_generate_reply = orig_async

        def _patched_generate_reply(
            self: Any,
            messages: Any = None,
            sender: Any = None,
            **kwargs: Any,
        ) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is None:
                return orig_sync(self, messages=messages, sender=sender, **kwargs)

            agent_name = getattr(self, "name", str(self))
            _gate(agent_name, active)
            spend_before = active._spent
            result = orig_sync(self, messages=messages, sender=sender, **kwargs)
            _attribute_spend(agent_name, active, spend_before)
            return result

        async def _patched_a_generate_reply(
            self: Any,
            messages: Any = None,
            sender: Any = None,
            **kwargs: Any,
        ) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is None:  # pragma: no cover — asyncio tasks inherit context
                return await orig_async(self, messages=messages, sender=sender, **kwargs)

            agent_name = getattr(self, "name", str(self))
            _gate(agent_name, active)
            spend_before = active._spent
            result = await orig_async(self, messages=messages, sender=sender, **kwargs)
            _attribute_spend(agent_name, active, spend_before)
            return result

        ConversableAgent.generate_reply = _patched_generate_reply
        ConversableAgent.a_generate_reply = _patched_a_generate_reply

    def remove_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Restore ConversableAgent.generate_reply and a_generate_reply.

        Only restores when the last active budget closes (reference count
        reaches zero).
        """
        global _original_generate_reply, _original_a_generate_reply, _patch_refcount

        if _patch_refcount <= 0:
            return
        _patch_refcount -= 1
        if _patch_refcount > 0:
            return  # other budgets still active

        if _original_generate_reply is None:
            return  # pragma: no cover — defensive null check
        try:
            from autogen.agentchat.conversable_agent import ConversableAgent

            ConversableAgent.generate_reply = _original_generate_reply
            ConversableAgent.a_generate_reply = _original_a_generate_reply
        except ImportError:  # pragma: no cover — defensive cleanup
            pass
        _original_generate_reply = None
        _original_a_generate_reply = None
