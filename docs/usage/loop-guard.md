---
title: Loop Guard – Detect and Stop Infinite AI Agent Tool Loops
description: "Automatically detect and stop infinite tool-call loops before they drain your LLM budget. Per-tool rolling-window counter raises AgentLoopError before the tool executes."
tags:
  - agent-safety
  - loop-detection
  - tool-budgets
  - budget-enforcement
---

# Loop Guard

**Detect and stop agent tool loops before they drain your wallet. One parameter.**

Your agent called `web_search` 2,000 times last night because the search results never changed and the model kept retrying. `max_usd` would have eventually stopped it — but loop guard stops it in seconds.

---

## The problem

A hard `max_usd` cap is a blunt instrument. Consider this scenario:

- Agent is given a task to monitor a news feed
- The feed returns stale results
- The model decides to keep calling `fetch_news` hoping for fresh data
- 300 identical calls later, you've spent $12 on a loop
- `max_usd=50.00` hasn't fired yet

The loop guard catches the **pattern**: the same tool, called repeatedly, in a short window. It doesn't matter what the results are — if a single tool fires 5+ times within 60 seconds, something is wrong.

---

## Quick Start

```python
from shekel import budget, AgentLoopError

try:
    with budget(max_usd=5.00, loop_guard=True) as b:
        run_my_agent()
except AgentLoopError as e:
    print(f"Loop detected on tool '{e.tool_name}': {e.call_count} calls in {e.window_seconds}s")
```

No changes to your agent. Works with all auto-intercepted frameworks out of the box.

---

## How it works

When `loop_guard=True`, shekel maintains a **per-tool rolling window counter** alongside its normal spend tracking:

1. Every time a tool is dispatched, shekel records a timestamp for that tool name
2. Before each dispatch, it counts how many calls to that tool fall within the rolling window
3. If the count reaches `loop_guard_max_calls`, `AgentLoopError` is raised **before the tool executes**
4. Old timestamps outside the window are evicted lazily on each check

The gate fires at the **pre-dispatch point** — the same gate used by `max_tool_calls`. The tool body never runs when the loop guard triggers.

---

## Tuning thresholds

The defaults (`max_calls=5`, `window=60s`) are conservative. Tune them to your use case:

```python
# High-frequency scraper — allow 20 calls per minute per tool
with budget(
    max_usd=10.00,
    loop_guard=True,
    loop_guard_max_calls=20,
    loop_guard_window_seconds=60.0,
) as b:
    run_scraper()
```

```python
# Strict loop detection — 3 calls in 30 seconds
with budget(
    loop_guard=True,
    loop_guard_max_calls=3,
    loop_guard_window_seconds=30.0,
) as b:
    run_agent()
```

```python
# All-time cap — never call the same tool more than N times total
with budget(
    loop_guard=True,
    loop_guard_max_calls=10,
    loop_guard_window_seconds=0,  # 0 = all-time, no rolling window
) as b:
    run_agent()
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `loop_guard` | `bool` | `False` | Enable per-tool rolling-window loop detection |
| `loop_guard_max_calls` | `int` | `5` | Max calls to the same tool within the window before `AgentLoopError` |
| `loop_guard_window_seconds` | `float` | `60.0` | Rolling window duration in seconds. `0` = all-time cap |

---

## Reading the exception

`AgentLoopError` carries enough context to understand the loop:

```python
from shekel import budget, AgentLoopError

try:
    with budget(loop_guard=True) as b:
        run_agent()
except AgentLoopError as e:
    print(f"Tool:           {e.tool_name}")
    print(f"Call count:     {e.call_count}")
    print(f"Window (s):     {e.window_seconds}")
    print(f"USD spent:      ${e.usd_spent:.4f}")
    print(f"Framework:      {e.framework}")  # "langchain", "mcp", "crewai", "openai-agents", "manual"
```

`AgentLoopError` subclasses `BudgetExceededError`, so existing `except BudgetExceededError` blocks catch it automatically.

---

## `warn_only` mode

Use `warn_only=True` to observe loop patterns in staging without blocking production traffic:

```python
import logging

with budget(loop_guard=True, warn_only=True) as b:
    run_agent()
# Never raises — logs a warning when a loop is detected instead

# After the run, inspect what would have been caught
for tool, count in b.loop_guard_counts.items():
    if count >= 5:
        logging.warning(f"Tool '{tool}' called {count} times — possible loop")
```

---

## Combining with `max_tool_calls`

Loop guard and `max_tool_calls` are independent. Both are enforced simultaneously:

```python
with budget(
    max_tool_calls=100,     # never more than 100 total dispatches
    loop_guard=True,        # also never more than 5 calls to the same tool in 60s
    loop_guard_max_calls=5,
) as b:
    run_agent()
# Whichever fires first wins: ToolBudgetExceededError or AgentLoopError
```

This combination gives you both a global tool budget and a per-tool repetition guard.

---

## Inspecting live counts

Read current per-tool call counts from `b.loop_guard_counts`:

```python
with budget(loop_guard=True) as b:
    run_agent()

# After the run — see how many times each tool was called
for tool_name, count in b.loop_guard_counts.items():
    print(f"  {tool_name}: {count} calls")
```

`loop_guard_counts` is a `dict[str, int]` mapping tool name to total calls recorded within the current window. Use it for observability, logging, or post-run analysis even when no loop was detected.

---

## Edge cases

### Legitimate high-frequency tools

Some tools are genuinely called hundreds of times — polling sensors, streaming chunked data, high-frequency analysis. Tune the thresholds or disable loop guard for those tools by using separate budget contexts:

```python
# Outer budget: loop guard active for all agent tools
with budget(max_usd=20.00, loop_guard=True, loop_guard_max_calls=5, name="agent") as agent_b:
    run_orchestration_agent()

# Inner budget for the high-frequency collector: no loop guard
with budget(max_usd=5.00, name="collector") as collector_b:
    run_sensor_collector()  # calls read_sensor() 500 times — intentional
```

Nested budgets inherit the parent's loop guard settings by default. Use a separate root-level budget for collectors that legitimately call the same tool at high frequency.

### Tool name collisions

Loop guard tracks by the exact tool name as reported by the framework adapter. If two different tools share a name across frameworks, their counts are merged. Ensure tool names are unique within an agent session.

---

## Framework coverage

Loop guard works with every framework shekel auto-intercepts:

| Framework | Interception point |
|---|---|
| `@tool` (plain Python) | shekel decorator |
| LangChain / LangGraph | `BaseTool.invoke` / `ainvoke` |
| MCP | `ClientSession.call_tool` |
| CrewAI | `BaseTool._run` / `_arun` |
| OpenAI Agents SDK | `FunctionTool` dispatch |

No framework-specific configuration needed — loop guard fires at the same pre-dispatch gate as `max_tool_calls`.

---

## Next Steps

- [Spend Velocity](spend-velocity.md) — burn-rate circuit breaker
- [Tool Budgets](tool-budgets.md) — cap total tool calls and charge per tool
- [API Reference](../api-reference.md)
