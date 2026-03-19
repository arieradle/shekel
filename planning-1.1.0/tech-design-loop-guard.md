# Technical Design: Loop Guard — Agent Loop Detection

**Feature:** `loop_guard` parameter for `Budget`
**Target version:** 1.1.0
**Status:** Draft
**Date:** 2026-03-19

---

## 1. Architecture Overview

Loop guard is a **pre-dispatch gate** that sits immediately before the existing
`_check_tool_limit()` call in the tool interception pipeline. The gate inspects a per-tool rolling
timestamp deque and raises `AgentLoopError` if the same tool has been called more than
`loop_guard_max_calls` times within the most recent `loop_guard_window_seconds`.

### Tool dispatch pipeline (with loop guard inserted)

```
Tool invoked (any framework)
        |
        v
shekel._tool / framework adapter
        |
        v
Budget._check_loop_guard(tool_name, framework)   <-- NEW (step 1)
  - evict expired timestamps from deque
  - if len(deque) >= loop_guard_max_calls: raise AgentLoopError (or warn)
        |
        v
Budget._check_tool_limit(tool_name, framework)   <-- existing (step 2)
  - check max_tool_calls
  - check max_usd via tool_prices
        |
        v
Tool executes
        |
        v
Budget._record_tool_call(tool_name, cost, framework)  <-- existing (step 3)
  - append timestamp to per-tool deque   <-- NEW side effect here
  - increment counters, emit events
```

Both gates are **pre-dispatch**: the tool never executes if either fires. The order is intentional:
loop guard fires first because it is the cheaper check (deque length vs timestamp comparison) and
because detecting a loop before checking the global cap produces the more actionable error message.

---

## 2. Data Structure: Rolling Window

### Per-tool timestamp deques

```python
from collections import deque

# Added to Budget.__init__ when loop_guard=True:
self._loop_guard_windows: dict[str, deque[float]] = {}
```

- **Key:** `tool_name` (str) — the canonical tool name from `ToolCallRecord`
- **Value:** `deque[float]` — monotonic timestamps (from `time.monotonic()`) of recent calls

The deque has no `maxlen` cap; eviction is time-based, not count-based. This allows the deque to
grow momentarily above `loop_guard_max_calls` (which is what triggers the error on the NEXT call)
and then shrink again as old entries age out.

### Timestamp source

`time.monotonic()` is used (not `time.time()`) to avoid sensitivity to system clock adjustments.
The window boundary is `now - loop_guard_window_seconds`.

When `loop_guard_window_seconds == 0`, no eviction is performed — all timestamps since budget entry
are retained and counted. This gives "all-time per-tool call count" semantics.

---

## 3. Gate Logic: `_check_loop_guard()`

```python
def _check_loop_guard(self, tool_name: str, framework: str) -> None:
    if not self.loop_guard:
        return

    now = time.monotonic()
    window = self._loop_guard_windows.setdefault(tool_name, deque())

    # Evict timestamps outside the rolling window
    if self.loop_guard_window_seconds > 0:
        cutoff = now - self.loop_guard_window_seconds
        while window and window[0] < cutoff:
            window.popleft()

    # Check: if already at or above the limit, the NEXT call is the violation
    if len(window) >= self.loop_guard_max_calls:
        if self.warn_only:
            import warnings
            warnings.warn(
                f"[shekel] Loop guard triggered for tool '{tool_name}': "
                f"{len(window)} calls in {self.loop_guard_window_seconds}s "
                f"(limit={self.loop_guard_max_calls}). "
                f"Total spent: ${self._spent:.4f}",
                stacklevel=4,
            )
        else:
            raise AgentLoopError(
                tool_name=tool_name,
                repeat_count=len(window),
                window_seconds=self.loop_guard_window_seconds,
                spent=self._spent,
            )
```

### Why check `>= max_calls` before appending

