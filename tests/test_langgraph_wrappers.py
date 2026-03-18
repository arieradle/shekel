"""Tests for LangGraph node-level budget enforcement (v0.3.1).

Domain: lg_mod.LangGraphAdapter — patching, node gate, spend attribution, async support.
"""

from __future__ import annotations

import inspect
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import shekel.providers.langgraph as lg_mod
from shekel import budget
from shekel._budget import Budget
from shekel._runtime import ShekelRuntime
from shekel.exceptions import BudgetExceededError, NodeBudgetExceededError

try:
    from langgraph.graph import END, StateGraph
    from typing_extensions import TypedDict

    LANGGRAPH_AVAILABLE = True

    class _State(TypedDict):
        value: int

except ImportError:
    LANGGRAPH_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_adapter_state():
    """Restore lg_mod.LangGraphAdapter patch state and ShekelRuntime registry after each test."""
    original_refcount = lg_mod._patch_refcount
    original_add_node = lg_mod._original_add_node
    original_registry = ShekelRuntime._adapter_registry[:]

    # Capture the actual StateGraph.add_node before any test mutations
    real_add_node = StateGraph.add_node

    yield

    # Restore module state
    lg_mod._patch_refcount = original_refcount
    lg_mod._original_add_node = original_add_node

    # Restore StateGraph
    StateGraph.add_node = real_add_node  # type: ignore[method-assign]

    # Restore registry
    ShekelRuntime._adapter_registry = original_registry


def _make_simple_graph(node_name: str, node_fn: Any) -> Any:
    """Build a minimal single-node StateGraph."""
    g = StateGraph(_State)
    g.add_node(node_name, node_fn)
    g.set_entry_point(node_name)
    g.add_edge(node_name, END)
    return g.compile()


# ---------------------------------------------------------------------------
# Group 1: lg_mod.LangGraphAdapter registered in ShekelRuntime
# ---------------------------------------------------------------------------


def test_langgraph_adapter_in_runtime_registry() -> None:
    """lg_mod.LangGraphAdapter is registered in ShekelRuntime at import time."""
    assert lg_mod.LangGraphAdapter in ShekelRuntime._adapter_registry


def test_langgraph_adapter_is_registered_exactly_once() -> None:
    """lg_mod.LangGraphAdapter appears exactly once in the registry."""
    count = sum(1 for a in ShekelRuntime._adapter_registry if a is lg_mod.LangGraphAdapter)
    assert count == 1


# ---------------------------------------------------------------------------
# Group 2: install_patches / remove_patches lifecycle
# ---------------------------------------------------------------------------


def test_install_patches_replaces_add_node() -> None:
    """install_patches() replaces StateGraph.add_node with the gated version."""
    original = StateGraph.add_node
    adapter = lg_mod.LangGraphAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert StateGraph.add_node is not original
    adapter.remove_patches(b)


