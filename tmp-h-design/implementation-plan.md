# Implementation Plan: Hierarchical Budget Enforcement

**Branch:** `feat/hierarchical-integration`
**Design doc:** `tmp-h-design/design-hierarchical-integration.md`
**PRD:** `tmp-h-design/PRD-hierarchical-integration.md`

Each phase is independently deliverable and releasable. Later phases depend on Phase 0 (ShekelRuntime) but not on each other.

---

## Phase 0 — ShekelRuntime Foundation (v0.3.1.1)

**Delivers:** Detection infrastructure and explicit API surface. Prerequisite for all later phases.

### What ships

- `ShekelRuntime` class — owns framework detection and adapter wiring
- `Budget.node()`, `Budget.agent()`, `Budget.task()` — explicit per-component cap API
- Enhanced `budget.tree()` — renders full hierarchy including node/agent/task child budgets

### Files to create

- `shekel/_runtime.py` — `ShekelRuntime` class

### Files to modify

- `shekel/_budget.py` — add `.node()`, `.agent()`, `.task()` methods; call `ShekelRuntime.probe()` on `__enter__`
- `shekel/__init__.py` — export new exception classes
- `shekel/exceptions.py` — add `NodeBudgetExceededError`, `AgentBudgetExceededError`, `TaskBudgetExceededError`, `SessionBudgetExceededError`

### Key design

```python
# shekel/_runtime.py
class ShekelRuntime:
    """Probes for installed frameworks and wires adapters at budget open."""

    ADAPTERS: list[type[ProviderAdapter]] = []  # populated by each phase

    @classmethod
    def probe(cls, budget: Budget) -> None:
        """Called once on budget.__enter__(). Activates all detected adapters."""
        for adapter_cls in cls.ADAPTERS:
            try:
                adapter = adapter_cls()
                adapter.install_patches(budget)
            except ImportError:
                pass  # framework not installed — silent skip
```

```python
# Budget gains:
def node(self, name: str, max_usd: float) -> Budget:
    """Register an explicit cap for a LangGraph node."""
    child = Budget(max_usd=max_usd, name=f"node:{name}", parent=self)
    self._node_budgets[name] = child
    return child

def agent(self, name: str, max_usd: float) -> Budget:
    """Register an explicit cap for an agent (CrewAI / OpenClaw)."""
    child = Budget(max_usd=max_usd, name=f"agent:{name}", parent=self)
    self._agent_budgets[name] = child
    return child

def task(self, name: str, max_usd: float) -> Budget:
    """Register an explicit cap for a task (CrewAI)."""
    child = Budget(max_usd=max_usd, name=f"task:{name}", parent=self)
    self._task_budgets[name] = child
    return child
```

### TDD test file

`tests/test_runtime.py`
- Test: `ShekelRuntime.probe()` runs without error when no frameworks installed
- Test: `Budget.node()` creates a child budget with correct limit
- Test: `Budget.agent()` creates a child budget with correct limit
- Test: `Budget.task()` creates a child budget with correct limit
- Test: `budget.tree()` includes node/agent/task children

---

## Phase 1 — LangGraph Layer (v0.3.2)

**Delivers:** Node-level circuit breaking for LangGraph. First framework integration. Highest-priority unmet need.

### What ships

- `LangGraphAdapter` — patches `StateGraph.add_node()` transparently
- `NodeBudgetExceededError` — level-specific exception with `node_name`
- Per-node explicit caps via `b.node("name", max_usd=X)`
- Implicit mode: full attribution + parent enforcement, no per-node cap required
- Async node support
- `budget.tree()` shows per-node spend

### Dependency

- Phase 0 (ShekelRuntime) must be complete

### Files to create

- `shekel/providers/langgraph.py` — `LangGraphAdapter`
- `tests/test_langgraph_wrappers.py` — all LangGraph integration tests

### Files to modify

- `shekel/_runtime.py` — register `LangGraphAdapter` in `ADAPTERS`
- `shekel/exceptions.py` — `NodeBudgetExceededError` (already added in Phase 0)

---

### Detailed Implementation: LangGraphAdapter

#### 1. Detection

```python
# shekel/providers/langgraph.py

from __future__ import annotations
from shekel.providers.base import ProviderAdapter

class LangGraphAdapter(ProviderAdapter):
    name = "langgraph"

    def install_patches(self, budget: Budget) -> None:
        import langgraph.graph.state  # raises ImportError if not installed
        from langgraph.graph.state import StateGraph
        _patch_state_graph(StateGraph, budget)

    def remove_patches(self) -> None:
        from langgraph.graph.state import StateGraph
        _unpatch_state_graph(StateGraph)
```

#### 2. Patching `StateGraph.add_node()`

