# PRD: Loop Guard — Agent Loop Detection for shekel

**Version:** 1.1.0-planned
**Status:** Draft
**Author:** shekel core team
**Date:** 2026-03-19

---

## 1. Problem Statement

### The "$47 Overnight Bill" Pattern

The most common cause of runaway LLM API spend is not a single expensive request — it is an
agent stuck in a loop. An agent calls a tool, receives an unexpected response, calls the same tool
again hoping for a different result, and repeats this hundreds or thousands of times before a human
notices. The entire session runs overnight or over a weekend while no one is watching.

This failure mode has a distinctive signature: **the same tool name appears in the call log at high
frequency within a short time window.** It is structurally different from legitimate high-volume use
(e.g. a batch job calling `write_file` 500 times sequentially) because it is **repetitive without
progress** — the agent is not advancing toward its goal.

### Why Existing Controls Fall Short

shekel already offers:

- `max_usd` — caps total spend, but the loop may exhaust the budget before the cap fires if the
  tool itself is cheap (e.g. a free local tool or a low-cost search call at $0.001 each)
- `max_tool_calls` — caps total dispatch count, but a legitimate agent doing 300 distinct tool
  calls would also be blocked

Neither control distinguishes **repetition of the same tool** from **breadth of tool use**.
A loop guard based on per-tool frequency in a rolling window fills this gap.

### Market Gap

No LLM observability or budget library currently detects runaway agent loops at the tool-dispatch
level. This is shekel's opportunity to be the first library that stops the "$47 overnight bill"
pattern before it starts.

---

## 2. Target Users and Jobs-to-Be-Done

### Primary: ML/AI Engineers deploying autonomous agents

**Job:** Ship reliable agents that do not accrue unexpected costs when they malfunction.

**Context:** They run agents in production that operate without human oversight for hours at a time.
They cannot afford to babysit every run. They want a single line of code that kills a runaway loop
before it hits their billing page.

### Secondary: Platform teams building multi-agent systems

**Job:** Provide cost safety guarantees across a fleet of agents with heterogeneous tools.

**Context:** They expose shekel as infrastructure. They need per-budget loop detection that works
independently for each running agent without cross-contamination.

### Tertiary: Hobbyists and researchers running overnight experiments

**Job:** Wake up to results, not a bill.

**Context:** They use single-shot scripts. They want a safe default they can add with one parameter
and forget about.

---

## 3. User Stories

**US-1 — Simple opt-in protection**
As an ML engineer, I want to add `loop_guard=True` to my existing budget and have the agent
immediately protected using sensible defaults, so that I do not need to understand the internals to
get coverage.

**US-2 — Tunable thresholds**
As a platform engineer, I want to set `loop_guard_max_calls=10` and
`loop_guard_window_seconds=120` so that I can match the thresholds to my specific agent's expected
tool usage patterns without over-triggering on legitimate high-frequency behavior.

**US-3 — Clear attribution in the exception**
As a developer debugging a production incident, I want the `AgentLoopError` to tell me exactly
which tool was looping, how many times it was called in the window, and what the total USD spend
was at time of detection, so I can reproduce and fix the root cause quickly.

**US-4 — Graceful warn-only mode**
As a researcher, I want to use `warn_only=True` combined with `loop_guard=True` so that a detected
loop logs a warning instead of raising, allowing my experiment to continue while I observe the
behavior.

**US-5 — Independent coexistence with `max_tool_calls`**
As a platform engineer, I want `loop_guard` and `max_tool_calls` to work independently so that I
can set a global cap on total dispatches AND a per-tool repetition limit without one interfering
with the other.

---

## 4. Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|--------------------|
| Quickstart fits in one line | `loop_guard=True` is the full API; no required configuration | Verify docs quickstart example ≤ 4 lines |
| Zero false positives on legitimate bursts | N distinct tools, each called M times, never triggers at default settings when M ≤ `loop_guard_max_calls` | Unit test: synthetic trace with 5 tools × 5 calls each, assert no error |
| Loop detection latency | Fires within the window + 1 dispatch | Unit test: assert fires on call N+1 |
| Exception field completeness | 100% of fields populated on raise | Unit test: inspect all AgentLoopError attrs |
| `warn_only` compatibility | No raise, warning emitted | Unit test: assert warning logged, no exception |
| Docs coverage | End-to-end usage example in docs | Manual review |
| Code coverage | 100% (per project standard) | `pytest --cov=shekel` |

