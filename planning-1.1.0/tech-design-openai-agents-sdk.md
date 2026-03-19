# Technical Design: OpenAI Agents SDK Adapter

**Feature:** `OpenAIAgentsRunnerAdapter`
**Target version:** 1.1.0
**Status:** Planning
**Date:** 2026-03-19

---

## 1. Architecture Overview

### How it fits into ShekelRuntime

`ShekelRuntime` maintains a class-level `_adapter_registry` list. On `Budget.__enter__()`, `ShekelRuntime.probe()` instantiates each registered adapter and calls `adapter.install_patches(budget)`. On `Budget.__exit__()`, `ShekelRuntime.release()` calls `adapter.remove_patches(budget)` for each adapter that was activated.

The new `OpenAIAgentsRunnerAdapter` follows this same pattern identically to `LangGraphAdapter` and `LangChainRunnerAdapter`:

```
Budget.__enter__()
  └─ ShekelRuntime.probe()
       └─ OpenAIAgentsRunnerAdapter().install_patches(budget)
            ├─ import agents  → raises ImportError if not installed → silently skipped
            ├─ _patch_refcount += 1
            ├─ if refcount == 1: monkey-patch Runner.run / run_sync / run_streamed
            └─ store originals in module-level globals

Budget.__exit__()
  └─ ShekelRuntime.release()
       └─ OpenAIAgentsRunnerAdapter().remove_patches(budget)
            ├─ _patch_refcount -= 1
            └─ if refcount == 0: restore originals from module-level globals
```

The adapter lives in `shekel/providers/openai_agents_runner.py` — a new file, separate from the existing `openai_agents.py` (which handles tool-level patching via `FunctionTool.on_invoke_tool`). This separation keeps tool budgets and runner budgets orthogonal and independently removable.

### Relationship to existing `openai_agents.py`

The existing `OpenAIAgentsAdapter` in `openai_agents.py` patches `FunctionTool.on_invoke_tool` for **tool call counting**. It does not use ref-counted patching and is not registered with `ShekelRuntime`. It is not modified by this feature.

The new `OpenAIAgentsRunnerAdapter` targets the **runner boundary** — `Runner.run` / `run_sync` / `run_streamed` — for **agent-level spend attribution and circuit breaking**. These are orthogonal concerns at different abstraction layers.

---

## 2. Files to Create or Modify

### New file

| Path | Purpose |
|------|---------|
| `shekel/providers/openai_agents_runner.py` | `OpenAIAgentsRunnerAdapter` class, helper functions, module-level patch state |
| `tests/test_openai_agents_wrappers.py` | Full test suite for the new adapter |

### Modified files

| Path | Change |
|------|--------|
| `shekel/_runtime.py` | Import `OpenAIAgentsRunnerAdapter` and call `ShekelRuntime.register(OpenAIAgentsRunnerAdapter)` inside `_register_builtin_adapters()` |

No changes to `shekel/exceptions.py` (reusing `AgentBudgetExceededError`).
No changes to `shekel/_budget.py` (reusing `_agent_budgets` dict and `ComponentBudget`).
No changes to `shekel/__init__.py` (no new public symbols needed; `AgentBudgetExceededError` is already exported).

---

## 3. Class and Method Design for `OpenAIAgentsRunnerAdapter`

### Module-level state (`openai_agents_runner.py`)

```python
_patch_refcount: int = 0
_original_run: Any = None        # Runner.run original classmethod
_original_run_sync: Any = None   # Runner.run_sync original classmethod
_original_run_streamed: Any = None  # Runner.run_streamed original classmethod
```

Using the same module-level global pattern as `langgraph.py` and `langchain.py`. Three separate `_original_*` variables — one per patched method — so restoration is independent and explicit.

### `OpenAIAgentsRunnerAdapter`

```python
class OpenAIAgentsRunnerAdapter:
    """Patches Runner.run, Runner.run_sync, and Runner.run_streamed for
    agent-level budget enforcement.

    Raises ImportError from install_patches() when openai-agents is not
    installed so that ShekelRuntime.probe() silently skips this adapter.
    """

    def install_patches(self, budget: Any) -> None:
        # Raises ImportError if not installed (ShekelRuntime handles this)
        # Increments _patch_refcount; skips patching if refcount > 1 (already patched)
        ...

    def remove_patches(self, budget: Any) -> None:
        # Decrements _patch_refcount; only restores originals when refcount reaches 0
        ...
```

### Helper functions (module-level, private)

