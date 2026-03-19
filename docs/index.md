---
title: Shekel – LLM Budget Control for AI Agents
description: Open-source Python library for LLM budget control, token budgeting, and AI agent cost governance for OpenAI, Anthropic, LangChain, LangGraph, and modern LLMOps systems.
---

<!--
Agent discovery metadata:

shekel python library
llm budget control
ai agent cost control
llm cost governance
token budgeting
openai usage limits
anthropic cost control
langchain budget guardrails
langgraph agent budgets
langfuse observability integration
llmops governance
ai spend guardrails
agentic systems
cost enforcement
usage quotas
-->

# Shekel

**LLM budget enforcement and cost tracking for Python. One line. Zero config.**

```python
with budget(max_usd=1.00):
    run_my_agent()  # raises BudgetExceededError if spend exceeds $1.00
```

Or enforce from the command line — no code changes needed:

```bash
shekel run agent.py --budget 1
```

---

## The Story

I spent **$47** debugging a LangGraph retry loop. The agent kept failing, LangGraph kept retrying, and OpenAI kept charging — all while I slept. 

I built shekel so you don't have to learn that lesson yourself.

---

## Features

<div class="grid cards single-col" markdown>

-   :material-lightning-bolt:{ .lg .middle } **Zero Config**

    ---

    One line of code. No API keys, no external services, no setup.

    ```python
    with budget(max_usd=1.00):
        run_agent()
    # or: shekel run agent.py --budget 1
    ```

-   :material-shield-check:{ .lg .middle } **Budget Enforcement**

    ---

    Hard caps, soft warnings, or track-only mode. You control the spend.

    ```python
    with budget(max_usd=1.00, warn_at=0.8):
        run_agent()
    ```

-   :material-swap-horizontal:{ .lg .middle } **Smart Fallback**

    ---

    Automatically switch to cheaper models instead of crashing.

    ```python
    with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
        run_agent()
    ```

-   :material-tree:{ .lg .middle } **Nested Budgets**

    ---

    Hierarchical tracking for multi-stage workflows.

    ```python
    with budget(max_usd=10, name="workflow"):
        with budget(max_usd=2, name="research"):
            run_research()
        with budget(max_usd=5, name="analysis"):
            run_analysis()
    ```

-   :material-telescope:{ .lg .middle } **Langfuse Integration**

    ---

    Circuit-break events, per-call spend streaming, and budget hierarchy in Langfuse — see exactly where your budget breaks.

    ```python
    from shekel.integrations.langfuse import LangfuseAdapter

    adapter = LangfuseAdapter(client=lf)
    AdapterRegistry.register(adapter)
    # Automatic cost tracking and budget monitoring!
    ```

-   :material-clock-time-four:{ .lg .middle } **Temporal Budgets**

    ---

    Rolling-window spend limits — enforce `$5/hr` per user, API tier, or agent. Hard stop with `retry_after` in the error.

    ```python
    tb = budget("$5/hr", name="api-tier")
    async with tb:
        response = await client.chat(...)
    ```

-   :material-tools:{ .lg .middle } **Tool Budgets**

    ---

    Cap agent tool calls before they bankrupt you. Auto-intercepts LangChain, MCP, CrewAI, OpenAI Agents. `@tool` decorator for plain Python.

    ```python
    with budget(max_tool_calls=50):
        run_agent()  # ToolBudgetExceededError on call 51
    ```

-   :material-chart-line:{ .lg .middle } **OpenTelemetry Metrics**

    ---

    Export cost, utilization, spend rate, and fallback data via OTel instruments — compatible with Prometheus, Grafana, Datadog, and any OTel backend.

    ```python
    from shekel.otel import ShekelMeter
    meter = ShekelMeter()  # zero config
    ```

-   :material-speedometer:{ .lg .middle } **Framework Agnostic**

    ---

    Works with LangGraph, CrewAI, AutoGen, LlamaIndex, Haystack, and any framework that calls OpenAI, Anthropic, or LiteLLM.

