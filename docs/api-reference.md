---
title: API Reference – Shekel LLM Budget Control
description: "Complete Python API reference for shekel: budget(), TemporalBudget, with_budget, @tool, all parameters, properties, methods, and the full exception hierarchy."
tags:
  - budget-enforcement
  - cost-tracking
  - agent-safety
  - llm-guardrails
---

# API Reference

Complete reference for all shekel APIs.

## `budget()`

Context manager for tracking and enforcing LLM API budgets.

### Signature

```python
def budget(
    max_usd: float | None = None,
    warn_at: float | None = None,
    on_warn: Callable[[float, float], None] | None = None,
    price_per_1k_tokens: dict[str, float] | None = None,
    fallback: dict[str, Any] | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
    name: str | None = None,
    max_llm_calls: int | None = None,
) -> Budget
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_usd` | `float \| None` | `None` | Maximum spend in USD. `None` = track-only mode (no enforcement). Must be positive if set. |
| `warn_at` | `float \| None` | `None` | Fraction (0.0-1.0) of `max_usd` at which to warn. |
| `on_warn` | `Callable[[float, float], None] \| None` | `None` | Callback fired at `warn_at` threshold. Receives `(spent, limit)`. |
| `price_per_1k_tokens` | `dict[str, float] \| None` | `None` | Override pricing: `{"input": X, "output": Y}` per 1k tokens. |
| `fallback` | `dict[str, Any] \| None` | `None` | Dict specifying when and what model to switch to: `{"at_pct": 0.8, "model": "gpt-4o-mini"}`. `at_pct` is the fraction of `max_usd` at which to switch; `model` is the fallback model (same provider only). Fallback shares the same `max_usd` budget — there is no separate ceiling. |
| `on_fallback` | `Callable[[float, float, str], None] \| None` | `None` | Callback on fallback switch. Receives `(spent, limit, fallback_model)`. |
| `name` | `str \| None` | `None` | Budget name for debugging and cost attribution. **Required when nesting budgets**. |
| `max_llm_calls` | `int \| None` | `None` | Maximum number of LLM API calls. Raises `BudgetExceededError` when exceeded. Can be combined with `max_usd`. |
| `loop_guard` | `bool` | `False` | Enable per-tool rolling-window loop detection. Raises `AgentLoopError` when the same tool is called more than `loop_guard_max_calls` times within `loop_guard_window_seconds`. |
| `loop_guard_max_calls` | `int` | `5` | Max calls to the same tool within the window before `AgentLoopError`. Only applies when `loop_guard=True`. |
| `loop_guard_window_seconds` | `float` | `60.0` | Rolling window duration in seconds. `0` = all-time cap (no rolling window). Only applies when `loop_guard=True`. |
| `max_velocity` | `str \| None` | `None` | Spend velocity cap. Format: `"$<amount>/<unit>"` (e.g. `"$0.50/min"`, `"$5/hr"`). Raises `SpendVelocityExceededError` when the burn rate exceeds this threshold. |
| `warn_velocity` | `str \| None` | `None` | Soft velocity warning threshold. Same format as `max_velocity`. Must be less than `max_velocity`. Fires `on_warn` callback when crossed; does not raise. |

### Returns

`Budget` object that can be used as a context manager.

### Examples

#### Track-Only Mode

```python
with budget() as b:
    run_agent()
print(f"Cost: ${b.spent:.4f}")
```

#### Budget Enforcement

```python
with budget(max_usd=1.00) as b:
    run_agent()
```

#### Early Warning

```python
with budget(max_usd=5.00, warn_at=0.8) as b:
    run_agent()  # Warns at $4.00
```

#### Custom Warning Callback

```python
def my_handler(spent: float, limit: float):
    print(f"Alert: ${spent:.2f} / ${limit:.2f}")

with budget(max_usd=10.00, warn_at=0.8, on_warn=my_handler):
    run_agent()
```

#### Model Fallback

```python
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_agent()
```

#### Call-Count Budget

```python
with budget(max_llm_calls=50) as b:
    run_agent()  # Raises BudgetExceededError after 50 LLM calls
```

#### Combined USD and Call-Count Budget

```python
with budget(max_usd=1.00, max_llm_calls=20, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_agent()
```

#### Accumulating Budget

```python
# Budget variables accumulate across uses
session = budget(max_usd=10.00, name="session")

with session:
    process_batch_1()

with session:
    process_batch_2()  # Accumulates automatically

print(f"Total: ${session.spent:.2f}")
```

#### Custom Pricing

```python
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.002, "output": 0.006}
):
    run_agent()
```