The timestamp of the current call is appended in `_record_tool_call()` (step 3), **after** the
gate (step 1). The gate therefore sees `N` existing timestamps. When `N >= loop_guard_max_calls`,
this call would be call `N+1` — the first call that exceeds the threshold. This mirrors the
existing `max_tool_calls` semantics where the check fires when `_tool_calls_made >= limit`
(i.e., at the `limit+1`-th call).

The PRD specifies "more than N times" — calling the tool N times is fine; call N+1 is blocked.
Since the deque holds N entries when the gate fires, `len(window) >= loop_guard_max_calls` is the
correct condition.

### Timestamp append (in `_record_tool_call`)

```python
def _record_tool_call(self, tool_name: str, cost: float, framework: str) -> None:
    # NEW: append timestamp to loop guard window
    if self.loop_guard:
        self._loop_guard_windows.setdefault(tool_name, deque()).append(time.monotonic())

    # existing logic (unchanged):
    self._tool_calls_made += 1
    self._tool_spent += cost
    self._tool_calls.append(ToolCallRecord(tool_name=tool_name, cost=cost, framework=framework))
    self._emit_tool_call_event(tool_name, cost, framework)
    self._check_tool_warn(tool_name)
```

---

## 4. Files to Create or Modify

### `shekel/exceptions.py` — add `AgentLoopError`

New class, appended after `ToolBudgetExceededError`:

```python
class AgentLoopError(BudgetExceededError):
    """Raised when the same tool is called too many times in a rolling time window.

    Indicates a probable agent loop — the same tool being called repetitively
    without making progress. Raised *before* the tool executes (pre-dispatch gate).

    Attributes:
        tool_name: The tool that triggered the loop guard.
        repeat_count: Number of calls to this tool within the window at time of detection.
        window_seconds: The configured rolling window duration in seconds (0 = all-time).
        spent: Total USD spent by the budget at time of detection.
    """

    def __init__(
        self,
        tool_name: str,
        repeat_count: int,
        window_seconds: float,
        spent: float,
    ) -> None:
        self.tool_name = tool_name
        self.repeat_count = repeat_count
        self.window_seconds = window_seconds
        # spent is passed to BudgetExceededError as both spent and limit (limit=spent)
        # because there is no fixed USD limit for loop guard — we reuse the field for
        # diagnostic purposes and set limit=spent to avoid a misleading "0 of 0" message.
        super().__init__(spent=spent, limit=spent, model=f"loop:{tool_name}")

    def __str__(self) -> str:
        window_str = (
            f"in the last {self.window_seconds:.0f}s"
            if self.window_seconds > 0
            else "total (all-time)"
        )
        return (
            f"Agent loop detected on tool '{self.tool_name}': "
            f"called {self.repeat_count} times {window_str}.\n"
            f"  Total spent: ${self.spent:.4f}\n"
            f"  Tip: Increase loop_guard_max_calls, increase loop_guard_window_seconds, "
            f"or investigate why the agent is repeating '{self.tool_name}'."
        )
```

**Inheritance rationale:** `AgentLoopError` subclasses `BudgetExceededError` (not
`ToolBudgetExceededError`) because it is a budget-level safety event, not a tool-quota event. It
fits the existing hierarchy alongside `NodeBudgetExceededError` and `AgentBudgetExceededError`.
Callers who catch `BudgetExceededError` will also catch `AgentLoopError`, which is the correct
behavior — the budget is protecting against runaway spend.

### `shekel/_budget.py` — modify `Budget`

**`__init__` signature additions:**

```python
def __init__(
    self,
    ...
    loop_guard: bool = False,
    loop_guard_max_calls: int = 5,
    loop_guard_window_seconds: float = 60.0,
) -> None:
```

**Validation in `__init__`:**

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

**New instance attributes (in `__init__`, under tool tracking block):**

```python
# Loop guard (v1.1.0)
self.loop_guard: bool = loop_guard
self.loop_guard_max_calls: int = loop_guard_max_calls
self.loop_guard_window_seconds: float = loop_guard_window_seconds
self._loop_guard_windows: dict[str, deque[float]] = {}
```