-   :material-web:{ .lg .middle } **Async & Streaming**

    ---

    Full support for async/await patterns and streaming responses.

    ```python
    async with budget(max_usd=1.00):
        await run_async_agent()
    ```

</div>

---

## Quick Start

### Installation

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

=== "Both"

    ```bash
    pip install shekel[all]
    ```

=== "All Models (400+)"

    ```bash
    pip install shekel[all-models]
    ```

### Basic Usage

```python
from shekel import budget, BudgetExceededError

# Enforce a hard cap
try:
    with budget(max_usd=1.00, warn_at=0.8) as b:
        run_my_agent()
    print(f"Spent ${b.spent:.4f}")
except BudgetExceededError as e:
    print(e)

# Track spend without enforcing a limit
with budget() as b:
    run_my_agent()
print(f"Cost: ${b.spent:.4f}")

# Decorator
from shekel import with_budget

@with_budget(max_usd=0.10)
def call_llm():
    ...
```

### See It In Action

```python
import openai
from shekel import budget

client = openai.OpenAI()

with budget(max_usd=0.10) as b:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.choices[0].message.content)

print(f"Total cost: ${b.spent:.4f}")
print(f"Remaining: ${b.remaining:.4f}")
```

---

## Why Shekel?

| Problem | Solution |
|---------|----------|
| Agent retry loops drain your wallet | Hard budget caps stop runaway costs |
| No visibility into LLM spending | Track every API call automatically |
| Expensive models blow your budget | Automatic fallback to cheaper models |
| Need to enforce spend limits | Context manager raises on budget exceeded |
| Multi-step workflows need session budgets | Budgets always accumulate across runs |

---

## What's New in v1.1.0

<div class="grid cards" markdown>

-   :material-robot-excited:{ .lg .middle } **OpenAI Agents SDK — Per-Agent Circuit Breaking**

    ---

    Automatic patching of `Runner.run`, `run_sync`, and `run_streamed`. Per-agent caps with `b.agent()`. `AgentBudgetExceededError` raised before the agent executes. Zero changes to your agent definitions.

    ```python
    with budget(max_usd=5.00) as b:
        b.agent("researcher", max_usd=2.00)
        b.agent("writer", max_usd=1.00)
        result = await Runner.run(researcher, "Research AI")

    print(b.tree())
    # [agent] researcher: $1.92 / $2.00 (96.0%)
    # [agent] writer:     $0.85 / $1.00 (85.0%)
    ```

    [OpenAI Agents SDK Integration →](integrations/openai-agents.md)

-   :material-refresh-auto:{ .lg .middle } **Loop Guard — Agent Loop Detection**

    ---

    Per-tool rolling-window counter catches stuck agents before they drain your budget. `AgentLoopError` raised before the tool executes on the Nth repeat call.

    ```python
    with budget(max_usd=5.00, loop_guard=True) as b:
        run_my_agent()  # AgentLoopError if any tool repeats 5x in 60s

    print(b.loop_guard_counts)
    # {'web_search': 3, 'read_file': 1}
    ```

    [Loop Guard →](usage/loop-guard.md)

-   :material-speedometer:{ .lg .middle } **Spend Velocity — Burn-Rate Circuit Breaker**

    ---

    Cap how fast you spend, not just how much. `"$0.50/min"` stops a bursty agent after the first half-dollar per minute. Normalized `velocity_per_min` in the exception.

    ```python
    with budget(max_usd=50.00, max_velocity="$1/min") as b:
        run_my_agent()  # SpendVelocityExceededError if burn > $1/min
    ```

    [Spend Velocity →](usage/spend-velocity.md)

</div>

---

## What's New in v1.0.2

<div class="grid cards" markdown>