#### Nested Budgets

```python
with budget(max_usd=10.00, name="workflow") as workflow:
    # Research stage: $2 budget
    with budget(max_usd=2.00, name="research"):
        run_research()
    
    # Analysis stage: $5 budget
    with budget(max_usd=5.00, name="analysis"):
        run_analysis()
    
    # Parent can spend too
    finalize()

print(f"Total: ${workflow.spent:.2f}")
print(workflow.tree())
```

[See full nested budgets guide →](usage/nested-budgets.md)

---

## `Budget` Class

The budget context manager object.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `spent` | `float` | Total USD spent in this budget context (includes children in nested budgets). |
| `remaining` | `float \| None` | Remaining USD budget (based on effective limit), or `None` if track-only mode. |
| `limit` | `float \| None` | Effective budget limit (auto-capped if nested), or `None` if track-only. |
| `name` | `str \| None` | Budget name. |
| `model_switched` | `bool` | `True` if fallback was activated. |
| `switched_at_usd` | `float \| None` | USD spent when fallback occurred, or `None`. |
| `fallback_spent` | `float` | USD spent on the fallback model. |
| `loop_guard_counts` | `dict[str, int]` | Per-tool call counts recorded by the loop guard. Empty dict when `loop_guard=False`. Keys are tool names; values are total calls recorded within the current window. |

### Nested Budget Properties {#nested-budget-properties}

| Property | Type | Description |
|----------|------|-------------|
| `parent` | `Budget \| None` | Parent budget, or `None` if root budget. |
| `children` | `list[Budget]` | List of child budgets created under this budget. |
| `active_child` | `Budget \| None` | Currently active child budget, or `None`. |
| `full_name` | `str` | Hierarchical path name (e.g., `"workflow.research.validation"`). |
| `spent_direct` | `float` | Direct spend by this budget only (excluding children). |
| `spent_by_children` | `float` | Sum of spend from all child budgets. |

### Methods

#### `reset()`

Reset spend tracking to zero. Only works when budget is not active.

```python
session = budget(max_usd=10.00, name="session")

with session:
    process()

session.reset()  # Back to $0

with session:
    process_again()
```

**Raises:** `RuntimeError` if called inside an active `with` block.

#### `summary()`

Return formatted spend summary as a string.

```python
with budget(max_usd=5.00) as b:
    run_agent()

print(b.summary())
```

**Returns:** Multi-line string with formatted table of calls, costs, and totals.

#### `summary_data()`

Return structured spend data as a dict.

```python
with budget() as b:
    run_agent()

data = b.summary_data()
print(data["total_spent"])
print(data["total_calls"])
print(data["by_model"])
```

**Returns:** Dictionary with keys:
- `total_spent`: Total USD
- `limit`: Budget limit
- `model_switched`: Boolean
- `switched_at_usd`: Switch point
- `fallback_model`: Fallback model name
- `fallback_spent`: Cost on fallback
- `total_calls`: Number of API calls
- `calls`: List of all call records
- `by_model`: Aggregated stats per model

#### `tree()`

Return visual hierarchy of budget tree with spend breakdown.

```python
with budget(max_usd=20, name="workflow") as w:
    with budget(max_usd=5, name="research"):
        research()
    with budget(max_usd=10, name="analysis"):
        analyze()

print(w.tree())
# workflow: $12.50 / $20.00 (direct: $0.00)
#   research: $3.20 / $5.00 (direct: $3.20)
#   analysis: $9.30 / $10.00 (direct: $9.30)
```

Also renders registered component budgets (nodes, agents, tasks). LangGraph node spend is tracked automatically; agent/task spend requires future framework adapters.

```python
with budget(max_usd=10, name="workflow") as b:
    b.node("fetch", max_usd=0.50)
    b.node("summarize", max_usd=1.00)
    run_langgraph_workflow()

print(b.tree())
# workflow: $0.84 / $10.00 (direct: $0.00)
#   [node] fetch: $0.12 / $0.50 (24.0%)
#   [node] summarize: $0.72 / $1.00 (72.0%)
```

**Returns:** Multi-line string with indented tree structure showing:
- Budget name and hierarchy
- Total spend / limit
- Direct spend (excluding children)
- `[ACTIVE]` marker for currently active children
- `[node]`, `[agent]`, `[task]` component budget lines with spend/limit/percentage

#### `node(name, max_usd)`

Register an explicit USD cap for a named LangGraph node. Returns `self` for chaining.

The cap is enforced by `LangGraphAdapter` — `NodeBudgetExceededError` is raised before the node body executes when the cap is reached. Spend is attributed to `ComponentBudget._spent` and visible in `budget.tree()`.

