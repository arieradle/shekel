# Implementation Plan — shekel v1.1.0

**Features:** OpenAI Agents SDK adapter · Loop Guard · Spend Velocity
**Branch:** `feat/v1.1.0`
**TDD required.** Write tests first, then implementation. 100% coverage before PR.

---

## Dependency Map

```
Phase 0  ──────────────────────────────────────────────────── (sequential, ~30 min)
  exceptions.py + __init__.py  ← prerequisite for everything

Phase 1a ──────────────────────────────────────────────────── (2 agents in parallel)
  Agent A: Loop Guard       → _budget.py + call sites + tests
  Agent C: OAI SDK Adapter  → new provider file + _runtime.py + tests
                             ↕ no file overlap with Agent A

Phase 1b ──────────────────────────────────────────────────── (after Agent A completes)
  Agent B: Spend Velocity   → _budget.py + tests
                             ↑ must wait: shares _budget.py __init__ + _reset_state

Phase 2  ──────────────────────────────────────────────────── (after all agents done)
  Full test suite + linters + coverage verification
```

**Why the sequencing:** Loop Guard (Agent A) and Spend Velocity (Agent B) both modify
`Budget.__init__`, `_reset_state`, and `_budget.py` imports. Running them concurrently
causes merge conflicts. Agent C (SDK adapter) touches only a new file and `_runtime.py` —
no overlap with A or B.

---

## Phase 0 — Shared Foundations

**Who:** main conversation (do before launching agents)
**Time:** ~30 min
**Files:** `shekel/exceptions.py`, `shekel/__init__.py`

### Step 0.1 — `shekel/exceptions.py`

Append after the existing `SessionBudgetExceededError` class:

**`AgentLoopError`** — subclasses `BudgetExceededError`:
- `__init__(self, tool_name: str, repeat_count: int, window_seconds: float, spent: float)`
- Sets `self.tool_name`, `self.repeat_count`, `self.window_seconds`
- Calls `super().__init__(spent=spent, limit=spent, model=f"loop:{tool_name}")`
- `__str__` shows tool name, repeat_count, window, spent, and a tuning tip
- See `tech-design-loop-guard.md` Section 4 for full class body

**`SpendVelocityExceededError`** — subclasses `BudgetExceededError`:
- `__init__(self, spent_in_window: float, limit_usd: float, window_seconds: float, model: str, tokens: dict)`
- Sets `self.spent_in_window`, `self.limit_usd`, `self.window_seconds`
- Computes `self.velocity_per_min = (spent_in_window / window_seconds) * 60.0`
- Computes `self.limit_per_min = (limit_usd / window_seconds) * 60.0`
- Calls `super().__init__(spent=spent_in_window, limit=limit_usd, model=model, tokens=tokens)`
- `__str__` shows window sum, limit, normalized rate, last model, and a tip
- See `tech-design-spend-velocity.md` Section 6 for full class body

### Step 0.2 — `shekel/__init__.py`

Add to the import block and `__all__`:
```python
from shekel.exceptions import AgentLoopError, SpendVelocityExceededError
```
Add `"AgentLoopError"` and `"SpendVelocityExceededError"` to `__all__`.

### Step 0.3 — Write tests first (TDD)

Before any `_budget.py` changes, confirm the exceptions are importable and have correct
inheritance and fields. Minimal test in a scratch file or directly in the test files that
agents will expand. Do not write full test suites here — agents own those.

### Step 0.4 — Verify

```bash
python -c "from shekel import AgentLoopError, SpendVelocityExceededError; print('ok')"
pytest tests/ -x -q  # existing tests must still pass
```

---

## Phase 1a — Parallel (launch both agents simultaneously after Phase 0)

---

### Agent A — Loop Guard

**Files owned exclusively:**
- `shekel/_budget.py` — loop guard additions only (not velocity section)
- `shekel/_tool.py`
- `shekel/providers/langchain.py`
- `shekel/providers/mcp.py`
- `shekel/providers/crewai.py`
- `shekel/providers/openai_agents.py`
- `tests/test_loop_guard.py` (new)

**DO NOT TOUCH:** `shekel/_runtime.py`, `shekel/providers/openai_agents_runner.py`, velocity code

---

#### A.1 — `shekel/_budget.py` — `__init__` additions

Add to the import block at top of file:
```python
import warnings
from collections import deque
```
(`deque` may already be imported — check first. `warnings` may already be imported — check first.)

Add new parameters to `Budget.__init__` signature (after `warn_only`):
```python
loop_guard: bool = False,
loop_guard_max_calls: int = 5,
loop_guard_window_seconds: float = 60.0,
```

Add validation block in `__init__` after existing validation:
```python
if loop_guard_max_calls <= 0:
    raise ValueError(
        f"loop_guard_max_calls must be a positive integer, got {loop_guard_max_calls}"
    )
if loop_guard_window_seconds < 0:
    raise ValueError(
        f"loop_guard_window_seconds must be >= 0 (0 = all-time), "
        f"got {loop_guard_window_seconds}"
    )
```

Add instance attributes in `__init__` (in the tool tracking block):
```python
# Loop guard (v1.1.0)
self.loop_guard: bool = loop_guard
self.loop_guard_max_calls: int = loop_guard_max_calls
self.loop_guard_window_seconds: float = loop_guard_window_seconds
self._loop_guard_windows: dict[str, deque[float]] = {}
```