def test_install_patches_raises_import_error_when_langgraph_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install_patches() raises ImportError when langgraph is not importable."""
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph.state", None)
    adapter = lg_mod.LangGraphAdapter()
    with pytest.raises(ImportError):
        adapter.install_patches(Budget(max_usd=5.00))


def test_remove_patches_restores_add_node() -> None:
    """remove_patches() restores StateGraph.add_node to the original."""
    original = StateGraph.add_node
    adapter = lg_mod.LangGraphAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert StateGraph.add_node is original


def test_reference_counting_patch_applied_once_for_nested_budgets() -> None:
    """Nested budgets increment refcount but only patch add_node once."""
    original = StateGraph.add_node
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    a1 = lg_mod.LangGraphAdapter()
    a2 = lg_mod.LangGraphAdapter()

    a1.install_patches(b1)
    patched = StateGraph.add_node
    assert patched is not original
    assert lg_mod._patch_refcount == 1

    a2.install_patches(b2)
    assert StateGraph.add_node is patched  # still the same patch
    assert lg_mod._patch_refcount == 2

    a2.remove_patches(b2)
    assert StateGraph.add_node is patched  # still patched (refcount 1)
    assert lg_mod._patch_refcount == 1

    a1.remove_patches(b1)
    assert StateGraph.add_node is original  # fully restored
    assert lg_mod._patch_refcount == 0


def test_remove_patches_is_safe_at_zero_refcount() -> None:
    """remove_patches() is a no-op when refcount is already 0."""
    adapter = lg_mod.LangGraphAdapter()
    lg_mod._patch_refcount = 0
    adapter.remove_patches(Budget(max_usd=5.00))  # must not raise
    assert lg_mod._patch_refcount == 0


def test_remove_patches_is_safe_when_original_is_none() -> None:
    """remove_patches() is a no-op when _original_add_node is None (refcount 1→0)."""
    adapter = lg_mod.LangGraphAdapter()
    lg_mod._patch_refcount = 1
    lg_mod._original_add_node = None  # simulate missing original
    adapter.remove_patches(Budget(max_usd=5.00))  # must not raise
    assert lg_mod._patch_refcount == 0


def test_add_node_callable_action_gets_wrapped() -> None:
    """Compiled subgraph (callable) passed as action is wrapped with the gate."""
    with budget(max_usd=5.00):
        # Build a subgraph and pass it as the action
        sub = StateGraph(_State)
        sub.add_node("inner", lambda s: {"value": s["value"] + 1})
        sub.set_entry_point("inner")
        sub.add_edge("inner", END)
        compiled_sub = sub.compile()

        # compiled_sub is callable — should be wrapped, not passed through
        wrapped = lg_mod._make_gate(compiled_sub, "sub")
        assert callable(wrapped)
        assert wrapped.__wrapped__ is compiled_sub or hasattr(wrapped, "__wrapped__")


def test_add_node_restored_on_budget_exit_even_on_exception() -> None:
    """StateGraph.add_node is restored even when an exception propagates."""
    original = StateGraph.add_node
    try:
        with budget(max_usd=5.00):
            patched = StateGraph.add_node
            assert patched is not original
            raise ValueError("simulated error")
    except ValueError:
        pass
    assert StateGraph.add_node is original


# ---------------------------------------------------------------------------
# Group 3: Node wrapping — name resolution and callable detection
# ---------------------------------------------------------------------------


def test_add_node_name_fn_form_wraps_action() -> None:
    """add_node('name', fn) wraps fn; node body is reachable via the wrapper."""
    called: list[bool] = []

    def my_node(state: _State) -> dict:
        called.append(True)
        return {"value": state["value"] + 1}

    with budget(max_usd=5.00):
        app = _make_simple_graph("my_node", my_node)
        result = app.invoke({"value": 0})

    assert result["value"] == 1
    assert called == [True]


def test_add_node_fn_form_wraps_callable() -> None:
    """add_node(fn) form (no explicit name) wraps fn using fn.__name__."""
    called: list[bool] = []

    def my_node(state: _State) -> dict:
        called.append(True)
        return {"value": 99}

    with budget(max_usd=5.00):
        g = StateGraph(_State)
        g.add_node(my_node)
        g.set_entry_point("my_node")
        g.add_edge("my_node", END)
        app = g.compile()
        app.invoke({"value": 0})

    assert called == [True]


def test_functools_wraps_preserves_original_name() -> None:
    """The gated wrapper has __name__ == original function __name__."""

    def target(state: _State) -> dict:
        return {"value": 0}

    wrapped = lg_mod._make_gate(target, "target")
    assert wrapped.__name__ == "target"


def test_sync_node_wrapped_as_sync() -> None:
    """A sync node function is wrapped with a sync (non-coroutine) gate."""

    def sync_node(state: _State) -> dict:
        return {"value": 0}

    wrapped = lg_mod._make_gate(sync_node, "sync_node")
    assert not inspect.iscoroutinefunction(wrapped)


def test_async_node_wrapped_as_async() -> None:
    """An async node function is wrapped with an async (coroutine) gate."""

    async def async_node(state: _State) -> dict:
        return {"value": 0}

    wrapped = lg_mod._make_gate(async_node, "async_node")
    assert inspect.iscoroutinefunction(wrapped)


# ---------------------------------------------------------------------------
# Group 4: Pre-execution gate — explicit node cap
# ---------------------------------------------------------------------------


def test_explicit_node_cap_exceeded_raises_before_node_runs() -> None:
    """NodeBudgetExceededError raised BEFORE the node body executes."""
    executed: list[bool] = []

    def fetch(state: _State) -> dict:
        executed.append(True)  # must never be reached
        return {"value": state["value"] + 1}

    with budget(max_usd=5.00) as b:
        b.node("fetch", max_usd=0.10)
        b._node_budgets["fetch"]._spent = 0.10  # exhaust the cap
        app = _make_simple_graph("fetch", fetch)

        with pytest.raises(NodeBudgetExceededError):
            app.invoke({"value": 0})

    assert executed == []  # node body never ran


def test_explicit_node_cap_error_carries_correct_fields() -> None:
    """NodeBudgetExceededError has correct node_name, spent, limit."""

    def fetch(state: _State) -> dict:
        return {"value": 0}

    with budget(max_usd=5.00) as b:
        b.node("fetch", max_usd=0.10)
        b._node_budgets["fetch"]._spent = 0.10
        app = _make_simple_graph("fetch", fetch)

        with pytest.raises(NodeBudgetExceededError) as exc_info:
            app.invoke({"value": 0})

    err = exc_info.value
    assert err.node_name == "fetch"
    assert err.spent == pytest.approx(0.10)
    assert err.limit == pytest.approx(0.10)


def test_explicit_node_cap_not_exceeded_allows_node_to_run() -> None:
    """Node runs normally when spend is below cap."""

    def fetch(state: _State) -> dict:
        return {"value": state["value"] + 10}

    with budget(max_usd=5.00) as b:
        b.node("fetch", max_usd=0.50)
        b._node_budgets["fetch"]._spent = 0.05  # below cap
        app = _make_simple_graph("fetch", fetch)
        result = app.invoke({"value": 0})

    assert result["value"] == 10


def test_node_cap_does_not_affect_other_nodes() -> None:
    """Capping one node does not prevent other nodes from running."""
    ran: list[str] = []

    def n1(state: _State) -> dict:
        ran.append("n1")
        return {"value": state["value"] + 1}

    def n2(state: _State) -> dict:
        ran.append("n2")
        return {"value": state["value"] + 1}

    with budget(max_usd=5.00) as b:
        b.node("n1", max_usd=0.10)
        b._node_budgets["n1"]._spent = 0.09  # below cap
        # n2 has no cap

        g = StateGraph(_State)
        g.add_node("n1", n1)
        g.add_node("n2", n2)
        g.set_entry_point("n1")
        g.add_edge("n1", "n2")
        g.add_edge("n2", END)
        app = g.compile()
        app.invoke({"value": 0})

    assert ran == ["n1", "n2"]


# ---------------------------------------------------------------------------
# Group 5: Pre-execution gate — parent budget exhaustion
# ---------------------------------------------------------------------------


def test_parent_budget_exhausted_raises_node_budget_exceeded_error() -> None:
    """NodeBudgetExceededError raised when parent budget is at limit."""
    executed: list[bool] = []

    def process(state: _State) -> dict:
        executed.append(True)
        return {"value": 0}

    with budget(max_usd=1.00) as b:
        b._spent = 1.00  # simulate exhausted parent
        app = _make_simple_graph("process", process)

        with pytest.raises(NodeBudgetExceededError) as exc_info:
            app.invoke({"value": 0})

    assert executed == []
    assert exc_info.value.node_name == "process"


def test_parent_budget_not_exhausted_allows_node() -> None:
    """Node runs when parent budget still has headroom."""

    def process(state: _State) -> dict:
        return {"value": 42}

    with budget(max_usd=1.00) as b:
        b._spent = 0.50  # half used
        app = _make_simple_graph("process", process)
        result = app.invoke({"value": 0})

    assert result["value"] == 42


def test_track_only_budget_no_gate() -> None:
    """Track-only budget (no max_usd) never triggers the parent gate."""

    def process(state: _State) -> dict:
        return {"value": 7}

    with budget() as b:
        b._spent = 999.0  # high spend, no limit
        app = _make_simple_graph("process", process)
        result = app.invoke({"value": 0})

    assert result["value"] == 7


def test_node_budget_exceeded_is_subclass_of_budget_exceeded_error() -> None:
    """NodeBudgetExceededError is catchable as BudgetExceededError."""

    def process(state: _State) -> dict:
        return {"value": 0}

    with budget(max_usd=1.00) as b:
        b._spent = 1.00
        app = _make_simple_graph("process", process)

        with pytest.raises(BudgetExceededError):  # catches NodeBudgetExceededError
            app.invoke({"value": 0})


def test_no_active_budget_node_runs_unguarded() -> None:
    """Node executes normally when invoked outside any budget context."""

    def process(state: _State) -> dict:
        return {"value": 100}

    # Build inside a budget context (so add_node is patched)
    with budget(max_usd=5.00):
        app = _make_simple_graph("process", process)

    # Invoke OUTSIDE any budget — get_active_budget() returns None
    result = app.invoke({"value": 0})
    assert result["value"] == 100


# ---------------------------------------------------------------------------
# Group 6: Post-execution spend attribution
# ---------------------------------------------------------------------------


def test_spend_delta_attributed_to_component_budget() -> None:
    """Spend during node execution is attributed to its ComponentBudget._spent."""

    def fetch(state: _State) -> dict:
        return {"value": state["value"]}

    with budget(max_usd=5.00) as b:
        b.node("fetch", max_usd=1.00)

        # Simulate spend occurring during the node by patching _spent after capture
        original_fn_ref: list[Any] = []
        original_fetch = fetch

        def fetch_with_spend(state: _State) -> dict:
            # Simulate an LLM call adding $0.15 to the budget
            b._spent += 0.15
            return original_fn_ref[0](state)

        original_fn_ref.append(original_fetch)

        app = _make_simple_graph("fetch", fetch_with_spend)
        app.invoke({"value": 0})
        cb = b._node_budgets["fetch"]

    assert cb._spent == pytest.approx(0.15)


def test_zero_spend_in_node_leaves_component_budget_at_zero() -> None:
    """When a node causes no LLM spend, ComponentBudget._spent stays 0.0."""

    def cheap_node(state: _State) -> dict:
        return {"value": 1}

    with budget(max_usd=5.00) as b:
        b.node("cheap_node", max_usd=0.50)
        app = _make_simple_graph("cheap_node", cheap_node)
        app.invoke({"value": 0})
        cb = b._node_budgets["cheap_node"]

    assert cb._spent == pytest.approx(0.0)


def test_spend_not_attributed_when_no_cap_registered() -> None:
    """Nodes without an explicit cap don't populate _node_budgets._spent."""

    def process(state: _State) -> dict:
        b._spent += 0.05  # simulated LLM call
        return {"value": 0}

    with budget(max_usd=5.00) as b:
        app = _make_simple_graph("process", process)
        app.invoke({"value": 0})

    assert "process" not in b._node_budgets