---

## 5. Scope

### In Scope

- New `Budget` constructor parameter: `loop_guard: bool = False`
- New optional tuning parameters: `loop_guard_max_calls: int = 5`,
  `loop_guard_window_seconds: float = 60.0`
- Per-tool rolling time window tracking using a `deque` of timestamps
- Pre-dispatch gate that fires `AgentLoopError` when the threshold is crossed
- New `AgentLoopError` exception with: `tool_name`, `repeat_count`, `window_seconds`, `spent`
- `AgentLoopError` exported from `shekel.__init__`
- `warn_only` compatibility (warning instead of raise)
- Works for all existing tool interception paths: `@tool` decorator, LangChain, MCP, CrewAI,
  OpenAI Agents
- `loop_guard_window_seconds=0` disables the window (all-time count per tool, no eviction)
- Nested budget: each `Budget` instance has its own independent loop guard state

### Out of Scope

- Semantic similarity detection (detecting loops where the tool name changes but the call
  arguments are equivalent — this requires embedding infrastructure and is a future feature)
- Argument-level deduplication (detecting identical arguments, not just identical tool names)
- Distributed / cross-process loop state (the rolling window is in-process only)
- Automatic agent restart or recovery (shekel raises; the caller decides what to do)
- Per-tool different thresholds (all tools share the same `loop_guard_max_calls` and
  `loop_guard_window_seconds`)
- Async-safe shared state across concurrent tasks in the same budget (out of scope for v1.1.0;
  the existing Budget thread-safety disclaimer applies)

---

## 6. High-Level API Design

### Basic usage — defaults

```python
from shekel import budget

with budget(max_usd=5.00, loop_guard=True) as b:
    run_agent()  # AgentLoopError raised if any tool is called >5 times in 60s
```

### Tuned thresholds

```python
with budget(max_usd=5.00, loop_guard=True, loop_guard_max_calls=10,
            loop_guard_window_seconds=120.0) as b:
    run_agent()
```

### Warn-only mode (no raise)

```python
with budget(max_usd=5.00, loop_guard=True, warn_only=True) as b:
    run_agent()  # Logs a warning; does not raise
```

### Catching the exception

```python
from shekel import budget, AgentLoopError

try:
    with budget(max_usd=5.00, loop_guard=True) as b:
        run_agent()
except AgentLoopError as e:
    print(f"Loop detected on '{e.tool_name}': "
          f"{e.repeat_count} calls in {e.window_seconds}s, "
          f"${e.spent:.4f} spent")
```

### With `max_tool_calls` (independent, both enforced)

```python
with budget(max_usd=5.00, max_tool_calls=100, loop_guard=True,
            loop_guard_max_calls=8) as b:
    run_agent()
# Raises ToolBudgetExceededError if total calls > 100
# Raises AgentLoopError if any single tool repeats > 8 times in 60s
# Whichever fires first wins
```

---

## 7. Edge Cases the Product Must Handle

| Edge Case | Required Behavior |
|-----------|-------------------|
| Tool called exactly `loop_guard_max_calls` times | No error. Error fires on call number `loop_guard_max_calls + 1`. |
| Calls spread across two windows (old calls expire) | After old timestamps are evicted, the count drops below threshold; subsequent calls may accumulate a new violation. |
| `loop_guard_window_seconds=0` | Window is infinite — all calls to a tool are counted; no eviction. |
| `loop_guard=False` (default) | No tracking overhead; rolling window dict never created; zero behavioral change. |
| `warn_only=True` | `AgentLoopError` is not raised; a `warnings.warn()` is issued with the same diagnostic string. |
| Nested budgets | Each child budget tracks its own window independently. A loop in a child does not affect the parent's counter. |
| Tool called by multiple frameworks (e.g., LangChain + MCP) | The `tool_name` key is the canonical name recorded in `ToolCallRecord`; all calls to the same name from any framework are counted together in the same per-tool window. |
| Budget reused across multiple `with` blocks (session mode) | The rolling window state carries over between blocks by default. Calling `b.reset()` clears it. |
| `loop_guard_max_calls=1` | Any tool called twice in the window triggers. This is a valid edge config for strict environments. |
| Very fast async agents calling a tool concurrently | `deque` operations in CPython are GIL-protected for single appends/poplefts, but the check-then-act is not atomic. The docstring must note this and recommend a per-task budget when strict concurrency safety is needed. |