#### A.2 — `shekel/_budget.py` — `_reset_state`

Add to `_reset_state()` (alongside existing `_tool_calls` reset):
```python
self._loop_guard_windows = {}
```

#### A.3 — `shekel/_budget.py` — new method `_check_loop_guard`

Insert as a new method near `_check_tool_limit`. Full pseudocode in
`tech-design-loop-guard.md` Section 3. Key points:
- Early return if `not self.loop_guard`
- Get/create deque with `maxlen=self.loop_guard_max_calls + 1`
- Evict entries older than `loop_guard_window_seconds` (skip eviction if window is 0)
- If `len(window) >= self.loop_guard_max_calls`:
  - If `self.warn_only`: `warnings.warn(...)` then `return`
  - Else: `raise AgentLoopError(tool_name, len(window), self.loop_guard_window_seconds, self._spent)`

#### A.4 — `shekel/_budget.py` — modify `_record_tool_call`

At the top of `_record_tool_call`, before existing logic, add:
```python
if self.loop_guard:
    self._loop_guard_windows.setdefault(
        tool_name, deque(maxlen=self.loop_guard_max_calls + 1)
    ).append(time.monotonic())
```
`time` must be imported at module level (check if already imported).

#### A.5 — `shekel/_budget.py` — new property `loop_guard_counts`

Add read-only property as specified in `tech-design-loop-guard.md` Section 7.
Returns `dict[str, int]` — live per-tool call counts within the current window.
Returns `{}` when `loop_guard=False`.

#### A.6 — All tool dispatch call sites

In each file below, find every block that calls `_check_tool_limit` and insert
`_check_loop_guard` immediately before it. Pattern to find:
```python
active._check_tool_limit(tool_name, "framework")
```
Becomes:
```python
active._check_loop_guard(tool_name, "framework")   # loop guard gate (v1.1.0)
active._check_tool_limit(tool_name, "framework")
```

**Files and line numbers (from grep):**
- `shekel/_tool.py` lines 34, 55, 76 (all 3 sync/async variants, framework=`"manual"`)
- `shekel/providers/langchain.py` lines 50, 61 (framework=`"langchain"`)
- `shekel/providers/mcp.py` line 36 (framework=`"mcp"`)
- `shekel/providers/crewai.py` lines 41, 52 (framework=`"crewai"`)
- `shekel/providers/openai_agents.py` line 37 (framework=`"openai-agents"`)

Total: 9 call sites. Apply the same two-line pattern to each.

#### A.7 — Tests: `tests/test_loop_guard.py`

Write tests first (TDD). Full test structure in `tech-design-loop-guard.md` Section 10.

Required test classes:
```
TestLoopGuardBaseline         — loop_guard=False does nothing; no windows allocated
TestLoopGuardThresholds       — fires on call N+1, not N; custom max_calls
TestLoopGuardWindowExpiry     — window slides; calls expire and count resets
TestAgentLoopErrorFields      — tool_name, repeat_count, window_seconds, spent, isinstance
TestLoopGuardWarnOnly         — warnings.warn called, no raise, execution continues
TestLoopGuardMultiTool        — tool A loops, tool B unaffected
TestLoopGuardWithMaxToolCalls — both independent; loop guard fires first
TestLoopGuardReset            — b.reset() clears windows
TestLoopGuardValidation       — ValueError on max_calls=0, window_seconds=-1
TestLoopGuardCounts           — loop_guard_counts property: empty when off, correct counts
TestLoopGuardIntegration      — fires via @tool decorator; fires via mocked call site
```

Use `monkeypatch` on `time.monotonic` for deterministic window expiry tests.

#### A.8 — Verify Agent A

```bash
pytest tests/test_loop_guard.py -v
pytest --cov=shekel --cov-report=term-missing
python -m black shekel/_budget.py shekel/_tool.py shekel/providers/langchain.py \
    shekel/providers/mcp.py shekel/providers/crewai.py shekel/providers/openai_agents.py \
    tests/test_loop_guard.py
python -m isort shekel/_budget.py tests/test_loop_guard.py
python -m ruff check shekel/_budget.py tests/test_loop_guard.py
python -m mypy shekel/_budget.py
```

---

### Agent C — OpenAI Agents SDK Runner Adapter

**Files owned exclusively:**
- `shekel/providers/openai_agents_runner.py` (new file)
- `shekel/_runtime.py`
- `tests/test_openai_agents_wrappers.py` (new file — check if exists first; if so, append)

**DO NOT TOUCH:** `shekel/_budget.py`, `shekel/providers/openai_agents.py` (tool budgets, separate concern)

---

#### C.1 — `shekel/providers/openai_agents_runner.py` (new file)

Module-level state:
```python
_patch_refcount: int = 0
_original_run: Any = None
_original_run_sync: Any = None
_original_run_streamed: Any = None
```

Helper functions:
- `_find_agent_cap(agent_name, active)` — walks parent chain, returns `ComponentBudget | None`
  (copy pattern from `shekel/providers/crewai.py::_find_agent_cap`)