def test_multiple_nodes_spend_attributed_separately() -> None:
    """Each node's spend is attributed to its own ComponentBudget independently."""

    with budget(max_usd=5.00) as b:
        b.node("n1", max_usd=1.00)
        b.node("n2", max_usd=1.00)

        def n1(state: _State) -> dict:
            b._spent += 0.10
            return {"value": state["value"] + 1}

        def n2(state: _State) -> dict:
            b._spent += 0.30
            return {"value": state["value"] + 1}

        g = StateGraph(_State)
        g.add_node("n1", n1)
        g.add_node("n2", n2)
        g.set_entry_point("n1")
        g.add_edge("n1", "n2")
        g.add_edge("n2", END)
        app = g.compile()
        app.invoke({"value": 0})

    assert b._node_budgets["n1"]._spent == pytest.approx(0.10)
    assert b._node_budgets["n2"]._spent == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Group 7: Async nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_no_active_budget_node_runs_unguarded() -> None:
    """Async node runs normally when invoked outside any budget context."""

    async def async_process(state: _State) -> dict:
        return {"value": 77}

    with budget(max_usd=5.00):
        g = StateGraph(_State)
        g.add_node("async_process", async_process)
        g.set_entry_point("async_process")
        g.add_edge("async_process", END)
        app = g.compile()

    # Invoke outside any budget — get_active_budget() returns None
    result = await app.ainvoke({"value": 0})
    assert result["value"] == 77