```python
def _find_agent_cap(agent_name: str, active: Any) -> Any:
    """Walk the budget parent chain to find the first ComponentBudget for agent_name.
    Returns None if no ancestor has a cap for this agent.
    Mirrors the identical function in shekel/providers/crewai.py."""
    ...

def _gate(agent_name: str, active: Any) -> None:
    """Pre-execution check. Raises AgentBudgetExceededError if:
    1. The agent's ComponentBudget._spent >= ComponentBudget.max_usd, OR
    2. The parent budget's _spent >= _effective_limit.
    No-op when agent_name is falsy."""
    ...

def _attribute_spend(agent_name: str, active: Any, spend_before: float) -> None:
    """Post-execution: add spend delta to ComponentBudget._spent.
    No-op when no cap is registered for agent_name."""
    ...
```

These three helpers follow the identical structure as the parallel functions in `langgraph.py` (`_gate`, `_attribute_spend`) and `crewai.py` (`_find_agent_cap`, `_gate_execution`, `_attribute_execution_spend`). The naming is intentionally consistent.

---

## 4. Exact Patch Mechanism

### Target

`agents.Runner` is a class with three classmethods:
- `Runner.run(agent, input, **kwargs)` — async, returns `RunResult`
- `Runner.run_sync(agent, input, **kwargs)` — sync, returns `RunResult`
- `Runner.run_streamed(agent, input, **kwargs)` — returns `RunResultStreaming` (async generator wrapper)

### Patch approach

All three are patched as **classmethods on the `Runner` class**. The originals are stored in module-level globals before patching.

```
_original_run = Runner.run
_original_run_sync = Runner.run_sync
_original_run_streamed = Runner.run_streamed

Runner.run = _patched_run
Runner.run_sync = _patched_run_sync
Runner.run_streamed = _patched_run_streamed
```

Since these are classmethods, the first argument to the replacement will be `cls` when called as `Runner.run(agent, ...)`. The patched wrappers receive `cls` explicitly and forward it to the original.

### Patch sequence for `Runner.run` (async)

```
_patched_run(cls, agent, input, **kwargs):
    active = get_active_budget()
    if active is None:
        return await _original_run(agent, input, **kwargs)

    agent_name = getattr(agent, "name", None) or ""
    _gate(agent_name, active)              # raises if cap exceeded
    spend_before = active._spent
    try:
        result = await _original_run(agent, input, **kwargs)
    except Exception:
        _attribute_spend(agent_name, active, spend_before)   # attribute partial spend
        raise
    _attribute_spend(agent_name, active, spend_before)
    return result
```

### Patch sequence for `Runner.run_sync` (sync)

Identical structure to `_patched_run` but synchronous — `result = _original_run_sync(agent, input, **kwargs)` without `await`.

### Patch sequence for `Runner.run_streamed` (streaming)

`run_streamed` returns a `RunResultStreaming` object (not an async generator directly). The object is iterable but spend accrues as events are processed internally. The wrapper:

1. Calls `_gate(agent_name, active)` before invoking the original.
2. Captures `spend_before`.
3. Calls the original to obtain the `RunResultStreaming` object.
4. Returns a thin async generator wrapper that iterates the original stream, then calls `_attribute_spend` after the stream is exhausted or on exception.

The wrapper preserves the `RunResultStreaming` interface by wrapping iteration only, not the object itself. If the consumer does not fully iterate the stream, spend attribution will be partial (same limitation as any lazy streaming system). This is documented in the PRD edge cases.

### Ref-counting

Identical to `LangGraphAdapter`:

```
install_patches():
    _patch_refcount += 1
    if _patch_refcount > 1:
        return  # already patched

remove_patches():
    _patch_refcount -= 1
    if _patch_refcount > 0:
        return  # other budgets still active
    # restore originals
```

This ensures nested `budget()` contexts (e.g., a parent and child budget both open) do not double-patch `Runner` and do not prematurely restore it when the inner budget exits.

### Restoration

```python
Runner.run = _original_run
Runner.run_sync = _original_run_sync
Runner.run_streamed = _original_run_streamed
_original_run = None
_original_run_sync = None
_original_run_streamed = None
```

All three module globals are reset to `None` after restoration, matching the `langchain.py` pattern. The entire restoration block is wrapped in `try/except ImportError` as a defensive measure in case the library was unloaded.

---

## 5. Spend Attribution Approach

### Mechanism

OpenAI API spend is tracked by the existing `shekel/providers/openai.py` wrapper, which intercepts `openai.chat.completions.create` (and its async/streaming variants) and increments `active._spent` directly. This means that by the time `Runner.run` returns, `active._spent` already reflects the full token cost of all LLM calls made during that agent run.