-   :material-graph:{ .lg .middle } **LangGraph Node-Level Circuit Breaking**

    ---

    Per-node USD caps enforced automatically. `NodeBudgetExceededError` raised before the node body runs. Zero graph changes required.

    ```python
    with budget(max_usd=10.00) as b:
        b.node("fetch", max_usd=0.50)
        b.node("summarize", max_usd=1.00)
        app.invoke(state)

    print(b.tree())
    # [node] fetch:    $0.12 / $0.50 (24.0%)
    # [node] summarize: $0.72 / $1.00 (72.0%)
    ```

-   :material-robot:{ .lg .middle } **CrewAI Agent/Task Circuit Breaking**

    ---

    Per-agent and per-task USD caps enforced automatically. `AgentBudgetExceededError` / `TaskBudgetExceededError` raised before the agent executes. Zero crew changes required.

    ```python
    with budget(max_usd=5.00) as b:
        b.agent(researcher.role, max_usd=2.00)
        b.task(research_task.name, max_usd=1.50)
        crew.kickoff(inputs={"topic": "AI"})

    print(b.tree())
    # [agent] Senior Researcher: $1.92 / $2.00 (96.0%)
    # [task]  research:          $1.92 / $1.50 (128.0%)
    ```

-   :material-link-variant:{ .lg .middle } **LangChain Per-Chain Circuit Breaking**

    ---

    Per-chain USD caps enforced automatically. `ChainBudgetExceededError` raised before the chain body runs. Zero changes to your chains required.

    ```python
    with budget(max_usd=5.00) as b:
        b.chain("retriever",  max_usd=0.20)
        b.chain("summarizer", max_usd=1.00)
        retriever_chain.invoke({"query": "..."})
        summarizer_chain.invoke({"doc": "..."})
    ```

-   :material-database:{ .lg .middle } **Distributed Budgets — Redis**

    ---

    Enforce spend limits atomically across multiple processes or containers. Atomic Lua-script enforcement, circuit breaker, fail-closed/open.

    ```python
    from shekel.backends.redis import RedisBackend

    backend = RedisBackend()  # reads REDIS_URL from env
    with budget("$5/hr + 100 calls/hr", name="api", backend=backend) as b:
        response = client.chat.completions.create(...)
    ```

-   :material-alert-decagram:{ .lg .middle } **Level-Specific Exceptions**

    ---

    `NodeBudgetExceededError`, `AgentBudgetExceededError`, `TaskBudgetExceededError`, `ChainBudgetExceededError` — all subclass `BudgetExceededError` so existing `except` blocks catch everything.

    ```python
    except TaskBudgetExceededError as e:
        print(f"Task '{e.task_name}' over budget")
    except AgentBudgetExceededError as e:
        print(f"Agent '{e.agent_name}' over budget")
    except BudgetExceededError:
        ...  # catches all budget errors
    ```

</div>

---

## Previous: v0.2.9

<div class="grid cards" markdown>

-   :material-console:{ .lg .middle } **[CLI Budget Enforcement](cli.md)**

    ---

    Run any Python agent with a hard USD cap — zero code changes. CI-friendly exit code 1. Docker, GitHub Actions, `.sh` scripts.

    ```bash
    shekel run agent.py --budget 5
    AGENT_BUDGET_USD=5 shekel run agent.py
    ```

-   :material-docker:{ .lg .middle } **[Docker & Container Guardrails](docker.md)**

    ---

    Use `shekel run` as a Docker entrypoint wrapper. Set `AGENT_BUDGET_USD` at runtime — no rebuild needed.

    ```dockerfile
    ENTRYPOINT ["shekel", "run", "agent.py"]
    ```

</div>

---

## Previous: v0.2.8

<div class="grid cards" markdown>