@pytest.mark.asyncio
async def test_async_node_runs_and_returns_result() -> None:
    """Async node wrapped by gate still executes and returns its result."""

    async def async_fetch(state: _State) -> dict:
        return {"value": state["value"] + 5}

    async with budget(max_usd=5.00):
        g = StateGraph(_State)
        g.add_node("async_fetch", async_fetch)
        g.set_entry_point("async_fetch")
        g.add_edge("async_fetch", END)
        app = g.compile()
        result = await app.ainvoke({"value": 0})

    assert result["value"] == 5


@pytest.mark.asyncio
async def test_async_node_cap_exceeded_raises_before_execution() -> None:
    """Async node gate raises NodeBudgetExceededError before awaiting node body."""
    executed: list[bool] = []

    async def async_fetch(state: _State) -> dict:
        executed.append(True)
        return {"value": 0}

    async with budget(max_usd=5.00) as b:
        b.node("async_fetch", max_usd=0.10)
        b._node_budgets["async_fetch"]._spent = 0.10

        g = StateGraph(_State)
        g.add_node("async_fetch", async_fetch)
        g.set_entry_point("async_fetch")
        g.add_edge("async_fetch", END)
        app = g.compile()

        with pytest.raises(NodeBudgetExceededError):
            await app.ainvoke({"value": 0})

    assert executed == []