```python
with budget(max_usd=10.00) as b:
    b.node("fetch_data", max_usd=0.50).node("summarize", max_usd=1.00)

    graph = StateGraph(State)
    graph.add_node("fetch_data", fetch_fn)
    graph.add_node("summarize", summarize_fn)
    app = graph.compile()
    app.invoke(state)
```

**Parameters:**
- `name` — node name (must match the name passed to `StateGraph.add_node()`)
- `max_usd` — USD cap; must be positive

**Raises:** `ValueError` if `max_usd <= 0`

#### `agent(name, max_usd)`

Register an explicit USD cap for a named CrewAI agent. Returns `self` for chaining.

Enforced by `CrewAIExecutionAdapter` — `AgentBudgetExceededError` is raised **before** `Agent.execute_task` runs when the cap is exhausted. Use `agent.role` as the key to eliminate string mismatch risk. Spend is attributed to `ComponentBudget._spent` and visible in `budget.tree()`.

```python
with budget(max_usd=10.00) as b:
    b.agent(researcher.role, max_usd=2.00).agent(writer.role, max_usd=1.50)
    crew.kickoff(inputs={"topic": "AI"})
```

**Parameters:**
- `name` — agent name (use `agent.role` directly)
- `max_usd` — USD cap; must be positive

**Raises:** `ValueError` if `max_usd <= 0`

#### `task(name, max_usd)`

Register an explicit USD cap for a named CrewAI task. Returns `self` for chaining.

Enforced by `CrewAIExecutionAdapter` — `TaskBudgetExceededError` is raised **before** `Agent.execute_task` runs when the cap is exhausted. Use `task.name` as the key directly. Gate order: task cap is checked before agent cap (most specific first). Spend is attributed independently to both the task and the executing agent.

```python
with budget(max_usd=10.00) as b:
    b.task(research_task.name, max_usd=1.50).task(write_task.name, max_usd=0.80)
    crew.kickoff(inputs={"topic": "AI"})
```

**Parameters:**
- `name` — task name (use `task.name` directly)
- `max_usd` — USD cap; must be positive

**Raises:** `ValueError` if `max_usd <= 0`

#### `chain(name, max_usd)`

Register an explicit USD cap for a named LangChain chain. Returns `self` for chaining.

Enforced by `LangChainRunnerAdapter` — `ChainBudgetExceededError` is raised before the chain body executes when the cap is reached. Spend is attributed to `ComponentBudget._spent` and visible in `budget.tree()`.

```python
with budget(max_usd=10.00) as b:
    b.chain("retriever", max_usd=0.20).chain("summarizer", max_usd=1.00)
    chain.invoke({"query": "..."})
```

**Parameters:**
- `name` — chain name (must match the `run_name` or object name passed to `add_node`/invoked directly)
- `max_usd` — USD cap; must be positive

**Raises:** `ValueError` if `max_usd <= 0`

---

## `TemporalBudget` (rolling-window budgets)

Created via the `budget()` factory when a spec string or `window_seconds` is provided.

### Temporal factory forms

```python
# Spec string (per-cap windows)
with budget("$5/hr", name="api") as b: ...
with budget("$5/hr + 100 calls/hr", name="api") as b: ...

# Kwargs (single shared window)
with budget(max_usd=5.0, window_seconds=3600, name="api") as b: ...
with budget(max_usd=5.0, max_llm_calls=100, window_seconds=3600, name="api") as b: ...
```

`name=` is required for `TemporalBudget`.

### Supported counters in multi-cap specs

| Token | Counter | Example |
|---|---|---|
| `$N` or `N usd` | `usd` | `$5/hr` |
| `N calls` | `llm_calls` | `100 calls/hr` |
| `N tools` | `tool_calls` | `20 tools/hr` |
| `N tokens` | `tokens` | `50000 tokens/hr` |

### Using a custom backend

```python
from shekel.backends.redis import RedisBackend

backend = RedisBackend(url="redis://localhost:6379/0")

with budget("$5/hr", name="api", backend=backend) as b:
    run_agent()
```

---

## `RedisBackend`

Synchronous Redis-backed rolling-window budget backend for distributed enforcement.

### Constructor

```python
RedisBackend(
    url: str | None = None,          # defaults to REDIS_URL env var
    tls: bool = False,
    on_unavailable: str = "closed",  # "closed" | "open"
    circuit_breaker_threshold: int = 3,
    circuit_breaker_cooldown: float = 10.0,
)
```

