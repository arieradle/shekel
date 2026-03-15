# shekel

[![PyPI version](https://img.shields.io/pypi/v/shekel)](https://pypi.org/project/shekel/)
[![Python versions](https://img.shields.io/pypi/pyversions/shekel)](https://pypi.org/project/shekel/)
[![License](https://img.shields.io/pypi/l/shekel)](https://pypi.org/project/shekel/)
[![CI](https://github.com/arieradle/shekel/actions/workflows/ci.yml/badge.svg)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![Unit Tests](https://img.shields.io/badge/unit%20tests-491%20passed-brightgreen)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![Integration Tests](https://img.shields.io/badge/integration%20tests-340%20passed-brightgreen)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![Performance Tests](https://img.shields.io/badge/performance%20tests-148%20passed-brightgreen)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/arieradle/shekel/branch/main/graph/badge.svg)](https://codecov.io/gh/arieradle/shekel)
[![Downloads](https://img.shields.io/pypi/dm/shekel)](https://pypi.org/project/shekel/)
[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://arieradle.github.io/shekel/)

**LLM budget enforcement and cost tracking for Python. One line. Zero config.**

```python
with budget(max_usd=1.00):
    run_my_agent()  # raises BudgetExceededError if spend exceeds $1.00
```

I spent $47 debugging a LangGraph retry loop. The agent kept failing, LangGraph kept retrying, and OpenAI kept charging — all while I slept. I built shekel so you don't have to learn that lesson yourself.

---

## ⚡️ What's New in v0.2.8: Temporal Budgets

**Rolling-window LLM spend limits — enforce `$5/hr` per API tier, user, or agent with a single line.**

```python
from shekel import budget, BudgetExceededError

# String DSL
api_budget = budget("$5/hr", name="api-tier")

async with api_budget:
    response = await client.chat.completions.create(...)
```

```python
# Or explicit kwargs
api_budget = budget(max_usd=5.0, window_seconds=3600, name="api-tier")
```

When the window limit is hit, `BudgetExceededError` now carries `retry_after` (seconds until reset) and `window_spent`:

```python
try:
    async with api_budget:
        response = await client.chat(...)
except BudgetExceededError as e:
    print(f"Window exceeded — retry in {e.retry_after:.0f}s (spent ${e.window_spent:.2f})")
```

**Design decisions:**
- Rolling window only (no fixed calendar windows) — simpler, no clock-sync issues
- Lazy reset on `__enter__` — no background threads
- `TemporalBudgetBackend` Protocol — bring your own Redis/Postgres backend
- Temporal-in-temporal nesting raises `ValueError` (regular `Budget` nesting is fine)
- `name=` is required on `TemporalBudget` — prevents ambiguous metrics

### Previous: OpenTelemetry Metrics *(v0.2.7)*

**Shekel exposes LLM cost and budget lifecycle data via OpenTelemetry — filling the gap the OTel GenAI spec leaves around cost and budget metrics.**

```bash
pip install shekel[otel]
```

```python
from shekel.otel import ShekelMeter
meter = ShekelMeter()  # uses global MeterProvider; silent no-op if OTel absent
```

Nine instruments ship out of the box:

| Instrument | Type | What it tracks |
|---|---|---|
| `shekel.llm.cost_usd` | Counter | Cost per LLM call (tagged by model & provider) |
| `shekel.llm.calls_total` | Counter | Call count per model |
| `shekel.llm.tokens_input_total` | Counter | Input tokens (opt-in) |
| `shekel.llm.tokens_output_total` | Counter | Output tokens (opt-in) |
| `shekel.budget.exits_total` | Counter | Budget exits by `status=completed\|exceeded\|warned` |
| `shekel.budget.cost_usd` | UpDownCounter | Cumulative spend per budget |
| `shekel.budget.utilization` | Histogram | 0.0–1.0 utilization on exit |
| `shekel.budget.spend_rate` | Histogram | USD/second spend rate |
| `shekel.budget.fallbacks_total` | Counter | Fallback model activations |
| `shekel.budget.autocaps_total` | Counter | Child budget auto-cap events |
| `shekel.budget.window_resets_total` | Counter | Temporal budget window resets *(v0.2.8)* |

**[📖 OTel Integration Guide](https://arieradle.github.io/shekel/integrations/otel/)**

### Previous: Native Gemini & HuggingFace Support *(v0.2.6)*

**Zero-config budget enforcement for Google Gemini and HuggingFace Inference API — same `with budget():` pattern, no changes needed.**

```python
# Google Gemini
import google.genai as genai
from shekel import budget

client = genai.Client(api_key="...")
with budget(max_usd=1.00) as b:
    response = client.models.generate_content(model="gemini-2.0-flash", contents="...")
print(f"Cost: ${b.spent:.4f}")
```

### Extensible Provider Architecture *(v0.2.5)*

Add any LLM provider without touching shekel core:

```python
from shekel.providers.base import ADAPTER_REGISTRY, ProviderAdapter

class MyProviderAdapter(ProviderAdapter):
    @property
    def name(self) -> str:
        return "myprovider"

    def install_patches(self) -> None: ...
    def extract_tokens(self, response) -> tuple: ...
    # ... and 4 more methods

ADAPTER_REGISTRY.register(MyProviderAdapter())

with budget(max_usd=10.00):
    response = my_provider_client.call()  # Shekel tracks cost
```

### ✅ Comprehensive Integration Test Suite

340 integration tests across real providers and feature domains — real API keys run in CI:

| Provider / Feature | Tests | Coverage |
|----------|-------|----------|
| OpenAI | 26 | Sync, async, streaming, budget enforcement, callbacks, fallback, multi-turn |
| Anthropic | 24 | Sync, async, streaming, budget enforcement, callbacks, multi-turn |
| Groq | 30 | Custom pricing, nested budgets, streaming, concurrent calls, rate limiting |
| Google Gemini | 42 | Multi-turn, streaming, JSON mode, function calling, token accuracy |
| HuggingFace | 12 | Sync, streaming, custom pricing, budget enforcement |
| LangGraph | 14 | Multi-node graphs, conditional edges, budget propagation |
| Ollama | 38 | Local inference, streaming, nested budgets |
| Temporal Budgets | 37 | Rolling windows, nesting, adapter events, async, multi-tenant, OTel |

---

## ✨ Core Features

### 🌳 Nested Budgets

Enforce independent spend limits per workflow stage with automatic rollup:

```python
with budget(max_usd=10.00, name="workflow") as workflow:
    with budget(max_usd=2.00, name="research"):
        sources = search_papers()      # $0.80

    with budget(max_usd=5.00, name="analysis"):
        insights = analyze(sources)    # $3.50

    final = polish(insights)           # $0.60

print(workflow.tree())
# workflow: $5.00 / $10.00
#   research: $0.80 / $2.00
#   analysis: $3.50 / $5.00
```

**Why you'll love this:**
- 🎯 Per-stage budgets — Cap each phase independently
- 🔒 Auto-capping — Child budgets can't exceed parent's remaining
- 📊 Cost attribution — See exactly where money was spent
- 🌳 Visual tree — Debug complex workflows instantly

**[📖 Nested Budgets Guide](https://arieradle.github.io/shekel/usage/nested-budgets/)**

### 🔭 Langfuse Integration

See exactly where your budget is going and when it breaks. Circuit-break events, budget hierarchy, and per-call spend stream to Langfuse automatically:

```python
from langfuse import Langfuse
from shekel.integrations import AdapterRegistry
from shekel.integrations.langfuse import LangfuseAdapter

lf = Langfuse(public_key="...", secret_key="...")
adapter = LangfuseAdapter(client=lf, trace_name="my-app")
AdapterRegistry.register(adapter)

with budget(max_usd=10.00, name="agent") as b:
    run_agent()  # Costs flow to Langfuse automatically!
```

**What you get:**
- ⚠️ Circuit break events — Captured in Langfuse the moment a budget is exceeded
- 🔄 Fallback annotations — Model switches recorded with timing and cost
- 🌳 Nested budget hierarchy — Child budgets map to child spans
- 💰 Per-call spend streaming — See cumulative cost after every LLM call

**[📖 Langfuse Integration Guide](https://arieradle.github.io/shekel/integrations/langfuse/)**

---

## Install

```bash
pip install shekel[openai]       # OpenAI
pip install shekel[anthropic]    # Anthropic
pip install shekel[gemini]       # Google Gemini (google-genai SDK)
pip install shekel[huggingface]  # HuggingFace Inference API
pip install shekel[langfuse]     # Langfuse (budget visibility and circuit-break events)
pip install shekel[litellm]      # LiteLLM (budget enforcement across 100+ providers)
pip install shekel[otel]         # OpenTelemetry metrics (ShekelMeter)
pip install shekel[all]          # All providers + Langfuse + OTel
pip install shekel[all-models]   # All above + tokencost (400+ model pricing)
pip install shekel[cli]          # CLI tools (shekel estimate, shekel models)
```

---

## Quick Start

### Simple Budget Enforcement

```python
from shekel import budget, BudgetExceededError

# Enforce a hard cap
try:
    with budget(max_usd=1.00, warn_at=0.8) as b:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello!"}]
        )
    print(f"Spent ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: ${e.spent:.2f} > ${e.limit:.2f}")
```

### Track Without Limits

```python
# Track spend without enforcing a limit
with budget() as b:
    run_my_agent()
print(f"Cost: ${b.spent:.4f}")
```

### Fallback to Cheaper Model

```python
# Switch to gpt-4o-mini at 80% of budget instead of raising
with budget(max_usd=0.50, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

if b.model_switched:
    print(f"Switched to {b.fallback['model']} at ${b.switched_at_usd:.4f}")
```

### Accumulating Sessions

```python
# Budget variables accumulate across multiple uses
session = budget(max_usd=5.00, name="session")

with session:
    run_step_1()  # Spends $1.50

with session:
    run_step_2()  # Spends $2.00

print(f"Session total: ${session.spent:.2f}")  # $3.50
```

---

## 🌳 Nested Budgets

Perfect for **multi-stage agents**, **research workflows**, and **production AI pipelines**.

### Real-World Example: AI Research Agent

```python
from shekel import budget

def research_agent(topic: str, max_budget: float = 10.0):
    """Research agent with per-stage budget control."""
    
    with budget(max_usd=max_budget, name="research_agent") as agent:
        # Phase 1: Web search ($2 budget)
        with budget(max_usd=2.00, name="web_search") as search:
            results = search_web(topic)
            if search.spent > 1.50:
                print("⚠️  Search phase used 75% of budget")
        
        # Phase 2: Content analysis ($5 budget)
        with budget(max_usd=5.00, name="analysis") as analysis:
            key_points = extract_insights(results)
            themes = identify_themes(key_points)
        
        # Phase 3: Report generation ($3 budget)
        with budget(max_usd=3.00, name="report_gen") as report:
            draft = generate_report(themes)
            final = refine_report(draft)
    
    # Print cost breakdown
    print(agent.tree())
    return final

# Run the agent
report = research_agent("AI safety alignment", max_budget=15.0)
```

### Auto-Capping: Smart Budget Management

```python
with budget(max_usd=10.00, name="workflow") as workflow:
    # Spend $7 on initial processing
    process_data()  # Spends $7.00
    
    # Child wants $5, but only $3 left
    # Shekel automatically caps child to $3!
    with budget(max_usd=5.00, name="final_step") as step:
        print(f"Requested: $5.00")
        print(f"Actual limit: ${step.limit:.2f}")  # $3.00 (auto-capped!)
        generate_output()  # Won't exceed $3
```

### Hierarchical Cost Attribution

```python
with budget(max_usd=50.00, name="production_pipeline") as pipeline:
    with budget(max_usd=10.00, name="ingestion"):
        ingest_data()
    
    with budget(max_usd=20.00, name="processing"):
        with budget(max_usd=8.00, name="validation"):
            validate_data()
        
        with budget(max_usd=12.00, name="transformation"):
            transform_data()
    
    with budget(max_usd=15.00, name="output"):
        generate_report()

# Detailed breakdown
print(f"Total: ${pipeline.spent:.2f}")
print(f"Direct spend: ${pipeline.spent_direct:.2f}")
print(f"Child spend: ${pipeline.spent_by_children:.2f}")
print(f"\nFull tree:")
print(pipeline.tree())
```

### Track-Only Children

```python
# Parent enforces budget, but track children without limits
with budget(max_usd=20.00, name="workflow") as workflow:
    # This child has no limit (max_usd=None)
    with budget(max_usd=None, name="exploration"):
        explore_options()  # Tracked but unlimited
    
    # This child is limited
    with budget(max_usd=5.00, name="finalization"):
        finalize()

print(f"Exploration cost: ${workflow.children[0].spent:.2f}")
print(f"Total cost: ${workflow.spent:.2f}")
```

---

## Advanced Features

### Async Support

```python
async with budget(max_usd=1.00) as b:
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello!"}]
    )
```

Full async support — `async with budget(...)` works for both top-level and nested budgets.

### Decorator Pattern

```python
from shekel import with_budget

@with_budget(max_usd=0.10)
def call_llm(prompt: str):
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
```

### Custom Pricing

```python
# Override model pricing
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.001, "output": 0.003}
) as b:
    call_custom_model()
```

### Spend Summary

```python
with budget(max_usd=2.00) as b:
    run_my_agent()

print(b.summary())
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# shekel spend summary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Total: $1.2450 / $2.00 (62%)
# 
# gpt-4o: $1.2450 (5 calls)
#   Input:  45.2k tokens → $0.1130
#   Output: 11.3k tokens → $1.1320
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## CLI

```bash
# Estimate cost before running
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
# Model:          gpt-4o
# Input tokens:   1,000
# Output tokens:  500
# Estimated cost: $0.007500

# List all bundled models with pricing
shekel models
shekel models --provider openai
shekel models --provider anthropic
```

---

## API Reference

### `budget(...)`

**String form** (returns `TemporalBudget`):

```python
budget("$5/hr", name="api")          # $5 per hour rolling window
budget("$10/30min", name="burst")    # $10 per 30-minute window
budget("$1/60s", name="realtime")    # $1 per minute
```

**Keyword form**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_usd` | `float \| None` | `None` | Hard spend cap in USD. `None` = track only. |
| `window_seconds` | `float \| None` | `None` | Rolling window duration in seconds. Set to create a `TemporalBudget`. |
| `name` | `str \| None` | `None` | Budget name. Required for `TemporalBudget` and nested budgets. |
| `warn_at` | `float \| None` | `None` | Fraction of limit (0.0–1.0) at which to call `on_warn`. |
| `on_warn` | `Callable \| None` | `None` | Callback at `warn_at` threshold. Receives `(spent, limit)`. |
| `fallback` | `dict \| None` | `None` | Switch model at threshold: `{"at_pct": 0.8, "model": "gpt-4o-mini"}`. Same provider only. |
| `on_fallback` | `Callable \| None` | `None` | Callback on fallback switch. Receives `(spent, limit, fallback_model)`. |
| `max_llm_calls` | `int \| None` | `None` | Hard cap on number of LLM API calls. |
| `price_per_1k_tokens` | `dict \| None` | `None` | Override pricing: `{"input": 0.001, "output": 0.003}`. |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `spent` | `float` | Total USD spent (includes children). |
| `remaining` | `float \| None` | USD remaining (based on effective limit). |
| `limit` | `float \| None` | Effective limit (auto-capped if nested). |
| `name` | `str \| None` | Budget name. |
| `calls_used` | `int` | Number of LLM API calls made so far. |
| `calls_remaining` | `int \| None` | Calls remaining before `max_llm_calls` is hit. |
| `parent` | `Budget \| None` | Parent budget, or `None` if root. |
| `children` | `list[Budget]` | List of child budgets. |
| `active_child` | `Budget \| None` | Currently active child. |
| `full_name` | `str` | Hierarchical path (e.g., `"workflow.research"`). |
| `spent_direct` | `float` | Direct spend on this budget (excluding children). |
| `spent_by_children` | `float` | Sum of all child spend. |
| `model_switched` | `bool` | `True` if fallback was activated. |
| `switched_at_usd` | `float \| None` | Spend level when fallback triggered. |
| `fallback_spent` | `float` | Cost incurred on the fallback model. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `summary()` | `str` | Formatted spend summary with model breakdown. |
| `summary_data()` | `dict` | Structured spend data as dictionary. |
| `tree()` | `str` | Visual hierarchy of the budget tree. |
| `reset()` | `None` | Reset spend tracking (only outside context). |

### `BudgetExceededError`

| Attribute | Description |
|-----------|-------------|
| `spent` | Total spend when limit was hit. |
| `limit` | The configured `max_usd`. |
| `model` | Model that triggered the error. |
| `tokens` | `{"input": N, "output": N}` from the last call. |
| `retry_after` | `float \| None` — seconds until `TemporalBudget` window resets. `None` for regular `Budget`. |
| `window_spent` | `float \| None` — spend accumulated in the current rolling window. `None` for regular `Budget`. |

---

## Supported Models

| Model | Input / 1k | Output / 1k |
|-------|-----------|-------------|
| gpt-4o | $0.00250 | $0.01000 |
| gpt-4o-mini | $0.000150 | $0.000600 |
| o1 | $0.01500 | $0.06000 |
| o1-mini | $0.00300 | $0.01200 |
| gpt-3.5-turbo | $0.000500 | $0.001500 |
| claude-3-5-sonnet-20241022 | $0.00300 | $0.01500 |
| claude-3-haiku-20240307 | $0.000250 | $0.001250 |
| claude-3-opus-20240229 | $0.01500 | $0.07500 |
| gemini-1.5-flash | $0.0000750 | $0.000300 |
| gemini-1.5-pro | $0.00125 | $0.00500 |

Versioned model names resolve automatically — `gpt-4o-2024-08-06` maps to `gpt-4o`.

For unlisted models: pass `price_per_1k_tokens` or install `shekel[all-models]` for 400+ models via [tokencost](https://github.com/AgentOps-AI/tokencost).

---

## Framework Integration

Works seamlessly with:

- **OpenTelemetry** — 8 instruments for cost/budget metrics; compatible with any OTel backend *(v0.2.7)*
- **Langfuse** — Full observability: cost streaming, span hierarchy, circuit-break events *(v0.2.4)*
- **LangGraph** — Budget entire agent workflows
- **CrewAI** — Per-agent budget tracking
- **AutoGen** — Multi-agent cost control
- **LlamaIndex** — RAG pipeline budgets
- **Haystack** — Document processing budgets

Any framework that calls `openai` or `anthropic` under the hood works automatically. See [`examples/`](examples/) for demos.

---

## How It Works

- **Monkey-patching** — Wraps `openai.chat.completions.create()` and `anthropic.messages.create()` on context entry
- **ContextVar isolation** — Each `budget()` stores its counter in a ContextVar; concurrent agents never share state
- **Hierarchical tracking** — Parent/child relationships track spend propagation automatically
- **Ref-counted patching** — Nested contexts patch only once
- **Zero config** — No API keys, no external services

---

## Documentation

**Full documentation: [arieradle.github.io/shekel](https://arieradle.github.io/shekel/)**

- [Quick Start Guide](https://arieradle.github.io/shekel/quickstart/)
- [Nested Budgets Guide](https://arieradle.github.io/shekel/usage/nested-budgets/)
- [Langfuse Integration Guide](https://arieradle.github.io/shekel/langfuse-integration/) *(v0.2.4)*
- [API Reference](https://arieradle.github.io/shekel/api-reference/)
- [Framework Integrations](https://arieradle.github.io/shekel/integrations/)

---

## Machine Discovery Metadata

This project provides:

- LLM budget control
- AI agent cost governance
- Token budgeting for LLM APIs
- Spend limits and usage quotas
- Guardrails for agentic systems

Works with ecosystems including:

OpenAI, Anthropic Claude, LangChain, LangGraph, Langfuse, CrewAI

Use cases include:

- Preventing runaway LLM costs
- Enforcing AI agent budgets
- LLMOps governance
- Token usage control
- AI API spend guardrails

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