The import `from collections import deque` is added at the top of the file.

**`_reset_state` additions:**

```python
# Loop guard reset (v1.1.0)
self._loop_guard_windows = {}
```

**New method `_check_loop_guard`** — as specified in section 3.

**Modified `_record_tool_call`** — append timestamp as specified in section 3.

**Modified `_check_tool_limit` call site** — insert `_check_loop_guard` before it:

The call site is inside the framework-specific tool invocation wrappers (e.g., `shekel/_tool.py`,
the LangChain adapter, the MCP adapter, etc.). Currently these call:

```python
budget._check_tool_limit(tool_name, framework)
# ... tool executes ...
budget._record_tool_call(tool_name, cost, framework)
```

They become:

```python
budget._check_loop_guard(tool_name, framework)   # NEW
budget._check_tool_limit(tool_name, framework)
# ... tool executes ...
budget._record_tool_call(tool_name, cost, framework)
```

**`snapshot()` / `to_dict()` additions:**

```python
"loop_guard": self.loop_guard,
"loop_guard_max_calls": self.loop_guard_max_calls,
"loop_guard_window_seconds": self.loop_guard_window_seconds,
"loop_guard_counts": {
    name: len(window) for name, window in self._loop_guard_windows.items()
},
```

### `shekel/__init__.py` — export `AgentLoopError`

```python
from shekel.exceptions import (
    ...
    AgentLoopError,       # NEW
    ...
)

__all__ = [
    ...
    "AgentLoopError",     # NEW
    ...
]
```

### `tests/test_loop_guard.py` — new test file (see section 9)

---

## 5. `AgentLoopError` Exception Design

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `tool_name` | `str` | The tool that crossed the threshold |
| `repeat_count` | `int` | Number of calls in the window at time of detection |
| `window_seconds` | `float` | The configured window (0 = all-time) |
| `spent` | `float` | Total USD spent by the budget at time of raise |

### Inherited fields (from `BudgetExceededError`)

`spent`, `limit`, `model`, `tokens`, `retry_after`, `window_spent`, `exceeded_counter` — most
inherited fields are irrelevant and left at defaults. `model` is set to `f"loop:{tool_name}"` to
make stack traces readable.

### `__str__` output example

```
Agent loop detected on tool 'web_search': called 5 times in the last 60s.
  Total spent: $0.0420
  Tip: Increase loop_guard_max_calls, increase loop_guard_window_seconds,
       or investigate why the agent is repeating 'web_search'.
```

---

## 6. Integration with `ToolCallRecord` and `_record_tool_call`

`ToolCallRecord` is unchanged. The loop guard uses `tool_name` from the existing record as its
dictionary key. No new fields are added to `ToolCallRecord`.

The timestamp appended to `_loop_guard_windows[tool_name]` is the monotonic time at the point of
`_record_tool_call()` invocation — after the tool executes successfully. This means:

- A tool that raises an exception does NOT have its timestamp recorded (the framework adapter will
  not call `_record_tool_call` on failure, consistent with existing behavior).
- The loop guard gate fires on the `N+1`-th **successful dispatch attempt**, not on errors.

If a tool consistently errors (e.g. network failure), each failed call does not increment the loop
guard window, so a retry loop on a failing tool would not be caught by loop guard alone. This is
acceptable for v1.1.0 — error-based retries should be caught by `max_tool_calls` instead.

---

## 7. Budget State: New Fields on `Budget`

### Constructor parameters (public)

```python
loop_guard: bool = False
loop_guard_max_calls: int = 5
loop_guard_window_seconds: float = 60.0
```

### Instance attributes

```python
self.loop_guard: bool
self.loop_guard_max_calls: int
self.loop_guard_window_seconds: float
self._loop_guard_windows: dict[str, deque[float]]  # private, not exposed via property
```

### Public read-only property (informational)

