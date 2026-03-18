"""CrewAI provider adapter for Shekel tool budget tracking and agent/task circuit breaking."""

from __future__ import annotations

import warnings
from typing import Any

_original_run: Any = None
_original_arun: Any = None


def _get_price(budget: Any, tool_name: str) -> float:
    if budget.tool_prices is not None and tool_name in budget.tool_prices:
        return float(budget.tool_prices[tool_name])
    return 0.0


class CrewAIAdapter:
    """Auto-patches crewai.tools.BaseTool._run / _arun."""

    def install_patches(self) -> None:
        global _original_run, _original_arun
        try:
            import crewai.tools as _crewai_tools

            if _original_run is not None:
                return  # Already patched

            _original_run = _crewai_tools.BaseTool._run
            _original_arun = _crewai_tools.BaseTool._arun

            from shekel._context import get_active_budget

            orig_run = _original_run
            orig_arun = _original_arun

            def _patched_run(self: Any, *args: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "crewai")
                    result = orig_run(self, *args, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "crewai")
                    return result
                return orig_run(self, *args, **kwargs)

            async def _patched_arun(self: Any, *args: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "crewai")
                    result = await orig_arun(self, *args, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "crewai")
                    return result
                return await orig_arun(self, *args, **kwargs)

            _crewai_tools.BaseTool._run = _patched_run
            _crewai_tools.BaseTool._arun = _patched_arun
        except (ImportError, AttributeError, TypeError):
            pass  # crewai not installed or API changed — skip silently

    def remove_patches(self) -> None:
        global _original_run, _original_arun
        try:
            if _original_run is None:
                return
            import crewai.tools as _crewai_tools

            _crewai_tools.BaseTool._run = _original_run
            _crewai_tools.BaseTool._arun = _original_arun
            _original_run = None
            _original_arun = None
        except (ImportError, AttributeError, TypeError):  # pragma: no cover
            _original_run = None  # pragma: no cover
            _original_arun = None  # pragma: no cover


# ---------------------------------------------------------------------------
# CrewAI execution-level adapter — agent/task circuit breaking (v1.0.0)
# ---------------------------------------------------------------------------

_execution_patch_refcount: int = 0
_original_execute_task: Any = None


def _find_agent_cap(agent_name: str, active: Any) -> Any:
    """Walk the budget parent chain to find a registered agent cap."""
    b: Any = active
    while b is not None:
        cb = b._agent_budgets.get(agent_name)
        if cb is not None:
            return cb
        b = b.parent
    return None


def _find_task_cap(task_name: str, active: Any) -> Any:
    """Walk the budget parent chain to find a registered task cap."""
    b: Any = active
    while b is not None:
        cb = b._task_budgets.get(task_name)
        if cb is not None:
            return cb
        b = b.parent
    return None


def _has_any_task_caps(active: Any) -> bool:
    """Return True if any budget in the parent chain has registered task caps."""
    b: Any = active
    while b is not None:
        if b._task_budgets:
            return True
        b = b.parent
    return False


def _get_task_name(task: Any) -> str:
    """Resolve task name: task.name (non-empty) → task.description (non-empty) → '<unnamed>'."""
    return getattr(task, "name", None) or getattr(task, "description", None) or "<unnamed>"


def _gate_execution(agent_name: str, task_name: str, task: Any, active: Any) -> None:
    """Pre-execution gate: task cap → agent cap → global budget."""
    from shekel.exceptions import AgentBudgetExceededError, TaskBudgetExceededError

    # Warn when task.name is absent/empty and task caps are registered (silent-miss risk)
    task_has_name = bool(getattr(task, "name", None))
    if not task_has_name and _has_any_task_caps(active):
        desc = getattr(task, "description", "") or ""
        if desc:
            msg = (
                f"shekel: task has no name (description: '{desc[:50]}...') "
                "— set task.name to apply caps."
            )
        else:
            msg = "shekel: task has no name and no description — set task.name to apply caps."
        warnings.warn(msg, UserWarning, stacklevel=4)

    # Task cap — most specific, checked first
    task_cb = _find_task_cap(task_name, active)
    if task_cb is not None and task_cb._spent >= task_cb.max_usd:
        raise TaskBudgetExceededError(
            task_name=task_name, spent=task_cb._spent, limit=task_cb.max_usd
        )

    # Agent cap
    agent_cb = _find_agent_cap(agent_name, active)
    if agent_cb is not None and agent_cb._spent >= agent_cb.max_usd:
        raise AgentBudgetExceededError(
            agent_name=agent_name, spent=agent_cb._spent, limit=agent_cb.max_usd
        )

    # Global budget check (mirrors langgraph._gate pattern)
    if active._effective_limit is not None and active._spent >= active._effective_limit:
        raise AgentBudgetExceededError(
            agent_name=agent_name, spent=active._spent, limit=active._effective_limit
        )


def _attribute_execution_spend(
    agent_name: str, task_name: str, active: Any, spend_before: float
) -> None:
    """Attribute spend delta to both agent and task ComponentBudgets."""
    delta = active._spent - spend_before
    if delta <= 0:
        return
    agent_cb = _find_agent_cap(agent_name, active)
    if agent_cb is not None:
        agent_cb._spent += delta
    task_cb = _find_task_cap(task_name, active)
    if task_cb is not None:
        task_cb._spent += delta


class CrewAIExecutionAdapter:
    """Patches ``Agent.execute_task`` for agent/task-level budget circuit breaking.

    Activated transparently by ``ShekelRuntime.probe()`` on ``budget().__enter__()``.
    A reference counter ensures nested budgets don't double-patch or prematurely
    restore the original method.
    """

    def install_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Patch ``Agent.execute_task``.  Raises ``ImportError`` when crewai
        is not installed so that ``ShekelRuntime.probe()`` silently skips it.
        """
        global _execution_patch_refcount, _original_execute_task

        import crewai.agent  # raises ImportError if crewai not installed  # noqa: F401
        from crewai.agent import Agent

        _execution_patch_refcount += 1
        if _execution_patch_refcount > 1:
            return  # already patched — just increment the refcount

        orig = Agent.execute_task
        _original_execute_task = orig

        def _patched_execute_task(
            self: Any, task: Any, context: Any = None, tools: Any = None
        ) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            if active is None:
                return orig(self, task, context, tools)

            agent_name = getattr(self, "role", str(self))
            task_name = _get_task_name(task)

            _gate_execution(agent_name, task_name, task, active)
            spend_before = active._spent
            result = orig(self, task, context, tools)
            _attribute_execution_spend(agent_name, task_name, active, spend_before)
            return result

        Agent.execute_task = _patched_execute_task

    def remove_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Restore ``Agent.execute_task``.  Only restores when the last
        active budget closes (reference count reaches zero).
        """
        global _execution_patch_refcount, _original_execute_task

        if _execution_patch_refcount <= 0:
            return
        _execution_patch_refcount -= 1
        if _execution_patch_refcount > 0:
            return  # other budgets still active

        if _original_execute_task is None:
            return  # pragma: no cover — defensive null check
        try:
            from crewai.agent import Agent

            Agent.execute_task = _original_execute_task
        except ImportError:  # pragma: no cover — defensive cleanup
            pass
        _original_execute_task = None  # reset after restore (langchain.py pattern)