@pytest.mark.asyncio
async def test_async_spend_attributed_to_component_budget() -> None:
    """Spend during async node execution is attributed to its ComponentBudget."""

    async with budget(max_usd=5.00) as b:
        b.node("async_fetch", max_usd=1.00)

        async def async_fetch(state: _State) -> dict:
            b._spent += 0.20
            return {"value": 0}

        g = StateGraph(_State)
        g.add_node("async_fetch", async_fetch)
        g.set_entry_point("async_fetch")
        g.add_edge("async_fetch", END)
        app = g.compile()
        await app.ainvoke({"value": 0})

    assert b._node_budgets["async_fetch"]._spent == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Group 8: Integration with Budget lifecycle via ShekelRuntime
# ---------------------------------------------------------------------------


def test_add_node_patched_on_budget_enter() -> None:
    """StateGraph.add_node is patched when a budget context is entered."""
    original = StateGraph.add_node
    with budget(max_usd=5.00):
        assert StateGraph.add_node is not original
    assert StateGraph.add_node is original


def test_add_node_restored_on_budget_exit() -> None:
    """StateGraph.add_node is restored after the budget context exits."""
    original = StateGraph.add_node
    with budget(max_usd=5.00):
        pass
    assert StateGraph.add_node is original


def test_mock_llm_spend_tracked_with_node_cap() -> None:
    """End-to-end: mocked LLM call inside node → spend tracked in ComponentBudget."""
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "ok"
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 50
    mock_resp.model = "gpt-4o-mini"

    with patch(
        "openai.resources.chat.completions.Completions.create",
        return_value=mock_resp,
    ):
        import openai

        client = openai.OpenAI(api_key="test")

        with budget(max_usd=5.00) as b:
            b.node("llm_node", max_usd=1.00)

            def llm_node(state: _State) -> dict:
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hello"}],
                )
                return {"value": state["value"] + 1}

            app = _make_simple_graph("llm_node", llm_node)
            app.invoke({"value": 0})

    assert b._node_budgets["llm_node"]._spent > 0
    assert b._node_budgets["llm_node"]._spent == pytest.approx(b.spent)


# ---------------------------------------------------------------------------
# Group 9: Nested budget cap inheritance (parent-chain lookup)
# ---------------------------------------------------------------------------


