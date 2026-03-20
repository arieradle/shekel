---
title: OpenAI Agents SDK Budget Control – Per-Agent Circuit Breaking
description: "Enforce hard USD caps on OpenAI Agents SDK runners. Per-agent circuit breaking with b.agent(). AgentBudgetExceededError raised before the agent executes. Zero config."
tags:
  - openai
  - openai-agents
  - agent-frameworks
  - circuit-breaker
  - budget-enforcement
---

# OpenAI Agents SDK Integration

Shekel integrates with the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) to enforce per-agent and global spend limits on multi-agent workflows — with zero changes to your agent definitions.

## Installation

```bash
pip install shekel[openai] openai-agents
```

## Zero-config global enforcement

Wrap any `Runner` call with `budget()` — shekel auto-detects the OpenAI Agents SDK and patches `Runner.run`, `Runner.run_sync`, and `Runner.run_streamed` on context entry:

```python
from agents import Agent, Runner
from shekel import budget, BudgetExceededError

researcher = Agent(name="researcher", instructions="Find key facts about the topic.")

try:
    with budget(max_usd=5.00) as b:
        result = await Runner.run(researcher, "Research quantum computing")
    print(f"Done. Spent: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: {e}")
```

Shekel patches `Runner.run`, `Runner.run_sync`, and `Runner.run_streamed` transparently at `budget().__enter__()` and restores them at `__exit__()`. No agent or runner changes are needed.

## Per-agent caps

Register caps keyed by `agent.name` — using the attribute directly eliminates string mismatch risk:

```python
from shekel.exceptions import AgentBudgetExceededError

researcher = Agent(name="researcher", instructions="Find key facts.")
writer = Agent(name="writer", instructions="Write a concise summary.")

try:
    with budget(max_usd=5.00, name="agents") as b:
        b.agent(researcher.name, max_usd=2.00)
        b.agent(writer.name, max_usd=1.00)
        research_result = await Runner.run(researcher, "Research AI safety")
        write_result = await Runner.run(writer, f"Summarize: {research_result.final_output}")
    print(f"Done. Spent: ${b.spent:.4f}")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' exceeded cap: ${e.spent:.4f} / ${e.limit:.2f}")
except BudgetExceededError as e:
    print(f"Global budget exceeded: {e}")

print(b.tree())
# agents: $2.84 / $5.00  (direct: $0.00)
#   [agent] researcher: $1.92 / $2.00  (96.0%)
#   [agent] writer:     $0.92 / $1.00  (92.0%)
```

`AgentBudgetExceededError` is raised **before** the agent run executes — the runner body never starts when the cap is already exhausted. It subclasses `BudgetExceededError`, so existing `except BudgetExceededError` blocks catch it automatically.

## Multi-agent pipeline

Combine multiple agents, each with its own cap:

```python
from shekel.exceptions import AgentBudgetExceededError

planner = Agent(name="planner", instructions="Break down the task into subtasks.")
researcher = Agent(name="researcher", instructions="Research each subtask.")
writer = Agent(name="writer", instructions="Write the final report.")

try:
    with budget(max_usd=10.00, name="pipeline") as b:
        b.agent(planner.name, max_usd=0.50)
        b.agent(researcher.name, max_usd=4.00)
        b.agent(writer.name, max_usd=2.00)

        plan = await Runner.run(planner, "Build a report on renewable energy")
        research = await Runner.run(researcher, plan.final_output)
        report = await Runner.run(writer, research.final_output)

    print(f"Pipeline complete. Spent: ${b.spent:.4f}")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' over budget: ${e.spent:.4f} / ${e.limit:.2f}")
except BudgetExceededError as e:
    print(f"Global cap hit: {e}")

print(b.tree())
# pipeline: $5.23 / $10.00  (direct: $0.00)
#   [agent] planner:    $0.08 / $0.50  (16.0%)
#   [agent] researcher: $3.82 / $4.00  (95.5%)
#   [agent] writer:     $1.33 / $2.00  (66.5%)
```

## Spend attribution with `b.tree()`

`b.tree()` provides a live breakdown of spend across all registered agents:

```python
with budget(max_usd=10.00, name="workflow") as b:
    b.agent("researcher", max_usd=4.00)
    b.agent("writer", max_usd=3.00)
    # ... run agents ...

print(b.tree())
# workflow: $6.10 / $10.00  (direct: $0.00)
#   [agent] researcher: $3.90 / $4.00  (97.5%)
#   [agent] writer:     $2.20 / $3.00  (73.3%)
```

