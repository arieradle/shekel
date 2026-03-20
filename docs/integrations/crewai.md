---
title: CrewAI Budget Control – Per-Agent and Per-Task Spend Caps
description: "Enforce LLM spend limits on CrewAI multi-agent workflows. Per-agent and per-task USD caps with AgentBudgetExceededError and TaskBudgetExceededError. Zero crew changes required."
tags:
  - crewai
  - agent-frameworks
  - circuit-breaker
  - budget-enforcement
---

# CrewAI Integration

Shekel integrates with [CrewAI](https://github.com/joaomdmoura/crewAI) to enforce per-agent, per-task, and global spend limits on multi-agent workflows — with zero changes to your crew definition.

## Installation

```bash
pip install shekel[openai] crewai
```

## Zero-config global cap

Wrap any crew execution with `budget()` — shekel auto-detects CrewAI and enforces the cap:

```python
from crewai import Agent, Task, Crew
from shekel import budget, BudgetExceededError

researcher = Agent(role="Senior Researcher", goal="Find key facts", backstory="...", llm="gpt-4o-mini")
writer = Agent(role="Content Writer", goal="Write a summary", backstory="...", llm="gpt-4o-mini")

research_task = Task(name="research", description="Research: {topic}", expected_output="3 facts", agent=researcher)
write_task = Task(name="write", description="Write a paragraph summary", expected_output="1 paragraph", agent=writer)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task])

try:
    with budget(max_usd=5.00) as b:
        crew.kickoff(inputs={"topic": "climate change"})
    print(f"Done. Spent: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: {e}")
```

Shekel patches `Agent.execute_task` transparently at `budget().__enter__()` and restores it at `__exit__()`. No crew or agent changes are needed.

## Per-agent caps

Register caps keyed by `agent.role` — using the attribute directly eliminates string mismatch risk:

```python
from shekel.exceptions import AgentBudgetExceededError

try:
    with budget(max_usd=5.00, name="agents") as b:
        b.agent(researcher.role, max_usd=2.00)
        b.agent(writer.role, max_usd=1.00)
        crew.kickoff(inputs={"topic": "quantum computing"})
    print(f"Done. Spent: ${b.spent:.4f}")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' exceeded cap: ${e.spent:.4f} / ${e.limit:.2f}")
except BudgetExceededError as e:
    print(f"Global budget exceeded: {e}")

print(b.tree())
# agents: $2.84 / $5.00  (direct: $0.00)
#   [agent] Senior Researcher: $1.92 / $2.00  (96.0%)
#   [agent] Content Writer:    $0.92 / $1.00  (92.0%)
```

`AgentBudgetExceededError` is raised **before** the agent executes — the agent body never runs when the cap is already exhausted. It subclasses `BudgetExceededError`, so existing `except BudgetExceededError` blocks catch it automatically.

## Per-agent + per-task caps

Combine agent and task caps. Use `task.name` as the key directly:

```python
from shekel.exceptions import AgentBudgetExceededError, TaskBudgetExceededError

try:
    with budget(max_usd=5.00, name="full") as b:
        b.agent(researcher.role, max_usd=2.00)
        b.agent(writer.role, max_usd=1.00)
        b.task(research_task.name, max_usd=1.50)
        b.task(write_task.name, max_usd=0.80)
        crew.kickoff(inputs={"topic": "renewable energy"})
    print(f"Done. Spent: ${b.spent:.4f}")
except TaskBudgetExceededError as e:
    print(f"Task '{e.task_name}' exceeded cap: ${e.spent:.4f} / ${e.limit:.2f}")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' exceeded cap")
except BudgetExceededError as e:
    print(f"Global budget exceeded: {e}")
```

Gate order (most specific first): **task cap → agent cap → global budget**. Spend delta from each execution is attributed independently to both the agent and the task — they represent different aggregation views of the same spend.

## Spend breakdown with `b.tree()`

```python
print(b.tree())
# full: $3.42 / $5.00  (direct: $0.00)
#   [agent] Senior Researcher: $2.10 / $2.00  (105.0%)
#   [agent] Content Writer:    $1.32 / $1.00  (132.0%)
#   [task]  research:          $2.10 / $1.50  (140.0%)
#   [task]  write:             $1.32 / $0.80  (165.0%)
```

`b.tree()` shows live spend for every registered component alongside its cap and utilization percentage.

## Nested budgets

Per-agent and per-task caps are inherited through the parent chain:

```python
with budget(max_usd=10.00, name="outer") as outer:
    with budget(max_usd=5.00, name="inner") as inner:
        inner.agent(researcher.role, max_usd=2.00)
        crew.kickoff(inputs={"topic": "AI"})
    # inner spend rolls up to outer automatically
```

## Warnings for unnamed tasks

If a `Task` has no `name` attribute and task caps are registered, shekel emits a `UserWarning`:

```
shekel: task has no name (description: 'Research the topic...') — set task.name to apply caps.
```

Always set `task.name` when using `b.task()` caps to avoid silent misses.

## Exception hierarchy

| Exception | Raised when | Fields |
|---|---|---|
| `AgentBudgetExceededError` | Agent cap exhausted | `agent_name`, `spent`, `limit` |
| `TaskBudgetExceededError` | Task cap exhausted | `task_name`, `spent`, `limit` |
| `BudgetExceededError` | Global budget exhausted | `spent`, `limit`, `model` |

All three subclass `BudgetExceededError`, so a single `except BudgetExceededError` catches them all.

## Next Steps

- [LangGraph Integration](langgraph.md) — per-node circuit breaking
- [Budget Enforcement](../usage/budget-enforcement.md)
- [API Reference](../api-reference.md)
