"""LangGraph adapter for Shekel — node-level circuit breaking (v1.0.0).

Patches ``StateGraph.add_node()`` transparently so every node — sync and async
— is wrapped with a pre-execution budget gate. Requires no user code changes:
just open a ``budget()`` context before building the graph.

How it works:

1. On ``budget.__enter__()``, ``ShekelRuntime.probe()`` calls
   ``LangGraphAdapter().install_patches(budget)``.  The adapter patches
   ``StateGraph.add_node`` with a version that wraps each node function with
   ``_make_gate()``.
2. When a node runs, the gate:
   a. Checks the explicit node cap (``b.node("name", max_usd=X)``), if set.
   b. Checks the parent budget total.
   c. On success, records the spend delta into ``ComponentBudget._spent``.
3. On ``budget.__exit__()``, ``ShekelRuntime.release()`` calls
   ``remove_patches()``.  A reference counter ensures nested budgets don't
   double-patch or prematurely restore the original method.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

_original_add_node: Any = None
_patch_refcount: int = 0


class LangGraphAdapter:
    """Patches ``StateGraph.add_node()`` for node-level budget enforcement."""

    def install_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Patch ``StateGraph.add_node``.  Raises ``ImportError`` when langgraph
        is not installed so that ``ShekelRuntime.probe()`` silently skips it.
        """
        global _original_add_node, _patch_refcount

        import langgraph.graph.state  # raises ImportError if not installed  # noqa: F401
        from langgraph.graph.state import StateGraph

        _patch_refcount += 1
        if _patch_refcount > 1:
            return  # already patched — just increment the refcount

        orig = StateGraph.add_node
        _original_add_node = orig

        def _patched_add_node(self: Any, node: Any, action: Any = None, **kwargs: Any) -> Any:
            if action is None and callable(node):
                # add_node(fn) — fn.__name__ is the node name
                node_name = getattr(node, "__name__", str(node))
                return orig(self, _make_gate(node, node_name), None, **kwargs)
            if isinstance(node, str) and action is not None and callable(action):
                # add_node("name", fn)
                return orig(self, node, _make_gate(action, node), **kwargs)
            # Passthrough: non-callable action or other invalid inputs —
            # forward to LangGraph to let it raise its own validation error.
            return orig(self, node, action, **kwargs)  # pragma: no cover

        StateGraph.add_node = _patched_add_node  # type: ignore[method-assign]

    def remove_patches(self, budget: Any) -> None:  # noqa: ARG002
        """Restore ``StateGraph.add_node``.  Only restores when the last
        active budget closes (reference count reaches zero).
        """
        global _patch_refcount

        if _patch_refcount <= 0:
            return
        _patch_refcount -= 1
        if _patch_refcount > 0:
            return  # other budgets still active

        if _original_add_node is None:
            return
        try:
            from langgraph.graph.state import StateGraph

            StateGraph.add_node = _original_add_node  # type: ignore[method-assign]
        except ImportError:  # pragma: no cover — defensive cleanup
            pass


# ---------------------------------------------------------------------------
# Gate factory
# ---------------------------------------------------------------------------


def _make_gate(fn: Any, node_name: str) -> Any:
    """Return a sync or async wrapper that gates ``fn`` with budget checks."""
    if inspect.iscoroutinefunction(fn):
        return _make_async_gate(fn, node_name)
    return _make_sync_gate(fn, node_name)


def _make_sync_gate(fn: Any, node_name: str) -> Any:
    @functools.wraps(fn)
    def _gated(state: Any, *args: Any, **kwargs: Any) -> Any:
        from shekel._context import get_active_budget

        active = get_active_budget()
        if active is None:
            return fn(state, *args, **kwargs)

        _gate(node_name, active)
        spend_before = active._spent
        result = fn(state, *args, **kwargs)
        _attribute_spend(node_name, active, spend_before)
        return result

    return _gated


def _make_async_gate(fn: Any, node_name: str) -> Any:
    @functools.wraps(fn)
    async def _gated(state: Any, *args: Any, **kwargs: Any) -> Any:
        from shekel._context import get_active_budget

        active = get_active_budget()
        if active is None:
            return await fn(state, *args, **kwargs)

        _gate(node_name, active)
        spend_before = active._spent
        result = await fn(state, *args, **kwargs)
        _attribute_spend(node_name, active, spend_before)
        return result

    return _gated


# ---------------------------------------------------------------------------
# Gate logic and spend attribution
# ---------------------------------------------------------------------------


def _find_node_cap(node_name: str, active: Any) -> Any:
    """Walk the budget parent chain to find a registered node cap.

    Returns the first ``ComponentBudget`` whose ``_node_budgets`` contains
    ``node_name``, starting from ``active`` and walking toward the root.
    Returns ``None`` if no ancestor has a cap for this node.
    """
    b: Any = active
    while b is not None:
        cb = b._node_budgets.get(node_name)
        if cb is not None:
            return cb
        b = b.parent
    return None


def _gate(node_name: str, active: Any) -> None:
    """Pre-execution budget check.  Raises ``NodeBudgetExceededError`` if the
    explicit node cap or parent budget is already at / over its limit.
    """
    from shekel.exceptions import NodeBudgetExceededError

    # 1. Explicit node cap check — walk up to find the cap (highest priority)
    cb = _find_node_cap(node_name, active)
    if cb is not None and cb._spent >= cb.max_usd:
        raise NodeBudgetExceededError(node_name=node_name, spent=cb._spent, limit=cb.max_usd)

    # 2. Parent budget total check
    if active._effective_limit is not None and active._spent >= active._effective_limit:
        raise NodeBudgetExceededError(
            node_name=node_name,
            spent=active._spent,
            limit=active._effective_limit,
        )


def _attribute_spend(node_name: str, active: Any, spend_before: float) -> None:
    """Post-execution: add the spend delta to the node's ComponentBudget._spent."""
    cb = _find_node_cap(node_name, active)
    if cb is not None:
        delta = active._spent - spend_before
        if delta > 0:
            cb._spent += delta