| Parameter | Default | Description |
|---|---|---|
| `url` | `REDIS_URL` env | Redis connection URL |
| `tls` | `False` | Force TLS (`ssl=True`) |
| `on_unavailable` | `"closed"` | `"closed"` raises `BudgetExceededError`; `"open"` allows through |
| `circuit_breaker_threshold` | `3` | Consecutive errors before circuit opens |
| `circuit_breaker_cooldown` | `10.0` | Seconds before retrying after circuit opens |

### Example

```python
from shekel import budget
from shekel.backends.redis import RedisBackend

backend = RedisBackend()  # reads REDIS_URL from env

with budget("$5/hr + 100 calls/hr", name="api-tier", backend=backend) as b:
    run_agent()
```

### Methods

- `check_and_add(budget_name, amounts, limits, windows)` — atomically check + increment counters
- `get_state(budget_name)` — return `{counter: spent}` for all counters
- `reset(budget_name)` — delete the Redis hash for `budget_name`
- `close()` — close the Redis connection

**Raises:** `BudgetConfigMismatchError` if `budget_name` is already registered with different limits or windows.

---

## `AsyncRedisBackend`

Async version of `RedisBackend`. All public methods are coroutines. Suitable for FastAPI, async LangGraph, and other async contexts.

```python
from shekel.backends.redis import AsyncRedisBackend

backend = AsyncRedisBackend()

async with budget("$5/hr", name="api", backend=backend) as b:
    await run_async_agent()
```

Constructor and parameters are identical to `RedisBackend`.

---

## `@with_budget`

Decorator that wraps functions with a budget context.

### Signature

```python
def with_budget(
    max_usd: float | None = None,
    warn_at: float | None = None,
    on_warn: Callable[[float, float], None] | None = None,
    price_per_1k_tokens: dict[str, float] | None = None,
    fallback: dict[str, Any] | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
    max_llm_calls: int | None = None,
)
```

### Parameters

Same as `budget()` (decorator creates fresh budget per call).

### Examples

#### Basic Decorator

```python
from shekel import with_budget

@with_budget(max_usd=0.50)
def generate_summary(text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize: {text}"}],
    )
    return response.choices[0].message.content
```

#### Async Decorator

```python
@with_budget(max_usd=0.50)
async def async_generate(prompt: str) -> str:
    response = await client.chat.completions.create(...)
    return response.choices[0].message.content
```

#### With All Parameters

```python
@with_budget(
    max_usd=2.00,
    warn_at=0.8,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
    on_warn=my_warning_handler
)
def process_request(data: dict) -> str:
    ...
```

---

## `BudgetExceededError`

Exception raised when budget limit is exceeded.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `spent` | `float` | Total USD spent when limit was hit. |
| `limit` | `float` | The configured `max_usd`. |
| `model` | `str` | Model that triggered the error. |
| `tokens` | `dict[str, int]` | Token counts: `{"input": N, "output": N}`. |

### Example

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.50):
        expensive_operation()
except BudgetExceededError as e:
    print(f"Spent: ${e.spent:.4f}")
    print(f"Limit: ${e.limit:.2f}")
    print(f"Model: {e.model}")
    print(f"Tokens: {e.tokens['input']} in, {e.tokens['output']} out")
```

---

## `NodeBudgetExceededError`

Raised when a LangGraph node exceeds its registered USD cap. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `node_name` | `str` | Name of the node that exceeded its budget. |
| `spent` | `float` | Total USD spent when the cap was hit. |
| `limit` | `float` | The configured `max_usd` for this node. |

```python
from shekel import budget, NodeBudgetExceededError, BudgetExceededError

try:
    with budget(max_usd=10.00) as b:
        b.node("fetch", max_usd=0.10)
        run_fetch_node()
except NodeBudgetExceededError as e:
    print(f"Node '{e.node_name}' exceeded ${e.limit:.2f}")
except BudgetExceededError:
    # catches all budget errors including NodeBudgetExceededError
    ...