def test_node_cap_on_outer_budget_enforced_in_nested_inner_budget() -> None:
    """Cap registered on outer budget raises NodeBudgetExceededError inside inner context."""
    executed: list[bool] = []

    def fetch(state: _State) -> dict:
        executed.append(True)
        return {"value": 0}

    with budget(max_usd=5.00, name="outer") as outer:
        outer.node("fetch", max_usd=0.10)
        outer._node_budgets["fetch"]._spent = 0.10  # exhaust the cap

        with budget(max_usd=2.00, name="inner"):
            app = _make_simple_graph("fetch", fetch)
            with pytest.raises(NodeBudgetExceededError):
                app.invoke({"value": 0})

    assert executed == []


def test_node_cap_spend_attributed_to_outer_budget_when_invoked_in_inner_context() -> None:
    """Spend delta attributed to outer budget's ComponentBudget when cap is registered there."""
    with budget(max_usd=5.00, name="outer") as outer:
        outer.node("fetch", max_usd=1.00)

        with budget(max_usd=2.00, name="inner") as inner:

            def fetch(state: _State) -> dict:
                inner._spent += 0.15  # simulate LLM spend on inner budget
                return {"value": 0}

            app = _make_simple_graph("fetch", fetch)
            app.invoke({"value": 0})

    assert outer._node_budgets["fetch"]._spent == pytest.approx(0.15)


def test_node_cap_found_on_grandparent_budget() -> None:
    """Cap registered on grandparent is found when graph runs two levels deep."""
    executed: list[bool] = []

    def fetch(state: _State) -> dict:
        executed.append(True)
        return {"value": 0}

    with budget(max_usd=10.00, name="root") as root:
        root.node("fetch", max_usd=0.10)
        root._node_budgets["fetch"]._spent = 0.10

        with budget(max_usd=5.00, name="mid"):
            with budget(max_usd=2.00, name="inner"):
                app = _make_simple_graph("fetch", fetch)
                with pytest.raises(NodeBudgetExceededError):
                    app.invoke({"value": 0})

    assert executed == []


def test_inner_budget_node_cap_takes_precedence_over_outer() -> None:
    """Cap registered on inner budget is used even if outer also has a cap for the same node."""

    def fetch(state: _State) -> dict:
        return {"value": 0}

    with budget(max_usd=5.00, name="outer") as outer:
        outer.node("fetch", max_usd=1.00)  # outer cap: $1.00 — not exceeded

        with budget(max_usd=2.00, name="inner") as inner:
            inner.node("fetch", max_usd=0.05)
            inner._node_budgets["fetch"]._spent = 0.05  # exhaust inner cap

            app = _make_simple_graph("fetch", fetch)
            with pytest.raises(NodeBudgetExceededError) as exc_info:
                app.invoke({"value": 0})

    # Raised using the inner cap ($0.05), not the outer cap ($1.00)
    assert exc_info.value.limit == pytest.approx(0.05)


def test_looping_node_circuit_breaks_on_parent_budget() -> None:
    """A node in a retry loop is stopped when parent budget is exhausted."""
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "ok"
    mock_resp.usage.prompt_tokens = 10000  # high token count to exhaust budget fast
    mock_resp.usage.completion_tokens = 5000
    mock_resp.model = "gpt-4o-mini"

    from typing_extensions import TypedDict

    class _LoopState(TypedDict):
        count: int

    with patch(
        "openai.resources.chat.completions.Completions.create",
        return_value=mock_resp,
    ):
        import openai

        client = openai.OpenAI(api_key="test")

        def loop_node(state: _LoopState) -> dict:
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "x"}],
            )
            return {"count": state["count"] + 1}

        def should_loop(state: Any) -> str:
            return "done" if state["count"] >= 100 else "loop"

        g = StateGraph(_LoopState)
        g.add_node("loop_node", loop_node)
        g.set_entry_point("loop_node")
        g.add_conditional_edges("loop_node", should_loop, {"loop": "loop_node", "done": END})
        app = g.compile()

        with pytest.raises((BudgetExceededError, NodeBudgetExceededError)):
            with budget(
                max_usd=0.001,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ):
                app.invoke({"count": 0})