- `_gate(agent_name, active)` — pre-run check:
  1. Check `ComponentBudget._spent >= max_usd` → raise `AgentBudgetExceededError`
  2. Check `active._spent >= active._effective_limit` → raise `AgentBudgetExceededError`
  No-op when `agent_name` is falsy.
- `_attribute_spend(agent_name, active, spend_before)` — post-run:
  delta = `active._spent - spend_before`; if `cb` found and delta > 0: `cb._spent += delta`

`OpenAIAgentsRunnerAdapter` class:
- `install_patches(budget)`: increment refcount; if refcount == 1: store originals, monkey-patch
  `Runner.run`, `Runner.run_sync`, `Runner.run_streamed`. Wrap in `try/except (ImportError, AttributeError, TypeError)` — silently skip.
- `remove_patches(budget)`: decrement refcount; if refcount == 0: restore originals, zero globals.
  Guard: `if _patch_refcount <= 0: return`. Guard: `if _original_run is None: return`.

Patched wrappers (see `tech-design-openai-agents-sdk.md` Section 4 for exact pseudocode):

`_patched_run(cls, agent, input, **kwargs)` — async:
1. `active = get_active_budget()` → if None, call original and return
2. `agent_name = getattr(agent, "name", None) or ""`
3. `_gate(agent_name, active)` — may raise
4. `spend_before = active._spent`
5. try: `result = await _original_run(agent, input, **kwargs)`; except: `_attribute_spend(...)`; raise
6. `_attribute_spend(agent_name, active, spend_before)`; return result

`_patched_run_sync(cls, agent, input, **kwargs)` — sync, same structure without await.

`_patched_run_streamed(cls, agent, input, **kwargs)` — async generator wrapper:
1. `_gate(...)` before calling original
2. Capture `spend_before`
3. Return async generator that iterates original stream, calls `_attribute_spend` after exhaustion or on exception
4. **Document as known limitation:** if caller accesses `.final_output` without iterating,
   attribution does not fire. Add docstring note.

#### C.2 — `shekel/_runtime.py`

Find `_register_builtin_adapters()`. Add:
```python
from shekel.providers.openai_agents_runner import OpenAIAgentsRunnerAdapter
ShekelRuntime.register(OpenAIAgentsRunnerAdapter)
```
alongside the existing `LangGraphAdapter`, `LangChainRunnerAdapter`, `CrewAIExecutionAdapter` registrations.

#### C.3 — Tests: `tests/test_openai_agents_wrappers.py`

Write tests first (TDD). Full structure in `tech-design-openai-agents-sdk.md` Section 9.

Fake module injection pattern:
```python
def _make_agents_modules(simulated_cost: float = 0.0):
    fake_agents = types.ModuleType("agents")
    class FakeRunner: ...   # classmethods run/run_sync/run_streamed
    class FakeAgent:
        def __init__(self, name): self.name = name
    fake_agents.Runner = FakeRunner
    sys.modules["agents"] = fake_agents
    return fake_agents, FakeRunner, FakeAgent
```

`_simulate_cost(cost)` increments `get_active_budget()._spent` directly.

Autouse fixture restores: `_patch_refcount`, `_original_run/sync/streamed`, `ShekelRuntime._adapter_registry`, cleans `sys.modules["agents"]`.

Required test groups (12):
```
TestRegistration             — adapter in registry at import
TestPatchLifecycle           — install/remove/refcount
TestGateNoCapRegistered      — runs freely, no b.agent()
TestGateParentExhausted      — raises AgentBudgetExceededError
TestGateAgentCapExhausted    — per-agent cap fires
TestSpendAttributionRun      — async Runner.run delta → ComponentBudget._spent
TestSpendAttributionRunSync  — sync Runner.run_sync same
TestSpendAttributionStreamed — full iteration attributes correctly
TestExceptionPath            — partial spend attributed before re-raise
TestAgentNameEdgeCases       — None/empty name behavior
TestNestedBudgets            — parent ceiling respected
TestSilentSkip               — no agents in sys.modules → no error on budget open
```

#### C.4 — Verify Agent C

```bash
pytest tests/test_openai_agents_wrappers.py -v
python -m black shekel/providers/openai_agents_runner.py tests/test_openai_agents_wrappers.py
python -m isort shekel/providers/openai_agents_runner.py tests/test_openai_agents_wrappers.py
python -m ruff check shekel/providers/openai_agents_runner.py
python -m mypy shekel/providers/openai_agents_runner.py shekel/_runtime.py
```

---

## Phase 1b — Spend Velocity (after Agent A completes)

**Wait for:** Agent A to merge its `_budget.py` changes before starting.
**Why:** Both add to `Budget.__init__` signature and `_reset_state`. Running simultaneously
causes merge conflicts on those two methods.

**Files owned exclusively:**
- `shekel/_budget.py` — velocity additions only (loop guard already there from Agent A)
- `tests/test_spend_velocity.py` (new)

---

#### B.1 — `shekel/_budget.py` — module-level additions

Add `import re` if not already present.