```

---

## `AgentBudgetExceededError`

Raised when an agent exceeds its registered USD cap. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `agent_name` | `str` | Name of the agent that exceeded its budget. |
| `spent` | `float` | Total USD spent when the cap was hit. |
| `limit` | `float` | The configured `max_usd` for this agent. |

---

## `TaskBudgetExceededError`

Raised when a task exceeds its registered USD cap. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `task_name` | `str` | Name of the task that exceeded its budget. |
| `spent` | `float` | Total USD spent when the cap was hit. |
| `limit` | `float` | The configured `max_usd` for this task. |

---

## `SessionBudgetExceededError`

Raised when an always-on agent session exceeds its rolling-window budget. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `agent_name` | `str` | Name of the agent session that exceeded its budget. |
| `spent` | `float` | Total USD spent when the cap was hit. |
| `limit` | `float` | The configured session budget. |
| `window` | `float \| None` | Rolling window duration in seconds, or `None`. |

---

## `ChainBudgetExceededError`

Raised when a LangChain chain exceeds its registered USD cap. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `chain_name` | `str` | Name of the chain that exceeded its budget. |
| `spent` | `float` | Total USD spent when the cap was hit. |
| `limit` | `float` | The configured `max_usd` for this chain. |

```python
from shekel import budget, ChainBudgetExceededError, BudgetExceededError

try:
    with budget(max_usd=10.00) as b:
        b.chain("retriever", max_usd=0.20)
        chain.invoke({"query": "..."})
except ChainBudgetExceededError as e:
    print(f"Chain '{e.chain_name}' exceeded ${e.limit:.2f}")
```

---

## `AgentLoopError`

Raised when the loop guard detects that the same tool has been called more than `loop_guard_max_calls` times within `loop_guard_window_seconds`. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `tool_name` | `str` | Name of the tool that triggered the loop detection. |
| `call_count` | `int` | Number of calls to this tool within the window at the time of blocking. |
| `window_seconds` | `float` | The configured rolling window duration. `0` means all-time cap. |
| `usd_spent` | `float` | Total USD spent when the loop was detected. |
| `framework` | `str` | Framework that dispatched the tool: `"langchain"`, `"mcp"`, `"crewai"`, `"openai-agents"`, or `"manual"`. |

```python
from shekel import budget, AgentLoopError, BudgetExceededError

try:
    with budget(loop_guard=True, loop_guard_max_calls=5):
        run_agent()
except AgentLoopError as e:
    print(f"Tool '{e.tool_name}' called {e.call_count}x in {e.window_seconds}s")
except BudgetExceededError:
    ...  # catches all budget errors including AgentLoopError
```

---

## `SpendVelocityExceededError`

Raised when the measured spend velocity (USD per minute) exceeds the `max_velocity` threshold. Subclass of `BudgetExceededError`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `velocity_per_min` | `float` | Measured spend velocity in USD/min at the time of blocking. Always normalized to per-minute regardless of the spec unit. |
| `limit_per_min` | `float` | The configured velocity limit in USD/min. |
| `window_seconds` | `float` | Rolling window over which velocity was measured (seconds). |
| `usd_spent` | `float` | Total USD spent when blocked. |
| `elapsed_seconds` | `float` | Seconds elapsed since the budget context opened. |

```python
from shekel import budget, SpendVelocityExceededError, BudgetExceededError

try:
    with budget(max_velocity="$0.50/min"):
        run_agent()
except SpendVelocityExceededError as e:
    print(f"Velocity: ${e.velocity_per_min:.4f}/min (limit: ${e.limit_per_min:.4f}/min)")
    print(f"Spent:    ${e.usd_spent:.4f} over {e.elapsed_seconds:.1f}s")
except BudgetExceededError:
    ...  # catches all budget errors including SpendVelocityExceededError
```

---

## `BudgetConfigMismatchError`

Raised by `RedisBackend` / `AsyncRedisBackend` when a budget name is already registered with different limits or windows. Subclass of `BudgetExceededError`.

```python
from shekel.exceptions import BudgetConfigMismatchError

try:
    with budget("$5/hr", name="api", backend=backend):
        run_agent()
except BudgetConfigMismatchError:
    # Budget "api" was previously registered with different caps.
    # Call backend.reset("api") to clear existing state.
    backend.reset("api")
```

**To resolve:** call `backend.reset(budget_name)` to delete the existing Redis state, then retry.

---

## Type Signatures

For type checking with mypy, pyright, etc:

```python
from shekel import budget, with_budget, BudgetExceededError
from typing import Callable

# Budget context manager
b: budget = budget(max_usd=1.00)

# Decorator
@with_budget(max_usd=0.50)
def my_func() -> str:
    ...

# Callbacks
def warn_callback(spent: float, limit: float) -> None:
    ...

def fallback_callback(spent: float, limit: float, fallback: str) -> None:
    ...
```

---

## Next Steps

- [Basic Usage](usage/basic-usage.md) - Learn the fundamentals
- [Nested Budgets](usage/nested-budgets.md) - Hierarchical tracking for multi-stage workflows
- [Budget Enforcement](usage/budget-enforcement.md) - Hard caps and warnings
- [Fallback Models](usage/fallback-models.md) - Automatic model switching