```python
@property
def loop_guard_counts(self) -> dict[str, int]:
    """Live per-tool call counts within the current rolling window.

    Returns a snapshot — calls earlier than loop_guard_window_seconds ago are
    not included. Returns an empty dict when loop_guard=False.
    """
    if not self.loop_guard:
        return {}
    now = time.monotonic()
    result: dict[str, int] = {}
    for tool_name, window in self._loop_guard_windows.items():
        if self.loop_guard_window_seconds > 0:
            cutoff = now - self.loop_guard_window_seconds
            count = sum(1 for ts in window if ts >= cutoff)
        else:
            count = len(window)
        result[tool_name] = count
    return result
```

---

## 8. Public API Additions Summary

| Addition | Type | Location |
|----------|------|----------|
| `Budget(loop_guard=True)` | parameter | `shekel/_budget.py` |
| `Budget(loop_guard_max_calls=5)` | parameter | `shekel/_budget.py` |
| `Budget(loop_guard_window_seconds=60.0)` | parameter | `shekel/_budget.py` |
| `Budget.loop_guard_counts` | read-only property | `shekel/_budget.py` |
| `AgentLoopError` | exception class | `shekel/exceptions.py` |
| `shekel.AgentLoopError` | re-export | `shekel/__init__.py` |

`budget()` factory in `__init__.py` passes `loop_guard`, `loop_guard_max_calls`, and
`loop_guard_window_seconds` through `**kwargs` to `Budget.__init__` unchanged — no changes needed
to the factory function itself.

---

## 9. Interaction with `max_tool_calls`

`loop_guard` and `max_tool_calls` are fully independent. They track different things:

| Control | What it tracks | What it raises |
|---------|----------------|----------------|
| `max_tool_calls` | Total tool dispatches across all tools | `ToolBudgetExceededError` |
| `loop_guard` | Per-tool call count in a rolling window | `AgentLoopError` |

Both can be set simultaneously. The order of checks (loop guard first, then `max_tool_calls`) means
whichever threshold is crossed first wins. In practice:

- A loop on a cheap tool (many calls, low cost) hits `loop_guard` first.
- An agent using many distinct tools hits `max_tool_calls` first.
- Both firing for the same call: `loop_guard` fires (it is checked first), and the exception
  propagates before `max_tool_calls` is evaluated.

They do not share state. Resetting one does not affect the other. Nested child budgets inherit
`max_tool_calls` auto-cap behavior as before; `_loop_guard_windows` is never inherited or shared
with parents.

---

## 10. Test Strategy

**File:** `tests/test_loop_guard.py`

### Key scenarios to cover

#### Baseline behavior

- `loop_guard=False` (default): calling a tool 100 times never raises `AgentLoopError`. No window
  dict is allocated.
- `loop_guard=True`, calls < threshold: no error after `loop_guard_max_calls` calls.
- `loop_guard=True`, calls == threshold + 1: `AgentLoopError` raised with correct fields.

#### Threshold and window math

- Call tool 5 times, sleep past the window, call 5 more times — no error (window slides).
- Call tool 5 times within window, call once more — error fires on call 6.
- `loop_guard_window_seconds=0`: all-time count; error fires after `max_calls + 1` total calls
  regardless of time elapsed.

#### Exception field verification

- Assert `e.tool_name == "my_tool"`
- Assert `e.repeat_count == loop_guard_max_calls`
- Assert `e.window_seconds == loop_guard_window_seconds`
- Assert `e.spent >= 0.0`
- Assert `isinstance(e, BudgetExceededError)`

#### `warn_only` mode

- With `warn_only=True` and loop detected: `warnings.warn` is called, no exception raised, tool
  call count in deque continues to grow.
- Assert the warning message contains the tool name and repeat count.

#### Multi-tool isolation

- Tool A called 10 times (exceeds threshold), Tool B called 3 times — only Tool A triggers.
- After `AgentLoopError` for Tool A, Tool B can still be called normally.

