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

## Phase 2 — Integration and Polish

**After all three agents are done.**

### Step 2.1 — Full test suite

```bash
pytest --cov=shekel --cov-report=term-missing -v
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

Run these specific scenarios manually to verify features coexist:

```python
# Loop guard + velocity together
with budget(max_usd=10.00, loop_guard=True, max_velocity="$1/min") as b:
    ...  # both should be independently enforceable

# OAI SDK + loop guard + velocity
with budget(max_usd=5.00, loop_guard=True, max_velocity="$0.50/min") as b:
    b.agent("researcher", max_usd=1.00)
    result = await Runner.run(agent, "input")
```

### Step 2.4 — Bump version

In `shekel/__init__.py`: `__version__ = "1.1.0"`
In `pyproject.toml`: `version = "1.1.0"`

### Step 2.5 — Update CHANGELOG.md

Add `## [1.1.0]` entry documenting all three features.

### Step 2.6 — Push and open PR

```bash
git push -u origin feat/v1.1.0
gh pr create --base main --title "feat: v1.1.0 — OpenAI Agents SDK, loop guard, spend velocity"
```

---

## File Change Summary

| File | Phase | Agent | Change type |
|------|-------|-------|-------------|
| `shekel/exceptions.py` | 0 | main | Add 2 exception classes |
| `shekel/__init__.py` | 0 | main | Export 2 new exceptions; version bump (Phase 2) |
| `shekel/_budget.py` | 1a | A | Loop guard params, methods, _record_tool_call, _reset_state |
| `shekel/_tool.py` | 1a | A | Insert _check_loop_guard at 3 call sites |
| `shekel/providers/langchain.py` | 1a | A | Insert _check_loop_guard at 2 call sites |
| `shekel/providers/mcp.py` | 1a | A | Insert _check_loop_guard at 1 call site |
| `shekel/providers/crewai.py` | 1a | A | Insert _check_loop_guard at 2 call sites |
| `shekel/providers/openai_agents.py` | 1a | A | Insert _check_loop_guard at 1 call site |
| `tests/test_loop_guard.py` | 1a | A | New — 11 test classes |
| `shekel/providers/openai_agents_runner.py` | 1a | C | New file — full adapter |
| `shekel/_runtime.py` | 1a | C | Register OpenAIAgentsRunnerAdapter |
| `tests/test_openai_agents_wrappers.py` | 1a | C | New — 12 test groups |
| `shekel/_budget.py` | 1b | B | Velocity params, methods, _record_spend, _reset_state |
| `tests/test_spend_velocity.py` | 1b | B | New — 27 test scenarios |
| `CHANGELOG.md` | 2 | main | Add [1.1.0] entry |
| `pyproject.toml` | 2 | main | version = "1.1.0" |

**Total new test scenarios:** 11 + 12 + 27 = **50 tests minimum**