Use this after any run — or during a run inside a `on_warn` callback — to see exactly where spend is going.

## Async and sync

Shekel patches all three `Runner` entry points. Use whichever fits your runtime:

=== "Async (`Runner.run`)"

    ```python
    import asyncio
    from agents import Agent, Runner
    from shekel import budget

    agent = Agent(name="assistant", instructions="Be helpful.")

    async def main():
        with budget(max_usd=2.00) as b:
            result = await Runner.run(agent, "Explain machine learning")
        print(f"Spent: ${b.spent:.4f}")

    asyncio.run(main())
    ```

=== "Sync (`Runner.run_sync`)"

    ```python
    from agents import Agent, Runner
    from shekel import budget

    agent = Agent(name="assistant", instructions="Be helpful.")

    with budget(max_usd=2.00) as b:
        result = Runner.run_sync(agent, "Explain machine learning")

    print(f"Spent: ${b.spent:.4f}")
    ```

Both methods respect the same budget context — spend from `Runner.run_sync` and `Runner.run` accumulates into the same `b.spent`.

## Streaming

`Runner.run_streamed` is also patched. Spend is attributed **after you finish iterating** the stream — not before:

```python
from agents import Agent, Runner
from shekel import budget

agent = Agent(name="assistant", instructions="Be helpful.")

with budget(max_usd=2.00) as b:
    result = Runner.run_streamed(agent, "Write a short poem")

    async for event in result.stream_events():
        if event.type == "raw_response_event":
            print(event.data, end="", flush=True)

    print()

print(f"Spent: ${b.spent:.4f}")
```

!!! warning "Streaming and budget enforcement"
    Because the OpenAI Agents SDK only returns token usage after the stream completes, `BudgetExceededError` cannot fire mid-stream. The budget gate fires at the **end** of each streamed run. Use `max_usd` as a ceiling across multiple streamed calls rather than expecting intra-stream interruption.

## Exception reference

| Exception | Raised when | Fields |
|---|---|---|
| `AgentBudgetExceededError` | Agent cap exhausted | `agent_name`, `spent`, `limit` |
| `BudgetExceededError` | Global budget exhausted | `spent`, `limit`, `model` |

Both subclass `BudgetExceededError`, so a single `except BudgetExceededError` catches them all.

```python
from shekel.exceptions import AgentBudgetExceededError
from shekel import BudgetExceededError

try:
    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        result = await Runner.run(researcher, "Research topic")
except AgentBudgetExceededError as e:
    print(f"Agent: {e.agent_name}")
    print(f"Spent: ${e.spent:.4f}")
    print(f"Limit: ${e.limit:.2f}")
except BudgetExceededError as e:
    print(f"Global cap: ${e.limit:.2f}")
```

## `warn_only` mode

Use `warn_only=True` in staging or development to observe spend without blocking:

```python
with budget(max_usd=2.00, warn_only=True) as b:
    result = await Runner.run(agent, "Research topic")
# Never raises — logs a warning when $2.00 is exceeded instead

print(f"Would have blocked at: ${b.spent:.4f}")
```

Switch `warn_only=False` (the default) in production to enforce hard caps.

## Nested budgets

Per-agent caps are enforced inside the parent ceiling. A child budget's per-agent spend rolls up to the parent automatically:

```python
with budget(max_usd=10.00, name="outer") as outer:
    with budget(max_usd=5.00, name="inner") as inner:
        inner.agent("researcher", max_usd=2.00)
        result = await Runner.run(researcher, "Research AI")
    # inner spend rolls up to outer automatically
    print(f"Inner: ${inner.spent:.4f}")
    print(f"Outer: ${outer.spent:.4f}")  # includes inner's spend
```

The outer budget acts as a ceiling — if it has $3.00 remaining and the inner budget requests $5.00, the inner is silently capped to $3.00.

## Next Steps

- [CrewAI Integration](crewai.md) — per-agent and per-task circuit breaking
- [LangGraph Integration](langgraph.md) — per-node circuit breaking
- [Loop Guard](../usage/loop-guard.md) — detect and stop agent loops
- [API Reference](../api-reference.md)