```python
_ORIGINAL_ADD_NODE = None

def _patch_state_graph(StateGraph, budget: Budget) -> None:
    global _ORIGINAL_ADD_NODE
    if _ORIGINAL_ADD_NODE is not None:
        return  # already patched (reference counting handled by _patch.py pattern)

    _ORIGINAL_ADD_NODE = StateGraph.add_node

    def patched_add_node(self, node: str | type, fn=None, **kwargs):
        node_name = node if isinstance(node, str) else node.__name__
        if fn is not None:
            fn = _wrap_node(node_name, fn, budget)
        elif callable(node):
            # add_node("my_node") where node itself is callable
            fn = _wrap_node(node_name, node, budget)
            node = node_name
        return _ORIGINAL_ADD_NODE(self, node, fn, **kwargs)

    StateGraph.add_node = patched_add_node
```

#### 3. Budget gate wrapper (sync + async)

```python
import asyncio
import functools
from shekel._context import get_active_budget
from shekel.exceptions import NodeBudgetExceededError

def _wrap_node(node_name: str, fn, budget: Budget):
    """Wrap a LangGraph node function with a pre-execution budget gate."""

    if asyncio.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(state, *args, **kwargs):
            _check_node_budget(node_name, budget)
            return await fn(state, *args, **kwargs)
        return async_wrapper
    else:
        @functools.wraps(fn)
        def sync_wrapper(state, *args, **kwargs):
            _check_node_budget(node_name, budget)
            return fn(state, *args, **kwargs)
        return sync_wrapper


def _check_node_budget(node_name: str, parent_budget: Budget) -> None:
    """Check node-level and parent-level budget before node executes."""
    active = get_active_budget()
    if active is None:
        return

    # Check explicit node cap first
    node_budget = active._node_budgets.get(node_name)
    if node_budget is not None:
        if node_budget.spent >= node_budget.max_usd:
            raise NodeBudgetExceededError(
                node_name=node_name,
                spent=node_budget.spent,
                limit=node_budget.max_usd,
            )

    # Check parent budget (implicit enforcement)
    if active.spent >= active.max_usd:
        raise NodeBudgetExceededError(
            node_name=node_name,
            spent=active.spent,
            limit=active.max_usd,
        )
```

#### 4. `NodeBudgetExceededError`

```python
# shekel/exceptions.py — addition

class NodeBudgetExceededError(BudgetExceededError):
    """Raised when a LangGraph node exceeds its budget cap.

    Raised *before* the node body executes — zero LLM spend wasted
    when an explicit node cap is set.
    """

    def __init__(
        self,
        node_name: str,
        spent: float,
        limit: float,
    ) -> None:
        self.node_name = node_name
        super().__init__(spent=spent, limit=limit, model=f"node:{node_name}")

    def __str__(self) -> str:
        return (
            f"Node budget exceeded for '{self.node_name}' "
            f"(${self.spent:.4f} / ${self.limit:.2f})\n"
            f"  Tip: Increase b.node('{self.node_name}', max_usd=...) "
            f"or remove the explicit cap to use parent budget only."
        )
```

---

### Test Plan: `tests/test_langgraph_wrappers.py`

Follow TDD — write all tests before implementing.

#### Test group 1: Detection and patching

```python
def test_langgraph_adapter_skipped_when_not_installed(monkeypatch):
    """ShekelRuntime silently skips LangGraph if not installed."""
    monkeypatch.setitem(sys.modules, "langgraph", None)
    with budget(max_usd=5.00):
        pass  # no error

def test_langgraph_adapter_patches_add_node_on_budget_open():
    """add_node is patched when budget context is entered."""
    ...

def test_langgraph_adapter_restores_add_node_on_budget_close():
    """add_node is restored after budget context exits."""
    ...

def test_langgraph_adapter_reference_counted():
    """Nested budgets: patch applied once, removed when last budget closes."""
    ...
```

#### Test group 2: Implicit mode (attribution + parent enforcement)

```python
def test_node_spend_attributed_to_parent_budget():
    """LLM spend inside a node rolls up to parent budget."""
    ...

def test_parent_budget_circuit_breaks_during_node_execution():
    """Parent budget exhaustion raises NodeBudgetExceededError."""
    with budget(max_usd=0.01) as b:
        graph = build_test_graph()  # node makes LLM call > $0.01
        with pytest.raises(NodeBudgetExceededError) as exc:
            graph.invoke({"input": "hello"})
        assert exc.value.node_name == "expensive_node"

def test_tree_shows_per_node_attribution():
    """budget.tree() includes node-level spend breakdown."""
    ...

def test_no_cap_nodes_share_parent_budget_uncapped():
    """Nodes without explicit cap are not individually limited."""
    ...
```

#### Test group 3: Explicit node caps

