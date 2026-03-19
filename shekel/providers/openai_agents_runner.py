"""OpenAI Agents SDK Runner adapter for Shekel agent-level budget enforcement.

Patches Runner.run, Runner.run_sync, and Runner.run_streamed to enforce
per-agent and global budget gates before each run, and attribute spend
to ComponentBudget._spent after completion.
"""

from __future__ import annotations

from typing import Any

# Module-level storage avoids the classmethod descriptor protocol issue
# that occurs when classmethods are stored as class attributes.
_patch_refcount: int = 0
_original_run: Any = None
_original_run_sync: Any = None
_original_run_streamed: Any = None


def _get_raw_descriptor(cls: type, name: str) -> Any:
    """Return the raw descriptor for *name* by walking the MRO.

    Uses vars(klass) rather than cls.__dict__ so that inherited classmethods
    (defined on a parent class) are found correctly.
    """
    for klass in cls.__mro__:
        if name in vars(klass):
            return vars(klass)[name]
    raise AttributeError(f"{name!r} not found in {cls.__name__} MRO")  # pragma: no cover


def _get_agent_name(agent: Any) -> str | None:
    """Extract agent name from an Agent object. Returns None if not available."""
    return getattr(agent, "name", None) or None


def _find_agent_cap(agent_name: str, budget: Any) -> Any:
    """Walk the budget parent chain to find a ComponentBudget for agent_name.

    Returns None if not found.
    """
    b = budget
    while b is not None:
        cap = b._agent_budgets.get(agent_name)
        if cap is not None:
            return cap
        b = getattr(b, "parent", None)
    return None


def _pre_run_gate(agent: Any, active_budget: Any) -> None:
    """Check agent cap and parent budget before running.

    Raises AgentBudgetExceededError if any limit is exceeded.
    """
    from shekel.exceptions import AgentBudgetExceededError

    agent_name = _get_agent_name(agent)
    if agent_name:
        cap = _find_agent_cap(agent_name, active_budget)
        if cap is not None and cap._spent >= cap.max_usd:
            raise AgentBudgetExceededError(
                agent_name=agent_name,
                spent=cap._spent,
                limit=cap.max_usd,
            )

    # Check effective budget limit (accounts for nested auto-capping)
    if active_budget._effective_limit is not None:
        if active_budget._spent >= active_budget._effective_limit:
            raise AgentBudgetExceededError(
                agent_name=agent_name or "unknown",
                spent=active_budget._spent,
                limit=active_budget._effective_limit,
            )


def _attribute_spend(agent: Any, active_budget: Any, spend_before: float) -> None:
    """Attribute spend delta to the agent's ComponentBudget._spent."""
    delta = active_budget.spent - spend_before
    agent_name = _get_agent_name(agent)
    if agent_name:
        cap = _find_agent_cap(agent_name, active_budget)
        if cap is not None:
            cap._spent += delta


def _make_run_wrapper(original_run: Any) -> Any:
    """Return an async classmethod wrapper for Runner.run."""

    async def wrapped_run(cls: Any, /, agent: Any, input: Any, **kwargs: Any) -> Any:
        from shekel._context import get_active_budget

        active_budget = get_active_budget()
        if active_budget is None:
            return await original_run.__func__(cls, agent, input, **kwargs)
        _pre_run_gate(agent, active_budget)
        spend_before = active_budget.spent
        try:
            result = await original_run.__func__(cls, agent, input, **kwargs)
        finally:
            _attribute_spend(agent, active_budget, spend_before)
        return result

    return classmethod(wrapped_run)


def _make_run_sync_wrapper(original_run_sync: Any) -> Any:
    """Return a sync classmethod wrapper for Runner.run_sync."""

    def wrapped_run_sync(cls: Any, /, agent: Any, input: Any, **kwargs: Any) -> Any:
        from shekel._context import get_active_budget

        active_budget = get_active_budget()
        if active_budget is None:
            return original_run_sync.__func__(cls, agent, input, **kwargs)
        _pre_run_gate(agent, active_budget)
        spend_before = active_budget.spent
        try:
            result = original_run_sync.__func__(cls, agent, input, **kwargs)
        finally:
            _attribute_spend(agent, active_budget, spend_before)
        return result

    return classmethod(wrapped_run_sync)


def _make_run_streamed_wrapper(original_run_streamed: Any) -> Any:
    """Return an async classmethod wrapper for Runner.run_streamed.

    Spend is attributed after full iteration completes. If the caller
    never iterates the returned stream, spend is not attributed (known
    limitation — document at call site if this matters).
    """

    async def wrapped_run_streamed(cls: Any, /, agent: Any, input: Any, **kwargs: Any) -> Any:
        from shekel._context import get_active_budget

        active_budget = get_active_budget()
        if active_budget is None:
            return await original_run_streamed.__func__(cls, agent, input, **kwargs)
        _pre_run_gate(agent, active_budget)
        spend_before = active_budget.spent

        inner_stream = await original_run_streamed.__func__(cls, agent, input, **kwargs)

        async def _attributed_stream() -> Any:
            try:
                async for chunk in inner_stream:
                    yield chunk
            finally:
                _attribute_spend(agent, active_budget, spend_before)

        return _attributed_stream()

    return classmethod(wrapped_run_streamed)


class OpenAIAgentsRunnerAdapter:
    """Patches OpenAI Agents SDK Runner methods to enforce budget gates.

    A reference counter ensures nested budgets do not double-patch or
    prematurely restore the original methods.

    Activated transparently by ShekelRuntime.probe() on budget.__enter__().
    """

    # These are class-level aliases to module-level state; kept for API
    # compatibility with tests that inspect the class. The actual storage
    # uses module-level variables to avoid classmethod descriptor protocol issues.

    @property
    def _patch_refcount(self) -> int:  # pragma: no cover
        return _patch_refcount

    def install_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Called on budget.__enter__. Patches Runner if not already patched.

        Raises ImportError when agents SDK is not installed, allowing
        ShekelRuntime.probe() to silently skip this adapter.
        """
        global _patch_refcount, _original_run, _original_run_sync, _original_run_streamed

        import agents  # noqa: F401 — raises ImportError if not installed
        from agents import Runner

        _patch_refcount += 1
        if _patch_refcount == 1:
            # Save the raw classmethod descriptors via MRO walk so that
            # restore writes back exactly the same descriptor object and
            # identity checks pass even when methods are inherited.
            _original_run = _get_raw_descriptor(Runner, "run")
            _original_run_sync = _get_raw_descriptor(Runner, "run_sync")
            _original_run_streamed = _get_raw_descriptor(Runner, "run_streamed")
            Runner.run = _make_run_wrapper(_original_run)
            Runner.run_sync = _make_run_sync_wrapper(_original_run_sync)
            Runner.run_streamed = _make_run_streamed_wrapper(_original_run_streamed)

    def remove_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Called on budget.__exit__. Restores Runner when refcount reaches 0."""
        global _patch_refcount, _original_run, _original_run_sync, _original_run_streamed

        try:
            from agents import Runner
        except ImportError:
            return

        if _patch_refcount <= 0:  # pragma: no cover — defensive guard against double-remove
            return

        _patch_refcount -= 1
        if _patch_refcount == 0:
            Runner.run = _original_run
            Runner.run_sync = _original_run_sync
            Runner.run_streamed = _original_run_streamed
            _original_run = None
            _original_run_sync = None
            _original_run_streamed = None