The spend delta is therefore:

```python
spend_before = active._spent       # snapshot before runner call
# ... agent runs, openai.py increments active._spent ...
delta = active._spent - spend_before  # total cost of this agent run
```

This is identical to the approach in `langgraph.py` (`_attribute_spend`) and `crewai.py` (`_attribute_execution_spend`).

### Attribution to ComponentBudget

```python
def _attribute_spend(agent_name: str, active: Any, spend_before: float) -> None:
    cb = _find_agent_cap(agent_name, active)
    if cb is not None:
        delta = active._spent - spend_before
        if delta > 0:
            cb._spent += delta
```

`ComponentBudget._spent` accumulates across multiple `Runner.run` calls for the same agent name within the same budget context.

### No double-counting

`active._spent` is the global accumulator. `ComponentBudget._spent` is a separate per-agent accumulator. The global spend is not modified by the attribution step — only `cb._spent` is updated. This is the same design as LangGraph nodes and CrewAI agents.

### Exception path

If the agent raises during execution, `openai.py` has still incremented `active._spent` for any LLM calls that completed before the exception. The `except` block in the patched wrapper calls `_attribute_spend` before re-raising, ensuring `ComponentBudget._spent` accurately reflects partial spend.

---

## 6. Public API Additions

No new public symbols. The adapter activates automatically. The user-facing API remains:

```python
b.agent("name", max_usd=X)   # existing Budget method, unchanged
```

`AgentBudgetExceededError` is already exported from `shekel.__init__`. No `__all__` changes needed.

No new kwargs on `budget()`. No new exceptions.

---

## 7. Exception Behavior

### `AgentBudgetExceededError` (reused from `shekel/exceptions.py`)

Raised in `_gate()` when either condition is met:

**Condition 1 — agent cap exhausted:**
```python
cb = _find_agent_cap(agent_name, active)
if cb is not None and cb._spent >= cb.max_usd:
    raise AgentBudgetExceededError(
        agent_name=agent_name,
        spent=cb._spent,
        limit=cb.max_usd,
    )
```

**Condition 2 — parent budget exhausted:**
```python
if active._effective_limit is not None and active._spent >= active._effective_limit:
    raise AgentBudgetExceededError(
        agent_name=agent_name,
        spent=active._spent,
        limit=active._effective_limit,
    )
```

Condition 1 is checked first (more specific cap takes priority), then Condition 2 (parent budget). This mirrors the priority ordering in `crewai.py` (`_gate_execution`).

### When `agent_name` is empty or None

`_gate` is a no-op for empty `agent_name`. The run proceeds. Condition 2 (parent budget check) can still fire by naming the agent with whatever string `getattr(agent, "name", None) or ""` resolves to — but since the name is empty, no `ComponentBudget` will be found for Condition 1. The parent budget check still fires using the empty string agent name in the error.

Design decision: use the empty agent name in the error message as-is. This is preferable to silently skipping the parent budget check entirely when the agent has no name.

### No new exceptions

`AgentBudgetExceededError` already has `agent_name`, `spent`, and `limit` attributes that fully describe an Agents SDK runner failure. No new exception class is needed.

---

## 8. `_runtime.py` Change

The only change to `_runtime.py` is adding the new adapter to `_register_builtin_adapters()`:

```python
def _register_builtin_adapters() -> None:
    from shekel.providers.crewai import CrewAIExecutionAdapter
    from shekel.providers.langchain import LangChainRunnerAdapter
    from shekel.providers.langgraph import LangGraphAdapter
    from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter  # new

    ShekelRuntime.register(LangGraphAdapter)
    ShekelRuntime.register(LangChainRunnerAdapter)
    ShekelRuntime.register(CrewAIExecutionAdapter)
    ShekelRuntime.register(OpenAIAgentsRunnerAdapter)  # new
```

---

## 9. Test Strategy

### File: `tests/test_openai_agents_wrappers.py`

Following CLAUDE.md: test file named after the domain (`openai_agents_wrappers`), not the module under test or the coverage motivation.

### Test infrastructure: fake `agents` module injection

The real `openai-agents` package is not a test dependency (may not be installed in CI). Tests inject a fake `agents` module into `sys.modules`, matching the pattern used in `test_crewai_wrappers.py`.