```python
def test_explicit_node_cap_circuit_breaks_before_node_executes():
    """NodeBudgetExceededError raised before node body runs when cap exceeded."""
    with budget(max_usd=5.00) as b:
        b.node("expensive_node", max_usd=0.01)
        graph = build_test_graph()
        # Pre-spend the node budget
        b._node_budgets["expensive_node"]._record_spend(0.02, "gpt-4o", {})
        with pytest.raises(NodeBudgetExceededError) as exc:
            graph.invoke({"input": "hello"})
        assert exc.value.node_name == "expensive_node"
        assert exc.value.limit == 0.01

def test_explicit_cap_does_not_affect_other_nodes():
    """Capping one node does not restrict other nodes."""
    ...

def test_unregistered_node_uses_parent_budget():
    """Node without explicit cap uses parent budget for enforcement."""
    ...
```

#### Test group 4: Async nodes

```python
async def test_async_node_wrapped_correctly():
    """Async node functions are wrapped with async budget gate."""
    ...

async def test_async_node_budget_exceeded_raises():
    """NodeBudgetExceededError raised correctly in async context."""
    ...
```

#### Test group 5: Exception contract

```python
def test_node_budget_exceeded_is_subclass_of_budget_exceeded_error():
    """NodeBudgetExceededError is catchable as BudgetExceededError."""
    err = NodeBudgetExceededError("my_node", spent=0.05, limit=0.01)
    assert isinstance(err, BudgetExceededError)

def test_node_budget_exceeded_error_fields():
    """NodeBudgetExceededError carries node_name, spent, limit."""
    ...

def test_existing_except_budget_exceeded_catches_node_error():
    """Existing user code catching BudgetExceededError still works."""
    with budget(max_usd=0.01):
        with pytest.raises(BudgetExceededError):  # not NodeBudgetExceededError
            graph.invoke(...)
```

#### Test group 6: Edge cases

```python
def test_looping_node_circuit_breaks_on_parent_budget():
    """A node in a loop is stopped when parent budget is exhausted."""
    # Build a graph with a loop (node → self-edge)
    # Each iteration costs $0.001
    # Parent budget is $0.01 → should stop after ~10 iterations
    ...

def test_subgraph_node_wrapped_correctly():
    """Nodes that are themselves subgraphs (CompiledGraph) are wrapped."""
    ...

def test_node_wrapped_only_once_with_nested_budgets():
    """Node function is not double-wrapped when nested budgets are used."""
    ...

def test_budget_gate_overhead_under_1ms():
    """Pre-execution budget check completes in < 1ms."""
    ...
```

---

### Acceptance Criteria (Phase 1)

- [ ] `StateGraph.add_node()` is transparently patched when LangGraph is installed and a budget is active
- [ ] Every node — sync and async — is wrapped with a pre-execution budget gate
- [ ] `NodeBudgetExceededError` is raised with correct `node_name`, `spent`, `limit`
- [ ] `NodeBudgetExceededError` is a subclass of `BudgetExceededError` — existing catch-all still works
- [ ] Implicit mode: parent budget enforces total, per-node attribution tracked
- [ ] Explicit mode: `b.node("name", max_usd=X)` creates a hard cap for that node
- [ ] Looping nodes are circuit-broken when parent budget exhausts
- [ ] Patch is reference-counted: nested budgets don't double-patch
- [ ] 100% code coverage
- [ ] All linters pass: `black`, `isort`, `ruff`, `mypy`

---

## Phase 2 — CrewAI Layer (v0.3.3)

**Delivers:** Agent-level and task-level circuit breaking for CrewAI.

### What ships

- `CrewAIAdapter` — registers as `BaseEventListener` on `crewai_event_bus`
- `AgentBudgetExceededError` — with `agent_name`, `spent`, `limit`
- `TaskBudgetExceededError` — with `task_name`, `spent`, `limit`
- Pre-task and pre-agent circuit breaking (before any LLM call is made)
- `b.agent("name", max_usd=X)` and `b.task("name", max_usd=X)` explicit API

### Files to create

- `shekel/providers/crewai.py` — `CrewAIAdapter` extending existing `crewai.py`
- `tests/test_crewai_wrappers.py`

### Key design

`CrewAIAdapter.install_patches()` registers `ShekelEventListener` on the global `crewai_event_bus`. On `TaskStartedEvent`, check task cap → raise `TaskBudgetExceededError` if exceeded. On `AgentExecutionStartedEvent`, check agent cap. On `LLMCallCompletedEvent`, record spend to agent + task child budgets.

### Test groups (high-level)

- Agent cap circuit-breaks before agent executes
- Task cap circuit-breaks before task's first LLM call
- Uncapped agents/tasks share parent budget
- Parallel crew tasks: correct `contextvars` budget lookup per task
- Exception hierarchy: both new exceptions are subclasses of `BudgetExceededError`
- Listener deregistered on budget close