Add module-level constants (outside any class, near top of file):
```python
_VELOCITY_RE = re.compile(
    r"^\s*\$(?P<amount>[\d.]+)\s*/\s*(?P<count>[\d.]*)\s*(?P<unit>sec|min|hr|h|m|s)\b\s*$",
    re.IGNORECASE,
)
_VELOCITY_UNIT_SECONDS: dict[str, float] = {
    "s": 1.0, "sec": 1.0, "min": 60.0, "m": 60.0, "hr": 3600.0, "h": 3600.0,
}
```

Add module-level pure function `_parse_velocity_spec(spec: str) -> tuple[float, float]`.
Full implementation in `tech-design-spend-velocity.md` Section 2.

#### B.2 — `shekel/_budget.py` — `__init__` additions

Add new parameters after `warn_only` (AFTER the loop_guard params Agent A added):
```python
max_velocity: str | None = None,
warn_velocity: str | None = None,
```

Add validation in `__init__` after loop guard validation:
```python
# Velocity spec parsing (v1.1.0)
self._velocity_limit_usd: float | None = None
self._velocity_window_seconds: float = 0.0
if max_velocity is not None:
    self._velocity_limit_usd, self._velocity_window_seconds = _parse_velocity_spec(max_velocity)

self._warn_velocity_limit_usd: float | None = None
self._warn_velocity_window_seconds: float = 0.0
if warn_velocity is not None:
    self._warn_velocity_limit_usd, self._warn_velocity_window_seconds = _parse_velocity_spec(warn_velocity)

# Cross-field validation
if warn_velocity is not None and max_velocity is None:
    raise ValueError("warn_velocity requires max_velocity to be set")
if (self._warn_velocity_limit_usd is not None
        and self._velocity_limit_usd is not None
        and self._warn_velocity_limit_usd >= self._velocity_limit_usd):
    raise ValueError(
        f"warn_velocity limit must be less than max_velocity limit"
    )

# Velocity runtime state
self._velocity_window: deque[tuple[float, float]] = deque()
self._velocity_warn_fired: bool = False
```

Note: `deque` is already imported from Agent A's changes.

Block `TemporalBudget` from using velocity (add check in `TemporalBudget.__init__`):
```python
if max_velocity is not None or warn_velocity is not None:
    raise ValueError(
        "max_velocity/warn_velocity cannot be used with TemporalBudget. "
        "Use the temporal spec string instead: budget('$5/hr', name='...')"
    )
```

#### B.3 — `shekel/_budget.py` — `_reset_state`

