<div align="center">

# 🪙 shekel

**Stop your AI agent from bankrupting you.**

[![PyPI version](https://img.shields.io/pypi/v/shekel?color=blue&label=PyPI)](https://pypi.org/project/shekel/)
[![Python versions](https://img.shields.io/pypi/pyversions/shekel)](https://pypi.org/project/shekel/)
[![CI](https://github.com/arieradle/shekel/actions/workflows/ci.yml/badge.svg)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/arieradle/shekel/branch/main/graph/badge.svg)](https://codecov.io/gh/arieradle/shekel)
[![Downloads](https://img.shields.io/pypi/dm/shekel?color=green)](https://pypi.org/project/shekel/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://pypi.org/project/shekel/)
[![GitHub Stars](https://img.shields.io/github/stars/arieradle/shekel?style=social)](https://github.com/arieradle/shekel/stargazers)
[![Docs](https://img.shields.io/badge/docs-arieradle.github.io%2Fshekel-blue)](https://arieradle.github.io/shekel/latest/)

</div>

```python
with budget(max_usd=5.00):
    run_my_agent()       # hard stop at $5. no SDK changes. no config. just works.
```

```bash
shekel run agent.py --budget 5   # or enforce without touching code at all
```

</div>

---

I woke up to a **$47 AWS bill** from a LangGraph agent that spent the night retrying a failed tool call. OpenAI was happy to keep charging. I built shekel so you don't have to learn that lesson yourself.

---

## Install

```bash
pip install shekel[openai]       # OpenAI
pip install shekel[anthropic]    # Anthropic
pip install shekel[all]          # OpenAI + Anthropic + LiteLLM + Gemini + HuggingFace
pip install shekel[cli]          # shekel run — enforce budgets without touching code
```

---

## Works with everything

If it calls OpenAI or Anthropic under the hood, shekel sees it — **zero integration code needed.**

| Provider | Framework | |
|---|---|---|
| OpenAI · Anthropic · Gemini | LangChain · LangGraph | Auto-patched |
| HuggingFace · LiteLLM · Groq | CrewAI · OpenAI Agents SDK | Auto-patched |
| MCP · AutoGen · LlamaIndex | Any custom wrapper | Auto-patched |

---

## Every pattern you'll actually use

### Hard cap — the one that saves you

```python
from shekel import budget

with budget(max_usd=5.00):
    run_my_agent()
# raises BudgetExceededError the moment spend crosses $5
```

No wrapping your OpenAI client. No decorators. No SDK replacement. shekel monkey-patches the provider on context entry and restores it on exit. Your existing code runs unchanged.

### Warn before the limit hits

```python
with budget(max_usd=5.00, warn_at=0.8) as b:
    run_my_agent()
# logs a warning at $4.00, raises at $5.00
```

### Track spend without enforcing

```python
with budget() as b:
    run_my_agent()
print(f"that cost ${b.spent:.4f}")
```

### Switch to a cheaper model instead of crashing

```python
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_my_agent()
# switches gpt-4o → gpt-4o-mini at $0.80, hard stops at $1.00
```

### Cap tool calls — stop the infinite search loop

```python
from shekel import tool

@tool(price=0.01)               # charge $0.01 per call + count toward the cap
def web_search(query: str) -> str: ...

@tool                           # free — just count calls
def read_file(path: str) -> str: ...

with budget(max_usd=5.00, max_tool_calls=20) as b:
    run_my_agent()
# ToolBudgetExceededError on call 21 — before the tool runs
print(b.summary())              # LLM spend + tool spend broken out by tool name
```

Auto-intercepted with zero config: **LangChain, MCP, CrewAI, OpenAI Agents SDK**.

### Per-stage budget control

```python
with budget(max_usd=10.00, name="pipeline") as pipeline:
    with budget(max_usd=2.00, name="research"):
        results = search_web(query)        # capped at $2

    with budget(max_usd=5.00, name="analysis"):
        report = analyze(results)          # capped at $5

print(pipeline.tree())
# pipeline: $4.80 / $10.00
#   research:  $1.20 / $2.00
#   analysis:  $3.60 / $5.00
```

Children auto-cap to the parent's remaining balance. `b.tree()` gives you a live visual breakdown.

### LangGraph — per-node circuit breaking

```python
with budget(max_usd=10.00, name="graph") as b:
    b.node("fetch_data", max_usd=0.50)   # NodeBudgetExceededError before node runs
    b.node("summarize",  max_usd=1.00)

    app = graph.compile()
    app.invoke({"query": "..."})

print(b.tree())
# graph: $0.84 / $10.00
#   [node] fetch_data: $0.12 / $0.50  (24%)
#   [node] summarize:  $0.72 / $1.00  (72%)
```

Shekel patches `StateGraph.add_node()` transparently — no graph changes needed.

### LangChain — per-chain circuit breaking

```python
with budget(max_usd=5.00, name="pipeline") as b:
    b.chain("retriever",  max_usd=0.20)   # ChainBudgetExceededError before chain runs
    b.chain("summarizer", max_usd=1.00)

    retriever_chain.invoke({"query": "..."})
    summarizer_chain.invoke({"doc": "..."})
```

Shekel patches `Runnable._call_with_config` and `RunnableSequence.invoke` — zero changes to your chains.

### CrewAI — per-agent and per-task circuit breaking

```python
from shekel.exceptions import AgentBudgetExceededError, TaskBudgetExceededError

try:
    with budget(max_usd=5.00, name="crew") as b:
        b.agent(researcher.role,       max_usd=2.00)  # use agent.role directly
        b.agent(writer.role,           max_usd=1.00)
        b.task(research_task.name,     max_usd=1.50)  # use task.name directly
        b.task(write_task.name,        max_usd=0.80)
        crew.kickoff(inputs={"topic": "AI"})
except TaskBudgetExceededError as e:
    print(f"Task '{e.task_name}' over budget: ${e.spent:.4f} / ${e.limit:.2f}")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' over budget")

print(b.tree())
# crew: $2.84 / $5.00
#   [agent] Senior Researcher: $1.92 / $2.00  (96.0%)
#   [agent] Content Writer:    $0.92 / $1.00  (92.0%)
#   [task]  research:          $1.92 / $1.50  (128.0%)
#   [task]  write:             $0.92 / $0.80  (115.0%)
```

Shekel patches `Agent.execute_task` transparently. Gate order: task cap → agent cap → global (most specific first).

### Distributed budgets — enforce across multiple processes

```python
from shekel.backends.redis import RedisBackend

backend = RedisBackend()   # reads REDIS_URL from env; fail-closed by default

with budget("$5/hr + 100 calls/hr", name="api-tier", backend=backend) as b:
    response = client.chat.completions.create(...)
# Atomic Lua-script enforcement — one Redis round-trip per call
# BudgetConfigMismatchError if the same name is reused with different limits
```

Works with `AsyncRedisBackend` for async workflows. Circuit breaker built in — configurable threshold + cooldown. Fail-open or fail-closed.

### Rolling-window rate limits

```python
with budget("$5/hr", name="api-tier") as b:
    response = await client.chat.completions.create(...)
# BudgetExceededError carries retry_after so callers know when the window resets
```

Multi-cap: `budget("$5/hr + 100 calls/hr")` — USD and call-count windows are independent.

### Accumulate across sessions

```python
session = budget(max_usd=20.00, name="session")

with session: run_step_1()   # $3.20
with session: run_step_2()   # $8.10
with session: run_step_3()   # raises at $20

print(f"total: ${session.spent:.2f}")
```

---

## Enforce from the CLI — zero code changes

Don't want to touch the code at all? Don't.

```bash
pip install shekel[cli]

shekel run agent.py --budget 5
# exit 0 = under budget  |  exit 1 = budget exceeded  ← CI-friendly
```

Drop it into any pipeline:

```bash
# Shell / cron / Docker
AGENT_BUDGET_USD=5 shekel run agent.py

# GitHub Actions
- run: shekel run agent.py --budget 5

# Docker — operator sets budget at runtime, no rebuild needed
ENTRYPOINT ["shekel", "run", "agent.py"]
# docker run -e AGENT_BUDGET_USD=5 my-agent-image
```

Key flags:

```bash
--budget 5          # hard stop in USD
--warn-at 0.8       # log warning at 80%, hard stop at 100%
--max-llm-calls 20  # cap by call count instead of spend
--max-tool-calls 50 # cap agent tool calls
--warn-only         # log but never exit 1  (soft guardrail)
--dry-run           # track costs, no enforcement
--output json       # machine-readable spend summary for log pipelines
--budget-file shekel.toml  # load limits from config file
```

---

## What the spend summary looks like

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

Or machine-readable:

```bash
shekel run agent.py --budget 5 --output json
# {"spent": 1.245, "limit": 5.0, "calls": 5, "tool_calls": 9, "status": "ok", "model": "gpt-4o"}
```

---

## The decorator

```python
from shekel import with_budget

@with_budget(max_usd=0.10)
def summarize(text: str) -> str:
    return client.chat.completions.create(...).choices[0].message.content
# budget enforced independently on every call
```

---

## How it works

shekel monkey-patches `openai.chat.completions.create` and `anthropic.messages.create` on `__enter__` and restores originals on `__exit__`. Spend is tracked in a `ContextVar` — concurrent agents in the same process never share state. Nested `with budget()` blocks form a tree; child spend rolls up automatically.

**No background threads. No external services. No API keys. Nothing leaves your machine.**

---

## Observability

- **Langfuse** — cost streaming, circuit-break events, budget hierarchy in Langfuse spans
- **OpenTelemetry** — 9 instruments: `shekel.llm.cost_usd`, `shekel.budget.utilization`, `shekel.budget.spend_rate`, `shekel.tool.calls_total`, and more

```python
from shekel.otel import ShekelMeter
meter = ShekelMeter()  # attaches to global MeterProvider; silent no-op if OTel absent
```

---

## Supported models

Built-in pricing for GPT-4o, GPT-4o-mini, o1, o3, Claude 3.5/3/3.7 Sonnet, Claude 3 Haiku/Opus, Gemini 2.0/2.5 Flash/Pro, and more.

```bash
pip install shekel[all-models]   # 400+ models via tokencost
shekel models                    # list all bundled models and pricing
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
```

---

## API quick reference

```python
budget(
    max_usd=5.00,           # hard USD cap
    warn_at=0.8,            # warn at 80%
    max_llm_calls=50,       # cap by call count
    max_tool_calls=100,     # cap tool dispatches
    tool_prices={"web_search": 0.01},  # charge per tool
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},  # switch instead of crash
    name="my-agent",        # required for nesting + temporal budgets
    backend=RedisBackend(), # distributed enforcement across processes
)

budget("$5/hr + 100 calls/hr", name="api-tier")  # multi-cap rolling-window
```

**Component caps** — all chainable, all raise before the component executes:

```python
b.node("fetch_data", max_usd=0.50)   # LangGraph node  → NodeBudgetExceededError
b.chain("retriever", max_usd=0.20)   # LangChain chain → ChainBudgetExceededError
b.agent("researcher", max_usd=1.00)  # CrewAI agent    → AgentBudgetExceededError
b.task("summarize", max_usd=0.50)    # CrewAI task     → TaskBudgetExceededError
```

**Exceptions** — all subclass `BudgetExceededError`, so one `except` catches everything:

| Exception | Raised when | Key fields |
|---|---|---|
| `BudgetExceededError` | Global cap hit | `spent`, `limit`, `model`, `retry_after` |
| `NodeBudgetExceededError` | LangGraph node cap hit | `node_name`, `spent`, `limit` |
| `AgentBudgetExceededError` | CrewAI agent cap hit | `agent_name`, `spent`, `limit` |
| `TaskBudgetExceededError` | CrewAI task cap hit | `task_name`, `spent`, `limit` |
| `ChainBudgetExceededError` | LangChain chain cap hit | `chain_name`, `spent`, `limit` |
| `ToolBudgetExceededError` | Tool call cap hit | `tool_name`, `calls_used`, `calls_limit` |
| `BudgetConfigMismatchError` | Redis name reused with different limits | — |

---

## Security

Every PR and push to `main` runs CodeQL, Trivy, Bandit, and pip-audit. See the [Security tab](https://github.com/arieradle/shekel/security/code-scanning) for results.

---

## Documentation

**[arieradle.github.io/shekel](https://arieradle.github.io/shekel/latest/)**

- [Quick Start](https://arieradle.github.io/shekel/latest/quickstart/)
- [CLI Reference](https://arieradle.github.io/shekel/latest/cli/)
- [Docker & Containers](https://arieradle.github.io/shekel/latest/docker/)
- [Nested Budgets](https://arieradle.github.io/shekel/latest/usage/nested-budgets/)
- [Tool Budgets](https://arieradle.github.io/shekel/latest/usage/tool-budgets/)
- [Temporal Budgets](https://arieradle.github.io/shekel/latest/usage/temporal-budgets/)
- [LangGraph Integration](https://arieradle.github.io/shekel/latest/integrations/langgraph/)
- [CrewAI Integration](https://arieradle.github.io/shekel/latest/integrations/crewai/)
- [API Reference](https://arieradle.github.io/shekel/latest/api-reference/)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — especially new framework adapters.

## License

MIT
