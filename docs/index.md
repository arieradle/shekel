---
title: Shekel – LLM Budget Control for AI Agents
description: "Open-source Python library for LLM budget control, token budgeting, and AI agent cost governance for OpenAI, Anthropic, LangChain, LangGraph, and modern LLMOps systems."
tags:
  - getting-started
  - budget-enforcement
  - agent-safety
  - openai
  - anthropic
  - langchain
  - langgraph
  - crewai
  - litellm
  - cost-tracking
---

# Shekel

**The missing safety layer for production AI agents.**

```python
with budget(max_usd=5.00):
    run_my_agent()  # hard stop at $5 — no SDK changes, no config
```

```bash
shekel run agent.py --budget 5   # or enforce without touching code at all
```

---

## The Story

I spent **$47** debugging a LangGraph retry loop. The agent kept failing, LangGraph kept retrying, and OpenAI kept charging — all while I slept.

I built shekel so you don't have to learn that lesson yourself.

Every serious AI agent needs the same things: spending limits, loop detection, velocity guards, per-component circuit breakers. Shekel is the library that provides all of it, in one import, with zero setup.

---

## What Shekel Does

<div class="grid cards" markdown>

-   :material-lightning-bolt:{ .lg .middle } **Hard Budget Caps**

    ---

    Wrap any agent in a context manager. Shekel intercepts every LLM call, tracks exact spend, and raises `BudgetExceededError` the moment you cross the limit. No SDK changes. No config.

    ```python
    with budget(max_usd=5.00, warn_at=0.8) as b:
        run_my_agent()
    # warns at $4.00, hard stops at $5.00
    ```

-   :material-swap-horizontal:{ .lg .middle } **Automatic Model Fallback**

    ---

    Don't crash — switch. Define a cheaper fallback model and shekel transparently rewrites the `model` parameter when the threshold is hit.

    ```python
    with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
        run_my_agent()
    # gpt-4o → gpt-4o-mini at $0.80, hard stop at $1.00
    ```

-   :material-tree:{ .lg .middle } **Nested Budgets**

    ---

    Break multi-stage pipelines into per-stage budgets. Children auto-cap to the parent's remaining balance. `b.tree()` gives you a live visual breakdown.

    ```python
    with budget(max_usd=10.00, name="pipeline") as pipeline:
        with budget(max_usd=2.00, name="research"):
            search_and_analyze()
        with budget(max_usd=5.00, name="synthesis"):
            write_report()

    print(pipeline.tree())
    # pipeline: $4.80 / $10.00
    #   research:  $1.20 / $2.00
    #   synthesis: $3.60 / $5.00
    ```

-   :material-tools:{ .lg .middle } **Tool Call Budgets**

    ---

    Cap agent tool dispatches before they spiral. Auto-intercepted for LangChain, MCP, CrewAI, and OpenAI Agents SDK. One decorator for plain Python.

    ```python
    @tool(price=0.01)
    def web_search(query: str) -> str: ...

    with budget(max_usd=5.00, max_tool_calls=20) as b:
        run_my_agent()
    # ToolBudgetExceededError on call 21 — before the tool runs
    ```

-   :material-refresh-auto:{ .lg .middle } **Loop Guard**

    ---

    Catches stuck agents before they drain your budget. A per-tool rolling-window counter fires `AgentLoopError` when the same tool repeats too many times — no matter what the total spend is.

    ```python
    with budget(max_usd=5.00, loop_guard=True) as b:
        run_my_agent()
    # AgentLoopError if any tool repeats 5x in 60s
    ```

-   :material-speedometer:{ .lg .middle } **Velocity Circuit Breaker**

    ---

    Cap how fast you burn money, not just how much. A bursty agent can blow through `max_usd` before you can react — `max_velocity` stops it in seconds.

    ```python
    with budget(max_usd=50.00, max_velocity="$1/min") as b:
        run_my_agent()
    # SpendVelocityExceededError if burn rate > $1/min
    ```

-   :material-clock-time-four:{ .lg .middle } **Temporal (Rolling-Window) Budgets**

    ---

    Enforce `$5/hr` per user, per API tier, or per agent. The string DSL handles multi-cap windows. `BudgetExceededError` carries `retry_after` so callers know when the window resets.

    ```python
    api_budget = budget("$5/hr + 100 calls/hr", name="api-tier")
    async with api_budget:
        response = await client.chat.completions.create(...)
    ```

-   :material-database:{ .lg .middle } **Distributed Budgets**

    ---

    Enforce shared limits atomically across multiple processes, workers, or containers. One Lua script per call — no race conditions.

    ```python
    from shekel.backends.redis import RedisBackend

    backend = RedisBackend()  # reads REDIS_URL from env
    with budget("$5/hr", name="api-tier", backend=backend):
        client.chat.completions.create(...)
    ```

-   :material-graph:{ .lg .middle } **Framework Circuit Breakers**

    ---

    Per-node, per-chain, per-agent, and per-task caps. Shekel patches your framework transparently — zero changes to your LangGraph graphs, CrewAI crews, or LangChain chains.

    ```python
    with budget(max_usd=10.00) as b:
        b.node("fetch_data", max_usd=0.50)   # LangGraph
        b.chain("retriever", max_usd=0.20)   # LangChain
        b.agent("researcher", max_usd=2.00)  # CrewAI / OAI Agents
        b.task("summarize", max_usd=0.50)    # CrewAI
    ```

-   :material-console:{ .lg .middle } **CLI — Zero Code Changes**

    ---

    Run any Python agent under a budget from the command line. CI-friendly exit codes. Works with Docker, GitHub Actions, and shell scripts.

    ```bash
    shekel run agent.py --budget 5
    AGENT_BUDGET_USD=5 shekel run agent.py
    ```

