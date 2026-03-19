"""LangChain provider adapter for Shekel — tool budget tracking and chain-level circuit breaking."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shekel._budget import Budget

_original_invoke: Any = None
_original_ainvoke: Any = None

# Chain-level patch state (LangChainRunnerAdapter)
_chain_patch_refcount: int = 0
_original_call_with_config: Any = None
_original_acall_with_config: Any = None
_original_sequence_invoke: Any = None
_original_sequence_ainvoke: Any = None


def _get_price(budget: Any, tool_name: str) -> float:
    if budget.tool_prices is not None and tool_name in budget.tool_prices:
        return float(budget.tool_prices[tool_name])
    return 0.0


class LangChainAdapter:
    """Auto-patches langchain_core.tools.BaseTool.invoke / ainvoke."""

    def install_patches(self) -> None:
        global _original_invoke, _original_ainvoke
        try:
            import langchain_core.tools as _lc_tools

            if _original_invoke is not None:
                return  # Already patched

            _original_invoke = _lc_tools.BaseTool.invoke
            _original_ainvoke = _lc_tools.BaseTool.ainvoke

            from shekel._context import get_active_budget

            orig_invoke = _original_invoke
            orig_ainvoke = _original_ainvoke

            def _patched_invoke(self: Any, input: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_loop_guard(tool_name, "langchain")
                    active._check_tool_limit(tool_name, "langchain")
                    result = orig_invoke(self, input, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "langchain")
                    return result
                return orig_invoke(self, input, **kwargs)

            async def _patched_ainvoke(self: Any, input: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_loop_guard(tool_name, "langchain")
                    active._check_tool_limit(tool_name, "langchain")
                    result = await orig_ainvoke(self, input, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "langchain")
                    return result
                return await orig_ainvoke(self, input, **kwargs)

            _lc_tools.BaseTool.invoke = _patched_invoke  # type: ignore[assignment, method-assign]
            _lc_tools.BaseTool.ainvoke = _patched_ainvoke  # type: ignore[assignment, method-assign]
        except (ImportError, AttributeError, TypeError):
            pass  # langchain_core not installed or API changed — skip silently

    def remove_patches(self) -> None:
        global _original_invoke, _original_ainvoke
        try:
            if _original_invoke is None:
                return
            import langchain_core.tools as _lc_tools

            _lc_tools.BaseTool.invoke = _original_invoke  # type: ignore[method-assign]
            _lc_tools.BaseTool.ainvoke = _original_ainvoke  # type: ignore[method-assign]
            _original_invoke = None
            _original_ainvoke = None
        except (ImportError, AttributeError, TypeError):  # pragma: no cover
            _original_invoke = None  # pragma: no cover
            _original_ainvoke = None  # pragma: no cover


# ---------------------------------------------------------------------------
# Chain-level helpers
# ---------------------------------------------------------------------------


def _find_chain_cap(chain_name: str, active: Budget) -> Any:
    """Walk the budget parent chain to find a registered chain cap.

    Returns the first ``ComponentBudget`` whose ``_chain_budgets`` contains
    ``chain_name``, starting from ``active`` and walking toward the root.
    Returns ``None`` if no ancestor has a cap for this chain.
    """
    b: Any = active
    while b is not None:
        cb = b._chain_budgets.get(chain_name)
        if cb is not None:
            return cb
        b = b.parent
    return None


def _gate_chain(chain_name: str | None, active: Budget) -> None:
    """Pre-execution budget check for a named chain or runnable.

    Raises ``ChainBudgetExceededError`` if the explicit chain cap or the
    parent budget is already at / over its limit.  No-op when ``chain_name``
    is falsy or when no cap is registered for it.
    """
    if not chain_name:  # pragma: no cover — callers guard on truthiness
        return

    from shekel.exceptions import ChainBudgetExceededError

    cb = _find_chain_cap(chain_name, active)
    if cb is not None and cb._spent >= cb.max_usd:
        raise ChainBudgetExceededError(chain_name=chain_name, spent=cb._spent, limit=cb.max_usd)

    if active._effective_limit is not None and active._spent >= active._effective_limit:
        raise ChainBudgetExceededError(
            chain_name=chain_name,
            spent=active._spent,
            limit=active._effective_limit,
        )


def _attribute_chain_spend(chain_name: str | None, active: Budget, spend_before: float) -> None:
    """Post-execution: add the spend delta to the chain's ComponentBudget._spent."""
    if not chain_name:  # pragma: no cover — callers guard on truthiness
        return
    cb = _find_chain_cap(chain_name, active)
    if cb is not None:
        delta = active._spent - spend_before
        if delta > 0:
            cb._spent += delta


# ---------------------------------------------------------------------------
# LangChainRunnerAdapter — chain-level circuit breaking
# ---------------------------------------------------------------------------