```python
def _make_agents_modules(simulated_cost: float = 0.0) -> tuple[types.ModuleType, type]:
    """Inject fake agents.Runner into sys.modules. Returns (module, Runner class)."""
    fake_agents = types.ModuleType("agents")

    class FakeRunner:
        @classmethod
        async def run(cls, agent, input, **kwargs):
            _simulate_cost(simulated_cost)
            return FakeRunResult()

        @classmethod
        def run_sync(cls, agent, input, **kwargs):
            _simulate_cost(simulated_cost)
            return FakeRunResult()

        @classmethod
        async def run_streamed(cls, agent, input, **kwargs):
            _simulate_cost(simulated_cost)
            yield FakeStreamEvent()

    fake_agents.Runner = FakeRunner
    sys.modules["agents"] = fake_agents
    return fake_agents, FakeRunner
```

`_simulate_cost` directly increments `get_active_budget()._spent` to simulate the effect of `openai.py` tracking a real API call.

A `FakeAgent` class with a configurable `name` attribute is used as the agent argument.

### Autouse fixture

```python
@pytest.fixture(autouse=True)
def restore_adapter_state():
    """Restore patch state and ShekelRuntime registry after each test."""
    original_refcount = openai_agents_runner_mod._patch_refcount
    original_run = openai_agents_runner_mod._original_run
    original_run_sync = openai_agents_runner_mod._original_run_sync
    original_run_streamed = openai_agents_runner_mod._original_run_streamed
    original_registry = ShekelRuntime._adapter_registry[:]

    yield

    openai_agents_runner_mod._patch_refcount = original_refcount
    openai_agents_runner_mod._original_run = original_run
    openai_agents_runner_mod._original_run_sync = original_run_sync
    openai_agents_runner_mod._original_run_streamed = original_run_streamed
    ShekelRuntime._adapter_registry = original_registry
    # Clean up injected fake modules
    for key in ["agents"]:
        sys.modules.pop(key, None)
```

### Test groups and scenarios

**Group 1: Registration**
- `OpenAIAgentsRunnerAdapter` is in `ShekelRuntime._adapter_registry` at import time
- Adapter instance has `install_patches` and `remove_patches` methods

**Group 2: Patch lifecycle**
- `install_patches` raises `ImportError` when `agents` is not in `sys.modules` (verifying ShekelRuntime will skip it)
- After `install_patches(budget)`, `Runner.run` is no longer the original classmethod
- After `remove_patches(budget)`, `Runner.run` is restored to the original
- Ref-count: two nested budgets → `_patch_refcount == 2` after both enter; inner exit leaves count at 1, not restored; outer exit restores
- `install_patches` is idempotent: calling it twice with count > 1 does not double-wrap

**Group 3: Gate — no cap registered**
- `Runner.run` inside `budget(max_usd=1.00)` with no `b.agent(...)` → runs freely
- `Runner.run_sync` inside `budget()` → runs freely
- `Runner.run` outside any `budget()` context → original behavior, no error

**Group 4: Gate — parent budget exhausted**
- `active._spent >= active._effective_limit` before `Runner.run` → raises `AgentBudgetExceededError`
- `agent_name` from error matches `agent.name`
- `error.spent` matches `active._spent`, `error.limit` matches `active._effective_limit`

**Group 5: Gate — agent cap exhausted**
- `b.agent("researcher", max_usd=0.10)` → `ComponentBudget._spent >= 0.10` → raises `AgentBudgetExceededError` before second run
- `error.agent_name == "researcher"`
- Agent with different name is not blocked by the cap

**Group 6: Spend attribution — async `Runner.run`**
- Single run with `simulated_cost=0.05`, `b.agent("researcher", max_usd=1.00)` → after run, `ComponentBudget._spent == 0.05`
- Two sequential runs with same agent → `ComponentBudget._spent == 0.10`
- Run with unregistered agent name → `b.spent` reflects cost, no `ComponentBudget` created

**Group 7: Spend attribution — sync `Runner.run_sync`**
- Same scenarios as Group 6, using `Runner.run_sync`

**Group 8: Spend attribution — `Runner.run_streamed`**
- After fully consuming the stream, `ComponentBudget._spent` reflects the simulated cost
- Partial iteration (break early) → partial or zero attribution (documents limitation)

**Group 9: Exception path**
- Agent raises `RuntimeError` during `Runner.run` → `ComponentBudget._spent` reflects partial cost accrued before exception; `RuntimeError` re-raised
- Agent raises `AgentBudgetExceededError` from parent budget exhaustion mid-run → re-raised unchanged

**Group 10: Agent name edge cases**
- `agent.name` is `None` → no cap lookup; parent budget gate still applied
- `agent.name` is `""` → same as `None`
- `agent.name` does not match any registered cap → run freely under parent budget