#### Coexistence with `max_tool_calls`

- Both set; loop fires first (same tool, high frequency).
- Both set; `max_tool_calls` fires first (many distinct tools, none repeating above `loop_guard_max_calls`).

#### State reset

- Call tool to threshold, call `b.reset()`, call tool again — no error (window was reset).

#### Custom thresholds

- `loop_guard_max_calls=1`: second call to any tool raises.
- `loop_guard_max_calls=100, loop_guard_window_seconds=1`: 100 calls in 2 seconds (spanning two
  windows) do not raise.

#### `loop_guard_counts` property

- Returns empty dict when `loop_guard=False`.
- Returns correct per-tool counts after calls, excluding expired entries.

#### Validation errors

- `loop_guard_max_calls=0` raises `ValueError` at construction time.
- `loop_guard_window_seconds=-1.0` raises `ValueError` at construction time.

#### Integration paths

- Loop guard fires when tool is invoked via `@tool` decorator.
- Loop guard fires when tool is invoked via mocked LangChain adapter call site.
- (MCP and CrewAI: mock the adapter call site similarly.)

### Test file structure

```
tests/test_loop_guard.py
  class TestLoopGuardBaseline
  class TestLoopGuardThresholds
  class TestLoopGuardWindowExpiry
  class TestAgentLoopErrorFields
  class TestLoopGuardWarnOnly
  class TestLoopGuardMultiTool
  class TestLoopGuardWithMaxToolCalls
  class TestLoopGuardReset
  class TestLoopGuardValidation
  class TestLoopGuardCounts
  class TestLoopGuardIntegration
```

---

## 11. Edge Cases

### Legitimate high-frequency tool use

A batch agent that calls `write_file` 500 times in a loop (legitimate: processing 500 documents)
will trigger loop guard with defaults. The developer must set `loop_guard_max_calls` to a value
above their expected per-tool call count, or disable loop guard for that specific budget.

There is no per-tool exemption list in v1.1.0 (out of scope). The tuning parameters are the
mitigation.

### Async concurrent calls

CPython's `deque.append()` and `deque.popleft()` are GIL-protected for individual operations, but
the check-then-act sequence in `_check_loop_guard` is not atomic:

```python
# Thread/task A and B both check len(window) == max_calls - 1 simultaneously
# Both see the count as below threshold and proceed
# Both append; now len(window) == max_calls + 1 with no error raised
```

This is an accepted limitation for v1.1.0, consistent with the existing `Budget` thread-safety
disclaimer. The docstring for `loop_guard` will note this and recommend using a separate `Budget`
instance per concurrent task when strict enforcement is required.

### Nested budgets

Each `Budget` instance maintains its own `_loop_guard_windows` dict. A child budget's window
counts are independent of its parent's. A loop detected in the child raises in the child's context;
the parent's window is unaffected. This is consistent with how `_tool_calls_made` is tracked
independently per budget instance.

Child budgets do NOT inherit the parent's `loop_guard` setting. If a developer wants loop guard on
a child, they must set it explicitly on the child `Budget`. This avoids surprising behavior where
adding loop guard to a parent silently changes child behavior.

### Budget reused across sessions

When a `Budget` is used across multiple `with` blocks (session mode), `_loop_guard_windows` is NOT
reset between blocks by default — the rolling window persists. This is correct: if an agent loops
across a session boundary, it should still be caught. `b.reset()` clears the windows for users who
need a clean slate per session.

### `loop_guard_window_seconds` very large (e.g. 86400)

The deque can grow indefinitely if a tool is called thousands of times in 24 hours. This is
expected: a deque with 10,000 entries costs roughly 80KB (8 bytes per float × 10k). At the scale
where this matters, the developer should be using `max_tool_calls` instead of (or in addition to)
loop guard.

### `loop_guard=True` with no tool calls

No windows are allocated, no overhead. `loop_guard_counts` returns `{}`.