-   :material-chart-line:{ .lg .middle } **OpenTelemetry Metrics**

    ---

    9 OTel instruments covering cost, utilization, spend rate, fallback activations, and loop events. Compatible with Prometheus, Grafana, Datadog, and any OTel backend.

    ```python
    from shekel.otel import ShekelMeter
    meter = ShekelMeter()  # silent no-op if OTel is absent
    ```

-   :material-telescope:{ .lg .middle } **Langfuse Integration**

    ---

    Per-call cost streaming, circuit-break events, and budget hierarchy in Langfuse spans — see exactly where your budget breaks.

    ```python
    from shekel.integrations.langfuse import LangfuseAdapter
    AdapterRegistry.register(LangfuseAdapter(client=lf))
    ```

</div>

---

## Works with Everything

If it calls OpenAI or Anthropic under the hood, shekel sees it — zero integration code needed.

| Provider | Framework | |
|---|---|---|
| OpenAI · Anthropic · Gemini | LangChain · LangGraph | Auto-patched |
| HuggingFace · LiteLLM · Groq | CrewAI · OpenAI Agents SDK | Auto-patched |
| MCP · AutoGen · LlamaIndex | Any custom wrapper | Auto-patched |

---

## Quick Start

### Install

=== "OpenAI"

    ```bash
    pip install shekel[openai]
    ```

=== "Anthropic"

    ```bash
    pip install shekel[anthropic]
    ```

=== "LiteLLM (100+ providers)"

    ```bash
    pip install shekel[litellm]
    ```

=== "All"

    ```bash
    pip install shekel[all]
    ```

=== "CLI only"

    ```bash
    pip install shekel[cli]
    ```

=== "400+ models"

    ```bash
    pip install shekel[all-models]
    ```

### Your first budget

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=1.00, warn_at=0.8) as b:
        run_my_agent()
    print(f"Spent: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: ${e.spent:.4f} / ${e.limit:.2f}")
```

No API keys. No external services. No background threads. Nothing leaves your machine.

---

## Why Shekel?

Production AI agents fail in predictable ways. Shekel is designed around those failure modes:

| Failure Mode | How Shekel Stops It |
|---|---|
| Retry loop runs overnight | `max_usd` hard cap |
| Same tool called 500 times in a loop | `loop_guard=True` |
| Agent bursts $40 in two minutes | `max_velocity="$1/min"` |
| One LangGraph node consumes the entire budget | `b.node("name", max_usd=X)` |
| Expensive model blows your budget mid-task | `fallback={"model": "gpt-4o-mini"}` |
| Multi-tenant API needs per-user rate limits | Redis backend + temporal budgets |
| CI pipeline needs cost enforcement | `shekel run agent.py --budget 5` |

All of these work together. `max_usd` + `loop_guard` + `max_velocity` are independent guards that fire on whichever condition triggers first.

---

## The Spend Summary

```python
with budget(max_usd=5.00) as b:
    run_my_agent()

print(b.summary())
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
shekel spend summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total: $1.2450 / $5.00 (25%)

gpt-4o:       $1.1320  (5 calls)
  Input:  45.2k tokens → $0.1130
  Output: 11.3k tokens → $1.1320

Tool spend:   $0.1130  (9 tool calls)
  web_search  $0.090  (9 calls)  [langchain]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Or machine-readable for log pipelines:

```bash
shekel run agent.py --budget 5 --output json
# {"spent": 1.245, "limit": 5.0, "calls": 5, "tool_calls": 9, "status": "ok"}
```

---

## Dive Deeper

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **[Quick Start Guide](quickstart.md)**

    ---

    Step-by-step examples — tracking, enforcement, fallback, nested budgets, async, streaming.

-   :material-book-open-variant:{ .lg .middle } **[Usage Guide](usage/basic-usage.md)**

    ---

    Deep-dives into every feature: enforcement modes, tool budgets, loop guard, velocity, temporal budgets.

-   :material-puzzle:{ .lg .middle } **[Integrations](integrations/langgraph.md)**

    ---

    Framework-specific guides for LangGraph, CrewAI, LangChain, OpenAI Agents SDK, Gemini, and more.

-   :material-api:{ .lg .middle } **[API Reference](api-reference.md)**

    ---

    Complete documentation of all parameters, properties, methods, and exceptions.

</div>

---

## Supported Models

Built-in pricing for GPT-4o, GPT-4o-mini, o1, o3, Claude 3.5/3/3.7 Sonnet, Claude 3 Haiku/Opus, Gemini 2.0/2.5 Flash/Pro, and more.

```bash
shekel models                    # list all bundled models and pricing
shekel models --provider openai
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
```

Install `shekel[all-models]` for [400+ models via tokencost](https://github.com/AgentOps-AI/tokencost). [See full model list →](models.md)

---

## What's New

See [CHANGELOG](changelog.md) for the full release history.

**v1.1.0** — Loop Guard, Spend Velocity, OpenAI Agents SDK per-agent circuit breaking
**v1.0.2** — LangGraph node caps, CrewAI agent/task caps, LangChain chain caps, Redis distributed budgets
**v0.2.9** — CLI `shekel run`; Docker support
**v0.2.8** — Tool budgets, temporal budgets, OpenTelemetry metrics

---

## Community

- **GitHub**: [arieradle/shekel](https://github.com/arieradle/shekel)
- **PyPI**: [pypi.org/project/shekel](https://pypi.org/project/shekel/)
- **Issues & PRs**: [github.com/arieradle/shekel/issues](https://github.com/arieradle/shekel/issues)
- **Contributing**: [See the guide](contributing.md)

---

MIT License
