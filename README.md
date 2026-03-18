# shekel

[![PyPI version](https://img.shields.io/pypi/v/shekel)](https://pypi.org/project/shekel/)
[![Python versions](https://img.shields.io/pypi/pyversions/shekel)](https://pypi.org/project/shekel/)
[![CI](https://github.com/arieradle/shekel/actions/workflows/ci.yml/badge.svg)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/arieradle/shekel/branch/main/graph/badge.svg)](https://codecov.io/gh/arieradle/shekel)
[![Downloads](https://img.shields.io/pypi/dm/shekel)](https://pypi.org/project/shekel/)
[![License](https://img.shields.io/pypi/l/shekel)](https://pypi.org/project/shekel/)

**Stop your AI agent from bankrupting you. One line.**

```python
with budget(max_usd=5.00):
    run_my_agent()
```

```bash
# Or enforce from outside — zero code changes
shekel run agent.py --budget 5
```

---

I woke up to a $47 AWS bill from a LangGraph agent that spent the night retrying a failed tool call. OpenAI was happy to keep charging. I built shekel so you don't have to learn that lesson yourself.

---

## Install

```bash
pip install shekel[openai]       # OpenAI
pip install shekel[anthropic]    # Anthropic
pip install shekel[all]          # OpenAI + Anthropic + LiteLLM + Gemini + HuggingFace
pip install shekel[cli]          # shekel run — enforce budgets without touching code
```

---

## The one-liner that changes everything

```python
from shekel import budget

with budget(max_usd=5.00):
    run_my_agent()               # hard stop at $5. no config. no API keys. just works.
```

That's it. No wrapping your OpenAI client. No decorators. No SDK replacement. shekel monkey-patches the provider SDK on context entry and restores it on exit. Your existing code runs unchanged.

Works with **OpenAI, Anthropic, Google Gemini, HuggingFace, LiteLLM, LangChain, LangGraph, CrewAI, MCP, OpenAI Agents SDK, AutoGen, LlamaIndex** — if it calls OpenAI or Anthropic under the hood, shekel sees it.

---

## Enforce from the CLI — zero code changes

Don't want to touch the code at all? Don't.

```bash
pip install shekel[cli]

shekel run agent.py --budget 5
# exit 0 = success  |  exit 1 = budget exceeded  ← CI-friendly
```

Drop it into any pipeline:

```bash
# Shell script / cron / Docker
AGENT_BUDGET_USD=5 shekel run agent.py

# GitHub Actions
- uses: ./.github/actions/enforce
  with:
    script: agent.py
    budget: "5"

# Docker — operator sets budget at runtime, no rebuild needed
ENTRYPOINT ["shekel", "run", "agent.py"]
# docker run -e AGENT_BUDGET_USD=5 my-agent-image
```

Flags that matter:

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

## Every pattern you'll actually use

### Hard cap

```python
with budget(max_usd=5.00):
    run_my_agent()
# raises BudgetExceededError the moment spend crosses $5
```

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
# switches from gpt-4o → gpt-4o-mini at $0.80, hard stops at $1.00
```

### Cap tool calls — stop the web_search loop

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

Children auto-cap to the parent's remaining balance. `workflow.tree()` gives you a visual breakdown.

### Rolling-window rate limits — `$5/hr`

```python
api_budget = budget("$5/hr", name="api-tier")

async with api_budget:
    response = await client.chat.completions.create(...)
# BudgetExceededError carries retry_after and window_spent
```

### Accumulate across sessions

```python
session = budget(max_usd=20.00, name="session")

with session: run_step_1()   # $3.20
with session: run_step_2()   # $8.10
with session: run_step_3()   # raises at $20

print(f"total: ${session.spent:.2f}")
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
# budget enforced on every call, independently
```

---

## How it works

shekel monkey-patches `openai.chat.completions.create` and `anthropic.messages.create` on `__enter__` and restores originals on `__exit__`. Spend is tracked in a `ContextVar` — concurrent agents in the same process never share state. Nested `with budget()` blocks form a tree; child spend rolls up automatically.

No background threads. No external services. No API keys. Nothing leaves your machine.

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

## API

```python
budget(
    max_usd=5.00,           # hard USD cap
    warn_at=0.8,            # warn at 80%
    max_llm_calls=50,       # cap by call count
    max_tool_calls=100,     # cap tool dispatches
    tool_prices={"web_search": 0.01},  # charge per tool
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},  # switch instead of crash
    name="my-agent",        # required for nesting + temporal budgets
)

budget("$5/hr", name="api-tier")   # temporal: rolling-window rate limit
```

`BudgetExceededError` → `spent`, `limit`, `model`, `retry_after` (temporal)
`ToolBudgetExceededError` → `tool_name`, `calls_used`, `calls_limit`, `framework`

---

## Documentation

**[arieradle.github.io/shekel](https://arieradle.github.io/shekel/latest/)**

- [Quick Start](https://arieradle.github.io/shekel/latest/quickstart/)
- [Installation](https://arieradle.github.io/shekel/latest/installation/)
- [CLI Reference](https://arieradle.github.io/shekel/latest/cli/) — `shekel run` full options
- [Docker & Containers](https://arieradle.github.io/shekel/latest/docker/) — entrypoint patterns
- [Architecture](https://arieradle.github.io/shekel/latest/architecture/) — how shekel works under the hood
- [Nested Budgets](https://arieradle.github.io/shekel/latest/usage/nested-budgets/)
- [Tool Budgets](https://arieradle.github.io/shekel/latest/usage/tool-budgets/)
- [Temporal Budgets](https://arieradle.github.io/shekel/latest/usage/temporal-budgets/)
- [API Reference](https://arieradle.github.io/shekel/latest/api-reference/)

---

## Security

Every PR and push to `main` runs CodeQL, Trivy, Bandit, and pip-audit. See the [Security tab](https://github.com/arieradle/shekel/security/code-scanning) for results.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome.

## License

MIT