-   :material-tools:{ .lg .middle } **[Tool Budgets](usage/tool-budgets.md)**

    ---

    Cap agent tool calls and charge per-tool USD. Auto-intercepts LangChain, MCP, CrewAI, and OpenAI Agents SDK. One decorator for plain Python tools.

    ```python
    with budget(max_tool_calls=50):
        run_agent()

    @tool(price=0.005)
    def web_search(query): ...
    ```

-   :material-clock-time-four:{ .lg .middle } **[Temporal Budgets *(v0.2.8)*](usage/temporal-budgets.md)**

    ---

    Rolling-window spend limits with a string DSL. `TemporalBudgetBackend` Protocol for community-extensible backends (Redis, Postgres, etc.).

    ```python
    tb = budget("$5/hr", name="api-tier")
    async with tb:
        await call_llm()
    ```

-   :material-refresh:{ .lg .middle } **[Window Reset Events](usage/temporal-budgets.md)**

    ---

    New `on_window_reset` adapter event fires lazily when a `TemporalBudget` window expires at `__enter__` time. New `shekel.budget.window_resets_total` OTel counter.

-   :material-alert-circle:{ .lg .middle } **[`BudgetExceededError` enrichment](usage/temporal-budgets.md)**

    ---

    `retry_after` (seconds until window reset) and `window_spent` now available on `BudgetExceededError` for temporal budgets.

-   :material-chart-line:{ .lg .middle } **[OpenTelemetry Metrics *(v0.2.7)*](integrations/otel.md)**

    ---

    `ShekelMeter` emits 9 OTel instruments covering per-call cost, budget utilization, spend rate, fallback activations, auto-cap events, and window resets. Silent no-op when `opentelemetry-api` is absent.

    ```python
    pip install shekel[otel]
    ```

-   :material-google:{ .lg .middle } **[Google Gemini *(v0.2.6)*](integrations/gemini.md)**

    ---

    Native adapter for the `google-genai` SDK — enforce budgets on `generate_content` and streaming. Pricing bundled for Gemini 2.0 Flash, 2.5 Flash, and 2.5 Pro.

    ```python
    pip install shekel[gemini]
    ```

-   :material-robot:{ .lg .middle } **[HuggingFace Inference API *(v0.2.6)*](integrations/huggingface.md)**

    ---

    Native adapter for `huggingface-hub` — budget enforcement for any model on the HuggingFace Inference API, sync and streaming.

    ```python
    pip install shekel[huggingface]
    ```

</div>

---

## What's Next?

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **[Quick Start Guide](quickstart.md)**

    ---

    Get up and running in 5 minutes with step-by-step examples.

-   :material-book-open-variant:{ .lg .middle } **[Usage Guide](usage/basic-usage.md)**

    ---

    Learn about all the features: enforcement, fallbacks, streaming, and more.

-   :material-api:{ .lg .middle } **[API Reference](api-reference.md)**

    ---

    Complete documentation of all parameters, properties, and methods.

-   :material-puzzle:{ .lg .middle } **[Integrations](integrations/langgraph.md)**

    ---

    See how to use shekel with LangGraph, CrewAI, and other frameworks.

</div>

---

## Supported Models

Built-in pricing for GPT-4o, GPT-4o-mini, o1, Claude 3.5 Sonnet, Claude 3 Haiku, Gemini 1.5, and more.

Install `shekel[litellm]` to enforce hard spend limits across 100+ providers through LiteLLM's unified interface.

Install `shekel[all-models]` for 400+ models via [tokencost](https://github.com/AgentOps-AI/tokencost).

[See full model list →](models.md)

---

## Community

- **GitHub**: [arieradle/shekel](https://github.com/arieradle/shekel)
- **PyPI**: [pypi.org/project/shekel](https://pypi.org/project/shekel/)
- **Issues**: [github.com/arieradle/shekel/issues](https://github.com/arieradle/shekel/issues)
- **Contributing**: [See our guide](contributing.md)

---

## License

MIT License - see [LICENSE](https://github.com/arieradle/shekel/blob/main/LICENSE) for details.