**Group 11: Nested budgets**
- Parent has $0.10 remaining, child registers `b.agent("x", max_usd=0.50)` → effective ceiling is $0.10 from parent; error raised when parent exhausted
- `_find_agent_cap` walks up to parent: child budget has no cap, parent budget has cap → parent cap is respected

**Group 12: Silent skip**
- Remove `agents` from `sys.modules`, open a `budget()` context → no `ImportError`, budget opens normally, `_patch_refcount == 0`

---

## 10. Edge Cases and Failure Modes

| Scenario | Handling |
|----------|---------|
| `agents.Runner` renamed or restructured in a future SDK version | `AttributeError` caught in `install_patches`; adapter silently skips (same as `except (ImportError, AttributeError, TypeError)` pattern used in `crewai.py` and `langchain.py`) |
| `Runner.run` called concurrently from two asyncio tasks sharing a budget | `get_active_budget()` uses `contextvars.ContextVar` — each task has its own context; no cross-contamination unless tasks explicitly share a budget object (which is already documented as not thread-safe) |
| `budget.warn_only=True` | Gate checks still occur; `AgentBudgetExceededError` is still raised (consistent with existing behavior — `warn_only` applies to the `BudgetExceededError` from `openai.py`, not to component gates) |
| Agent runs inside a `budget()` context that has no `max_usd` (track-only) | Condition 2 in `_gate` (`active._effective_limit is not None`) evaluates False → no gate on parent budget; agent-specific caps (Condition 1) still enforced if registered |
| `openai-agents` installed but `agents.Runner` is not a class (future API break) | `AttributeError` on attribute assignment caught by `except (ImportError, AttributeError, TypeError)` in `install_patches` |
| `remove_patches` called when `_patch_refcount == 0` | Guard at top of `remove_patches`: `if _patch_refcount <= 0: return` (mirrors `LangGraphAdapter`) |
| `_original_run` is `None` when `remove_patches` tries to restore | Guard: `if _original_run is None: return` — defensive null check, same as `crewai.py` |
| `run_streamed` stream raises before yielding any events | `except` block calls `_attribute_spend` then re-raises; partial spend (zero in this case) attributed correctly |
| `RunResultStreaming` methods accessed without iterating (e.g. `.final_output`, `.last_response_id`) | **Known gap / documented limitation.** The wrapper only attributes spend after the iteration path is exhausted. If a consumer calls `.final_output` directly on the `RunResultStreaming` object without iterating, the wrapper's post-iteration `_attribute_spend` never runs. Spend is still tracked globally by `openai.py`; only `ComponentBudget._spent` is affected (will undercount). Mitigation: document this in the adapter docstring and in the `run_streamed` edge case note in the PRD. A future release may wrap `RunResultStreaming` more completely. |

---

## 11. Design Decisions and Rationale

**Why a new file (`openai_agents_runner.py`) rather than extending `openai_agents.py`?**

The existing `openai_agents.py` patches `FunctionTool.on_invoke_tool` for tool-call budgets. It does not use ref-counting and is not registered with `ShekelRuntime`. Merging runner-level patching into that file would entangle two orthogonal concerns, make the ref-count logic harder to follow, and require modifications to a file that is stable and fully tested. A separate file follows the existing pattern (one file per adapter concern) and avoids risk.

**Why reuse `AgentBudgetExceededError` rather than creating `RunnerBudgetExceededError`?**

`AgentBudgetExceededError` already carries `agent_name`, `spent`, and `limit`. The semantics are identical — an agent (referenced by `agent.name`) exceeded its budget. Creating a new exception class would fragment the exception hierarchy without adding information. `AgentBudgetExceededError` is already exported from `shekel.__init__`.

**Why attribute spend on exception rather than skipping attribution?**

If an agent raises mid-run, real token spend has already occurred and been recorded by `openai.py`. Skipping attribution on exception would cause `ComponentBudget._spent` to undercount, potentially allowing a subsequent run to bypass a cap that should have fired. The catch-attribute-reraise pattern ensures correctness.

**Why check the parent budget condition in `_gate` rather than relying on `openai.py` to raise `BudgetExceededError`?**

The parent budget check in `_gate` is a pre-execution guard: it fires *before* the agent makes any API calls. `openai.py` fires mid-execution, after at least one API call has been made. The pre-check is cheaper (no API round-trip) and produces a cleaner error (`AgentBudgetExceededError` with agent context vs. `BudgetExceededError` with model context).