Add to `_reset_state()` (after Agent A's loop_guard reset):
```python
self._velocity_window.clear()
self._velocity_warn_fired = False
```

#### B.4 — `shekel/_budget.py` — new velocity methods

Add these methods (see `tech-design-spend-velocity.md` Sections 3–4 for full bodies):

- `_prune_velocity_window(self, now: float) -> None` — evict entries older than window
- `_append_velocity_entry(self, cost: float) -> None` — prune then append `(now, cost)`
- `_velocity_window_sum` — property, returns `sum(d for _, d in self._velocity_window)`
- `_check_velocity_warn(self) -> None` — fires `on_warn` once when sum >= warn limit;
  resets `_velocity_warn_fired` when deque is emptied by pruning
- `_check_velocity_limit(self) -> None` — raises `SpendVelocityExceededError` (or warns
  if `warn_only`) when sum > limit

#### B.5 — `shekel/_budget.py` — modify `_record_spend`

In the existing `_record_spend` method, after incrementing `_calls_made` and before
`_check_warn()`, insert:
```python
# Velocity tracking (v1.1.0)
if self._velocity_limit_usd is not None or self._warn_velocity_limit_usd is not None:
    self._append_velocity_entry(cost)
    self._check_velocity_warn()
    self._check_velocity_limit()
```

Do NOT add a `maxlen` to `_velocity_window` — see `tech-design-spend-velocity.md` Section 11.

#### B.6 — Tests: `tests/test_spend_velocity.py`

Write tests first (TDD). Full scenario list in `tech-design-spend-velocity.md` Section 10.
27 specific test scenarios. Use `monkeypatch` on `time.monotonic` for deterministic windows.

Key patterns:
```python
# Simulate time passing without sleeping:
times = iter([0.0, 10.0, 10.5, 75.0])
monkeypatch.setattr("time.monotonic", lambda: next(times))
```

Required coverage:
- Parser: all valid formats + all error formats
- Velocity raise: under limit, over limit, window rollover
- Velocity warn: fires once, resets, fires again next window
- warn_only: no raise, callback fires
- Combined with max_usd: velocity fires first on fast burn
- Exception fields: all attributes correct, isinstance BudgetExceededError
- Construction validation: warn_velocity without max_velocity, warn >= max
- Reset: clears window and warn flag
- Async path: async `with budget(max_velocity=...)` works
- Nested: child velocity independent; parent gets single entry on child exit
- Track-only (no max_usd): velocity-only guard works

#### B.7 — Verify Agent B

```bash
pytest tests/test_spend_velocity.py -v
pytest --cov=shekel --cov-report=term-missing
python -m black shekel/_budget.py tests/test_spend_velocity.py
python -m isort shekel/_budget.py tests/test_spend_velocity.py
python -m ruff check shekel/_budget.py tests/test_spend_velocity.py
python -m mypy shekel/_budget.py
```

---

## Phase 1c — Docs + Examples (parallel with Phase 1b, Agent D)

**Start:** immediately after Phase 0 completes (does not touch code).
**No file overlap** with Agents A, B, or C.

**Files owned exclusively:**
- `docs/integrations/openai-agents.md` (new)
- `docs/usage/loop-guard.md` (new)
- `docs/usage/spend-velocity.md` (new)
- `docs/usage/openai_agents_demo.py` (new)
- `docs/usage/loop_guard_demo.py` (new)
- `docs/usage/spend_velocity_demo.py` (new)
- `docs/index.md` — add 3 What's New cards
- `docs/api-reference.md` — add new params + exceptions
- `docs/changelog.md` — add [1.1.0] entry
- `README.md` — targeted additions only (keep current tone/structure)

---

### D.1 — `docs/integrations/openai-agents.md` (new)

Model after `docs/integrations/crewai.md` in structure. Sections:

1. **Overview** — one paragraph: what the adapter does, zero-config activation
2. **Installation** — `pip install shekel openai-agents`
3. **Zero-config global enforcement** — single `budget()` wrapping `Runner.run`
4. **Per-agent caps** — `b.agent("researcher", max_usd=0.30)` + `AgentBudgetExceededError`
5. **Multi-agent pipeline** — example with 2+ agents each with their own cap
6. **Spend attribution with `b.tree()`** — show output
7. **Async and sync** — `Runner.run` (async) and `Runner.run_sync` (sync) examples
8. **Streaming** — `Runner.run_streamed` example with known-limitation callout
9. **Exception reference** — `AgentBudgetExceededError` fields table
10. **warn_only mode** — staging/dev use case
11. **Nested budgets** — parent ceiling behavior

### D.2 — `docs/usage/loop-guard.md` (new)

Sections:
1. **The problem** — overnight loop scenario, why `max_usd` alone isn't enough
2. **Quick start** — `budget(max_usd=5.00, loop_guard=True)`
3. **How it works** — rolling window, per-tool tracking, pre-dispatch gate
4. **Tuning thresholds** — `loop_guard_max_calls`, `loop_guard_window_seconds`
5. **Reading the exception** — `AgentLoopError` fields, example traceback
6. **warn_only mode** — observe without blocking
7. **Combining with max_tool_calls** — independent, both enforced
8. **Inspecting live counts** — `b.loop_guard_counts`
9. **Edge cases** — legitimate high-frequency tools (tune thresholds), session mode, nested budgets
10. **Framework coverage** — works with `@tool`, LangChain, MCP, CrewAI, OpenAI Agents

### D.3 — `docs/usage/spend-velocity.md` (new)

Sections:
1. **The problem** — fast burn vs slow burn, why total cap isn't enough
2. **Quick start** — `budget(max_velocity="$0.50/min")`
3. **Spec format** — `$<amount>/<count><unit>` table with all supported units
4. **Velocity-only guard** (no `max_usd`) — US-6 use case
5. **Compound guardrails** — `max_usd` + `max_velocity` together
6. **Velocity warning** — `warn_velocity` before hard stop
7. **warn_only mode** — dev/staging observability
8. **Reading the exception** — `SpendVelocityExceededError` fields, normalized `velocity_per_min`
9. **Nested budgets** — child tracks call-by-call; parent receives delta on exit
10. **What it doesn't cover** — TemporalBudget interaction, distributed velocity

### D.4 — Example files

**`docs/usage/openai_agents_demo.py`**
- Complete runnable example: 2 agents (researcher + writer), each with a cap
- Shows `b.agent()`, `Runner.run`, `b.tree()`, catches `AgentBudgetExceededError`
- Mock OpenAI client so it runs without API key (same pattern as `langchain_demo.py`)

**`docs/usage/loop_guard_demo.py`**
- Simulates a tool that gets stuck in a loop (returns same result repeatedly)
- Shows `loop_guard=True` detecting and stopping it
- Demonstrates `warn_only=True` variant with logging
- Shows `b.loop_guard_counts` after a run

**`docs/usage/spend_velocity_demo.py`**
- Simulates bursty LLM usage with `time.sleep` between calls
- Shows velocity guard firing, velocity warning firing first
- Shows velocity-only mode (no `max_usd`)
- Shows compound: `max_usd=50.00, max_velocity="$1/min"`

### D.5 — `docs/index.md` — What's New cards

Add 3 new cards to the existing `What's New in v1.1.0` grid
(change header from `v1.0.2` to `v1.1.0`, keep existing cards, prepend new ones):

```
Card 1: OpenAI Agents SDK — Per-Agent Circuit Breaking
  icon: robot, link: integrations/openai-agents.md

Card 2: Loop Guard — Agent Loop Detection
  icon: shield, link: usage/loop-guard.md

Card 3: Spend Velocity — Burn-Rate Circuit Breaker
  icon: zap, link: usage/spend-velocity.md
```

### D.6 — `docs/api-reference.md`

Add to Budget constructor params table:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `loop_guard` | `bool` | `False` | Enable per-tool rolling-window loop detection |
| `loop_guard_max_calls` | `int` | `5` | Max calls to the same tool within the window before `AgentLoopError` |
| `loop_guard_window_seconds` | `float` | `60.0` | Rolling window duration in seconds (0 = all-time) |
| `max_velocity` | `str \| None` | `None` | Spend velocity cap, e.g. `"$0.50/min"` |
| `warn_velocity` | `str \| None` | `None` | Soft velocity warning threshold (must be < `max_velocity`) |

Add to exceptions table: `AgentLoopError`, `SpendVelocityExceededError` with fields.

Add `loop_guard_counts` property to Budget properties table.

### D.7 — `docs/changelog.md`

Add `## [1.1.0]` entry at the top (before `[1.0.2]`). Cover:
- OpenAI Agents SDK `Runner` adapter with per-agent caps and spend attribution
- `loop_guard=True` — rolling-window per-tool loop detection, `AgentLoopError`
- `max_velocity="$X/unit"` — burn-rate circuit breaker, `SpendVelocityExceededError`
- New exceptions: `AgentLoopError`, `SpendVelocityExceededError`
- New `Budget` properties: `loop_guard_counts`

### D.8 — `README.md` — Targeted additions only

**Do not restructure or rewrite.** Make these surgical insertions:

1. In the **"Works with everything"** table — add OpenAI Agents SDK row:
   `| OpenAI Agents SDK | Runner-level | AgentBudgetExceededError |`

2. In the exceptions table — add:
   `| AgentLoopError | loop_guard | Same tool > N times in window |`
   `| SpendVelocityExceededError | max_velocity | Burn rate exceeds limit |`

3. After the CrewAI section — add a short **"Loop & Velocity Protection"** section
   (4–6 lines max) showing `loop_guard=True` and `max_velocity=` on one budget.
   Keep it tight — the README is already polished.

### D.9 — Verify Agent D

```bash
mkdocs build --strict   # must pass with zero warnings
```

Check all internal links resolve. Confirm new pages appear in `mkdocs.yml` nav
(add entries if nav is explicit — check `mkdocs.yml` first).

---

## Phase 2 — Unit Test Suite + Linters

**After Agents A, B, C complete.** Agent D can still be running.

### Step 2.1 — Full unit test suite

```bash
pytest tests/ --ignore=tests/integrations --ignore=tests/performance \
    --cov=shekel --cov-report=term-missing -v
```

100% coverage required. Any uncovered line must be either covered or `# pragma: no cover`.

### Step 2.2 — Linters on all changed files

```bash
python -m black shekel/ tests/
python -m isort shekel/ tests/
python -m ruff check shekel/ tests/
python -m mypy shekel/_budget.py shekel/exceptions.py shekel/__init__.py \
    shekel/_runtime.py shekel/providers/openai_agents_runner.py
```

Fix all errors before proceeding.

### Step 2.3 — Spot-check cross-feature interaction

```python
# Loop guard + velocity + OAI SDK together
with budget(max_usd=5.00, loop_guard=True, max_velocity="$0.50/min") as b:
    b.agent("researcher", max_usd=1.00)
    result = await Runner.run(agent, "input")
    # both guards active; agent cap also enforced
```

### Step 2.4 — Bump version

In `shekel/__init__.py`: `__version__ = "1.1.0"`
In `pyproject.toml`: `version = "1.1.0"`

---

## Phase 2b — Integration + Performance Tests (parallel with Phase 2 linting, Agent E)

**Start:** after Agents A, B, C complete (needs working implementation).
**No file overlap** with Phase 2 main linting work.

**Files owned exclusively:**
- `tests/integrations/test_loop_guard_integration.py` (new)
- `tests/integrations/test_spend_velocity_integration.py` (new)
- `tests/integrations/test_openai_agents_integration.py` (new)
- `tests/performance/test_loop_guard_performance.py` (new)
- `tests/performance/test_velocity_performance.py` (new)

---

### E.1 — `tests/integrations/test_loop_guard_integration.py`

Model after `tests/integrations/test_langgraph_integration.py`. Two test groups:

**`TestLoopGuardMockIntegration`** (no API keys, always runs):
- End-to-end: `@tool` decorated function called in a loop; `loop_guard=True` fires
- End-to-end: mocked LangChain `BaseTool` in a chain; loop guard fires mid-chain
- End-to-end: mocked MCP tool; loop guard fires
- Loop guard + `max_tool_calls`: both active, loop fires first
- `warn_only` path: 10 calls, only warnings, no exception, budget context exits cleanly
- Session budget: loop guard state persists across `with` blocks; `b.reset()` clears
- `loop_guard_counts` returns accurate snapshot after mixed tool calls

**`TestLoopGuardLiveIntegration`** (requires `OPENAI_API_KEY`, skipped without):
- Real OpenAI call inside `loop_guard=True` budget; normal call completes; spend tracked
- Skip pattern: `pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="no API key")`

### E.2 — `tests/integrations/test_spend_velocity_integration.py`

**`TestSpendVelocityMockIntegration`** (always runs):
- End-to-end: mock LLM calls via `shekel/providers/openai.py` patch; velocity fires on burst
- `warn_velocity` fires before hard stop in a realistic multi-call sequence
- Velocity + `max_usd`: compound guardrails, velocity fires first on fast burn
- Velocity + nested budget: child fires independently; parent tracks delta on exit
- Track-only budget with velocity: `budget(max_velocity="$0.50/min")` — no `max_usd`
- Async path: `async with budget(max_velocity=...)` — burst of async calls triggers guard
- Window rollover: monkeypatched time; second window starts clean after first expires
- `warn_only=True` + velocity: warning fires via `warnings.warn`, no exception, run completes

**`TestSpendVelocityLiveIntegration`** (requires `OPENAI_API_KEY`):
- Real OpenAI call with `max_velocity="$5/min"` — single call completes under limit; spend tracked

### E.3 — `tests/integrations/test_openai_agents_integration.py`

**`TestOpenAIAgentsRunnerMockIntegration`** (always runs):
- End-to-end with fake `agents` module: `Runner.run` patched, spend attributed, `b.tree()` correct
- Multi-agent pipeline: 2 agents each with cap; first agent cap exhausted; second still runs
- Nested budget: child budget with agent cap; parent ceiling respected
- `Runner.run_sync` path: spend attributed correctly
- `Runner.run_streamed` path: after full iteration, spend attributed
- Agent raises mid-run: partial spend attributed; exception re-raised
- No `b.agent()` registered: runs freely, global spend tracked, no `ComponentBudget` created
- Refcount: 2 nested `budget()` contexts → single patch; inner exit → still patched; outer exit → restored
- `ShekelRuntime` probe skips gracefully when `agents` not in `sys.modules`

**`TestOpenAIAgentsRunnerLiveIntegration`** (requires `OPENAI_API_KEY` + `openai-agents` installed):
- Real `Runner.run` with a minimal agent and `budget(max_usd=0.10)` — completes or budget fires
- Per-agent cap: `b.agent("test", max_usd=0.001)` — fires before second run of same agent

### E.4 — `tests/performance/test_loop_guard_performance.py`

Model after `tests/performance/test_run_overhead.py`. Key benchmarks:

**`TestLoopGuardOverhead`**:
- `loop_guard=False` baseline: call `_check_tool_limit` N times — measure overhead per call
- `loop_guard=True` with empty window: same N calls — overhead must be < 0.5 ms per call
- `loop_guard=True` with full window (max_calls - 1 entries): eviction + check — < 1 ms per call
- Memory: `_loop_guard_windows` dict with 100 tool names × 5 entries each — < 1 MB total
- Assert: loop guard adds < 10 µs overhead per tool dispatch (use `time.perf_counter`)

```python
def test_loop_guard_overhead_per_dispatch():
    """Loop guard check adds < 10 µs per tool dispatch."""
    N = 1000
    with budget(max_usd=100.00, loop_guard=True, loop_guard_max_calls=N + 1) as b:
        # pre-fill window with N-1 entries
        for i in range(N - 1):
            b._check_loop_guard(f"tool_{i % 10}", "manual")
            b._record_tool_call(f"tool_{i % 10}", 0.0, "manual")
        t0 = time.perf_counter()
        for _ in range(100):
            b._check_loop_guard("tool_0", "manual")
        elapsed = (time.perf_counter() - t0) / 100
    assert elapsed < 10e-6, f"loop guard overhead too high: {elapsed*1e6:.1f} µs"
```

### E.5 — `tests/performance/test_velocity_performance.py`

**`TestVelocityOverhead`**:
- `max_velocity=None` baseline: call `_record_spend` N times — baseline overhead
- `max_velocity="$100/min"` active: same N calls under limit — overhead per call < 5 µs
- Deque pruning: pre-fill window with 1000 entries, trigger pruning — < 1 ms per prune pass
- Memory: `_velocity_window` deque with 10,000 entries — measure size via `sys.getsizeof`

```python
def test_velocity_overhead_per_record_spend():
    """Velocity check adds < 5 µs per _record_spend call."""
    N = 500
    with budget(max_usd=1000.00, max_velocity="$999/min") as b:
        t0 = time.perf_counter()
        for _ in range(N):
            b._record_spend(0.0001, "gpt-4o-mini", {"input": 10, "output": 5})
        elapsed = (time.perf_counter() - t0) / N
    assert elapsed < 5e-6, f"velocity overhead too high: {elapsed*1e6:.1f} µs"
```

### E.6 — Verify Agent E

```bash
# Integration tests (mock only — no API keys required for CI)
pytest tests/integrations/test_loop_guard_integration.py \
       tests/integrations/test_spend_velocity_integration.py \
       tests/integrations/test_openai_agents_integration.py -v -k "Mock"

# Performance tests
pytest tests/performance/test_loop_guard_performance.py \
       tests/performance/test_velocity_performance.py -v
```

---

## Phase 3 — Final Integration + Release

**After Phases 2 and 2b and Agent D all complete.**

### Step 3.1 — Full test suite including integrations and perf

```bash
pytest --cov=shekel --cov-report=term-missing -v
```

### Step 3.2 — Docs build

```bash
mkdocs build --strict
```

Zero warnings. All new pages in nav.

### Step 3.3 — Final linting-fix loop (repeat until all clean)

Run the full linter stack over **all changed files**. Fix any error, then re-run. Do not
proceed to Step 3.4 until every tool exits with zero errors.

```bash
# 1. Format
python -m black shekel/ tests/

# 2. Import order
python -m isort shekel/ tests/

# 3. Lint (style + correctness)
python -m ruff check shekel/ tests/

# 4. Type check (source files only — tests excluded)
python -m mypy shekel/_budget.py shekel/exceptions.py shekel/__init__.py \
    shekel/_runtime.py shekel/providers/openai_agents_runner.py \
    shekel/_tool.py shekel/providers/langchain.py shekel/providers/mcp.py \
    shekel/providers/crewai.py shekel/providers/openai_agents.py
```

**Loop:** if any command exits non-zero, fix the reported errors, then restart from step 1.
All four tools must pass in the same run before continuing.

### Step 3.4 — Update `docs/changelog.md` and `CHANGELOG.md`

Finalize the `[1.1.0]` entries with accurate test counts and any adjustments from implementation.

### Step 3.5 — Push and open PR

```bash
git push -u origin feat/v1.1.0
gh pr create --base main \
  --title "feat: v1.1.0 — OpenAI Agents SDK adapter, loop guard, spend velocity" \
  --body "..."
```

---

## Phase 4 — Security Issue Audit (after Phase 3, Agent F)

**Start:** after PR is open (or in parallel with final review).
**Who:** Agent F — security triage bot.

### What Agent F does

1. `gh issue list --label security --state open` — list all open security-labelled issues
2. `gh issue list --state open` — scan all open issues for security keywords (injection, leak, secret, token, credential, overflow, RCE, XSS, SSRF, DoS, CVE)
3. For each finding:
   - Read the issue body and comments
   - Determine if it is still relevant given the current codebase
   - **If still relevant:** attempt a fix in the code, commit, and reference the issue in the commit message
   - **If no longer relevant** (already fixed, not applicable, or out of scope): close the issue with a comment explaining why
4. After all issues processed: run `pytest tests/ -x -q` to confirm no regressions from any fixes

**Scope:** source code issues only — do not modify CI, secrets config, or infrastructure files.

---

## File Change Summary

| File | Phase | Agent | Change type |
|------|-------|-------|-------------|
| `shekel/exceptions.py` | 0 | main | Add `AgentLoopError`, `SpendVelocityExceededError` |
| `shekel/__init__.py` | 0 | main | Export 2 new exceptions; version bump (Phase 2) |
| `shekel/_budget.py` | 1a | A | Loop guard params, `_check_loop_guard`, `_record_tool_call`, `_reset_state` |
| `shekel/_tool.py` | 1a | A | `_check_loop_guard` at 3 call sites |
| `shekel/providers/langchain.py` | 1a | A | `_check_loop_guard` at 2 call sites |
| `shekel/providers/mcp.py` | 1a | A | `_check_loop_guard` at 1 call site |
| `shekel/providers/crewai.py` | 1a | A | `_check_loop_guard` at 2 call sites |
| `shekel/providers/openai_agents.py` | 1a | A | `_check_loop_guard` at 1 call site |
| `tests/test_loop_guard.py` | 1a | A | New — 11 test classes |
| `shekel/providers/openai_agents_runner.py` | 1a | C | New — full adapter |
| `shekel/_runtime.py` | 1a | C | Register `OpenAIAgentsRunnerAdapter` |
| `tests/test_openai_agents_wrappers.py` | 1a | C | New — 12 test groups |
| `shekel/_budget.py` | 1b | B | Velocity params, methods, `_record_spend`, `_reset_state` |
| `tests/test_spend_velocity.py` | 1b | B | New — 27 test scenarios |
| `docs/integrations/openai-agents.md` | 1c | D | New — full integration guide |
| `docs/usage/loop-guard.md` | 1c | D | New — loop guard usage guide |
| `docs/usage/spend-velocity.md` | 1c | D | New — velocity usage guide |
| `docs/usage/openai_agents_demo.py` | 1c | D | New — runnable example |
| `docs/usage/loop_guard_demo.py` | 1c | D | New — runnable example |
| `docs/usage/spend_velocity_demo.py` | 1c | D | New — runnable example |
| `docs/index.md` | 1c | D | Add 3 What's New v1.1.0 cards; update header |
| `docs/api-reference.md` | 1c | D | New params + exceptions + `loop_guard_counts` |
| `docs/changelog.md` | 1c | D | Add `[1.1.0]` entry |
| `README.md` | 1c | D | OpenAI Agents SDK in table; 2 new exceptions; loop+velocity section |
| `tests/integrations/test_loop_guard_integration.py` | 2b | E | New — mock + live tests |
| `tests/integrations/test_spend_velocity_integration.py` | 2b | E | New — mock + live tests |
| `tests/integrations/test_openai_agents_integration.py` | 2b | E | New — mock + live tests |
| `tests/performance/test_loop_guard_performance.py` | 2b | E | New — overhead benchmarks |
| `tests/performance/test_velocity_performance.py` | 2b | E | New — overhead benchmarks |
| `CHANGELOG.md` | 3 | main | Finalize `[1.1.0]` entry |
| `pyproject.toml` | 3 | main | `version = "1.1.0"` |

**Test count:**
- Unit (A + B + C): 11 + 27 + 12 = **50 tests**
- Integration mock (E): ~25 scenarios across 3 files
- Integration live (E): ~5 scenarios (skipped without API keys)
- Performance (E): ~8 benchmarks

**Total new tests: ~88**