class LangChainRunnerAdapter:
    """Patches ``Runnable._call_with_config``, ``_acall_with_config``, and
    ``RunnableSequence.invoke/ainvoke`` for chain-level budget enforcement.

    Raises ``ImportError`` when ``langchain_core`` is not installed so that
    ``ShekelRuntime.probe()`` silently skips it.
    """

    def install_patches(self, budget: Budget) -> None:  # noqa: ARG002
        global _chain_patch_refcount, _original_call_with_config, _original_acall_with_config
        global _original_sequence_invoke, _original_sequence_ainvoke

        import langchain_core.runnables.base  # raises ImportError if not installed  # noqa: F401
        from langchain_core.runnables.base import Runnable, RunnableSequence

        _chain_patch_refcount += 1
        if _chain_patch_refcount > 1:
            return

        # -- Patch 1: Runnable._call_with_config (sync, covers RunnableLambda etc.) --
        orig_cwc = Runnable._call_with_config
        _original_call_with_config = orig_cwc

        def _patched_cwc(self: Any, func: Any, input_: Any, config: Any, **kwargs: Any) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            name: str | None = getattr(self, "name", None)
            if active is not None and name:
                _gate_chain(name, active)
                spend_before = active._spent
                result = orig_cwc(self, func, input_, config, **kwargs)
                _attribute_chain_spend(name, active, spend_before)
                return result
            return orig_cwc(self, func, input_, config, **kwargs)

        Runnable._call_with_config = _patched_cwc  # type: ignore[method-assign,assignment]

        # -- Patch 2: Runnable._acall_with_config (async, covers async RunnableLambda) --
        orig_acwc = Runnable._acall_with_config
        _original_acall_with_config = orig_acwc

        async def _patched_acwc(
            self: Any, func: Any, input_: Any, config: Any, **kwargs: Any
        ) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            name = getattr(self, "name", None)
            if active is not None and name:
                _gate_chain(name, active)
                spend_before = active._spent
                result = await orig_acwc(self, func, input_, config, **kwargs)
                _attribute_chain_spend(name, active, spend_before)
                return result
            return await orig_acwc(self, func, input_, config, **kwargs)

        Runnable._acall_with_config = _patched_acwc  # type: ignore[method-assign,assignment]

        # -- Patch 3: RunnableSequence.invoke (LCEL pipelines, sync) --
        orig_seq_invoke = RunnableSequence.invoke
        _original_sequence_invoke = orig_seq_invoke

        def _patched_seq_invoke(self: Any, input: Any, config: Any = None, **kwargs: Any) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            name = getattr(self, "name", None)
            if active is not None and name:
                _gate_chain(name, active)
                spend_before = active._spent
                result = orig_seq_invoke(self, input, config, **kwargs)
                _attribute_chain_spend(name, active, spend_before)
                return result
            return orig_seq_invoke(self, input, config, **kwargs)

        RunnableSequence.invoke = _patched_seq_invoke  # type: ignore[method-assign]

        # -- Patch 4: RunnableSequence.ainvoke (LCEL pipelines, async) --
        orig_seq_ainvoke = RunnableSequence.ainvoke
        _original_sequence_ainvoke = orig_seq_ainvoke

        async def _patched_seq_ainvoke(
            self: Any, input: Any, config: Any = None, **kwargs: Any
        ) -> Any:
            from shekel._context import get_active_budget

            active = get_active_budget()
            name = getattr(self, "name", None)
            if active is not None and name:
                _gate_chain(name, active)
                spend_before = active._spent
                result = await orig_seq_ainvoke(self, input, config, **kwargs)
                _attribute_chain_spend(name, active, spend_before)
                return result
            return await orig_seq_ainvoke(self, input, config, **kwargs)

        RunnableSequence.ainvoke = _patched_seq_ainvoke  # type: ignore[method-assign]

    def remove_patches(self, budget: Budget) -> None:  # noqa: ARG002
        global _chain_patch_refcount, _original_call_with_config, _original_acall_with_config
        global _original_sequence_invoke, _original_sequence_ainvoke

        if _chain_patch_refcount <= 0:
            return
        _chain_patch_refcount -= 1
        if _chain_patch_refcount > 0:
            return

        if _original_call_with_config is None:  # pragma: no cover — defensive null check
            return
        try:
            from langchain_core.runnables.base import Runnable, RunnableSequence

            Runnable._call_with_config = _original_call_with_config  # type: ignore[method-assign]
            Runnable._acall_with_config = _original_acall_with_config  # type: ignore[method-assign]
            RunnableSequence.invoke = _original_sequence_invoke  # type: ignore[method-assign]
            RunnableSequence.ainvoke = _original_sequence_ainvoke  # type: ignore[method-assign]
        except ImportError:  # pragma: no cover — defensive cleanup
            pass
        _original_call_with_config = None
        _original_acall_with_config = None
        _original_sequence_invoke = None
        _original_sequence_ainvoke = None