---

## Phase 3 — Loop Detection (v0.3.4)

**Delivers:** Velocity-based circuit breaking. Catches runaway loops before absolute limit is hit.

### What ships

- Spend velocity tracker on `Budget` class
- `loop_detection_multiplier` and `loop_detection_window` parameters on `budget()`
- Circuit-break when instantaneous rate > N× rolling baseline
- Raises `BudgetExceededError` with message indicating loop detection triggered

### Files to modify

- `shekel/_budget.py` — add velocity tracking to `_record_spend()`
- `tests/test_loop_detection.py`

### Key design

Rolling window: store `(timestamp, amount)` tuples in a deque. On each `_record_spend()` call, evict entries older than `loop_detection_window` seconds, compute rate. If rate > `multiplier × baseline`, raise.

Default: disabled (`loop_detection_multiplier=None`). Opt-in only.

---

## Phase 4 — Tiered Thresholds (v0.3.5)

**Delivers:** N-tier enforcement (warn / fallback / disable tools / stop) instead of binary warn + hard stop.

### What ships

- `tiers` parameter on `budget()`
- Actions: `"warn"`, `"fallback:<model>"`, `"disable_tools"`, `"stop"`
- Backward compatible: existing `warn_at` and `fallback` still work as before

### Files to modify

- `shekel/_budget.py` — tier evaluation in `_check_limits()`
- `shekel/_run_config.py` — `tiers` parameter
- `tests/test_tiered_thresholds.py`

---

## Phase 5 — OpenClaw Layer (v0.3.6)

**Delivers:** Session-level circuit breaking for OpenClaw always-on agents.

### What ships

- `OpenClawAdapter` — hooks into `openclaw-sdk` agent lifecycle
- `SessionBudgetExceededError` — with `agent_name`, `spent`, `limit`, `window`
- Session suspension on budget breach (does not kill Gateway)
- `TemporalBudget` as default budget type for OpenClaw contexts

### Files to create

- `shekel/providers/openclaw.py` — `OpenClawAdapter`
- `tests/test_openclaw_wrappers.py`

### Open question to resolve first

Does `openclaw-sdk` expose Python lifecycle hooks for agent start/stop/suspend? If not, alternative: patch the agent's LLM call path and use TemporalBudget's rolling window as the enforcement mechanism.

---

## Phase 6 — DX Layer (v0.3.7)

**Delivers:** Adoption-friendly features — showback mode, budget tags, system-wide policy.

### What ships

- `mode="showback"` parameter on `budget()` — track everything, raise nothing
- `tags` parameter on `@tool()` decorator
- `budget.summary(group_by="tags")` output
- System-wide defaults via `shekel.configure(per_llm_call_max=0.10)` (or env vars)

### Files to modify

- `shekel/_budget.py` — `mode` parameter, skip raise in showback
- `shekel/_tool.py` — `tags` parameter on `@tool`
- `shekel/_run_config.py` — global defaults
- `tests/test_showback_mode.py`, `tests/test_budget_tags.py`

---

## Cross-Cutting Concerns (All Phases)

### Testing standards (from CLAUDE.md)

- TDD: all tests written before implementation
- 100% coverage on all new code
- Test files named by domain: `test_langgraph_wrappers.py`, `test_crewai_wrappers.py`, etc.
- Run after each phase: `pytest --cov=shekel --cov-report=term-missing`

### Linting (run after each phase)

```bash
python -m black shekel/ tests/
python -m isort shekel/ tests/
python -m ruff check shekel/ tests/
python -m mypy shekel/
```

### Optional dependency pattern (existing convention)

Each adapter wraps its import in `try/except ImportError` or raises `ImportError` from `install_patches()` — `ShekelRuntime` catches and silently skips.

### Backward compatibility

Every phase must pass the full existing test suite unchanged. No existing API is modified — only additive changes.

---

## Delivery Summary

| Phase | Version | Layer | Independent? |
|---|---|---|---|
| Phase 0 | v0.3.1 | ShekelRuntime + foundation API | Yes (prerequisite) |
| Phase 1 | v0.3.2 | LangGraph — node-level | Depends on Phase 0 |
| Phase 2 | v0.3.3 | CrewAI — agent + task level | Depends on Phase 0 |
| Phase 3 | v0.3.4 | Loop detection | Depends on Phase 0 |
| Phase 4 | v0.3.5 | Tiered thresholds | Depends on Phase 0 |
| Phase 5 | v0.3.6 | OpenClaw — session level | Depends on Phase 0 |
| Phase 6 | v0.3.7 | DX layer | Depends on Phase 0 |

Phases 1–6 are independent of each other and can be developed in parallel after Phase 0.
