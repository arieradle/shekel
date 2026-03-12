# shekel

[![PyPI version](https://img.shields.io/pypi/v/shekel)](https://pypi.org/project/shekel/)
[![Python versions](https://img.shields.io/pypi/pyversions/shekel)](https://pypi.org/project/shekel/)
[![License](https://img.shields.io/pypi/l/shekel)](https://pypi.org/project/shekel/)
[![CI](https://github.com/arieradle/shekel/actions/workflows/ci.yml/badge.svg)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![Performance](https://img.shields.io/badge/perf-120%20tests-brightgreen)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![Integration Tests](https://img.shields.io/badge/integration%20tests-104%20passed-brightgreen)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/arieradle/shekel/branch/main/graph/badge.svg)](https://codecov.io/gh/arieradle/shekel)
[![Downloads](https://img.shields.io/pypi/dm/shekel)](https://pypi.org/project/shekel/)
[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://arieradle.github.io/shekel/)

**LLM cost tracking and budget enforcement for Python. One line. Zero config.**

```python
with budget(max_usd=1.00):
    run_my_agent()  # raises BudgetExceededError if spend exceeds $1.00
```

I spent $47 debugging a LangGraph retry loop. The agent kept failing, LangGraph kept retrying, and OpenAI kept charging — all while I slept. I built shekel so you don't have to learn that lesson yourself.

---

## ⚡️ What's New in v0.2.5: Extensible Provider Architecture

**Built an open architecture for adding new LLM providers without touching shekel's core. Validated with comprehensive integration tests.**

### 🔧 Provider Registry Architecture

Shekel now uses a pluggable provider adapter pattern, enabling the community to add support for any LLM provider:

```python
from shekel.providers.base import ADAPTER_REGISTRY, ProviderAdapter

class MyProviderAdapter(ProviderAdapter):
    @property
    def name(self) -> str:
        return "myprovider"

    # Implement: install_patches(), remove_patches(), extract_tokens(), wrap_stream()
    def install_patches(self) -> None: ...
    def extract_tokens(self, response) -> tuple: ...
    # ... 5 more methods

# Register once at import time
ADAPTER_REGISTRY.register(MyProviderAdapter())

# Works everywhere automatically:
with budget(max_usd=10.00):
    response = my_provider_client.call()  # Shekel tracks cost
```

**What this enables:**
- Add new providers without modifying shekel core
- Standard interface all providers implement
- Easy community contributions (Cohere, Replicate, vLLM, Mistral, etc.)

### ✅ Validated with Real-World Integration Tests

Provider architecture validated and stress-tested with comprehensive integration test suites:

- **25+ Groq API integration tests** — Custom pricing, nested budgets, streaming, concurrent calls, rate limiting
- **30+ Google Gemini API integration tests** — Multi-turn conversations, JSON mode, function calls, token accuracy
- Real API keys in CI pipeline ensure it works end-to-end

### ⚙️ Production-Grade Reliability

- **Exponential backoff retry logic** — Gracefully handles rate limiting and transient failures
- **100+ integration test scenarios** — Comprehensive validation across multiple providers
- **Concurrent test stability** — Reduced flakiness in multi-provider scenarios

---

## ✨ Core Features

### 🌳 Nested Budgets

Control costs for multi-stage AI workflows with hierarchical budget tracking:

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

Full LLM observability with zero configuration. Track costs, visualize budget hierarchies, and debug overruns in Langfuse automatically:

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
- 💰 Real-time cost streaming — See spend after each LLM call
- 🌳 Nested budget hierarchy — Child budgets → child spans
- ⚠️ Circuit break events — Alerts when budgets are exceeded
- 🔄 Fallback annotations — Track model switches

**[📖 Langfuse Integration Guide](https://arieradle.github.io/shekel/integrations/langfuse/)**

---

## Install

```bash
pip install shekel[openai]       # OpenAI
pip install shekel[anthropic]    # Anthropic
pip install shekel[langfuse]     # Langfuse observability
pip install shekel[all]          # OpenAI + Anthropic + Langfuse
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
# Fall back to gpt-4o-mini instead of raising
with budget(max_usd=0.50, fallback="gpt-4o-mini") as b:
    response = client.chat.completions.create(
        model="gpt-4o",  # Will switch to gpt-4o-mini if needed
        messages=[{"role": "user", "content": prompt}]
    )
    
if b.model_switched:
    print(f"Switched to {b.fallback} at ${b.switched_at_usd:.4f}")
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

**Note:** Async nesting not yet supported in v0.2.3. Use sync nested budgets or single-level async.

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

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_usd` | `float \| None` | `None` | Hard spend cap in USD. `None` = track only. |
| `name` | `str \| None` | `None` | **v0.2.3**: Budget name. **Required for nesting**. |
| `warn_at` | `float \| None` | `None` | Fraction of limit (0.0–1.0) at which to warn. |
| `on_exceed` | `Callable \| None` | `None` | Callback at `warn_at` threshold. Receives `(spent, limit)`. |
| `fallback` | `str \| None` | `None` | Model to switch to when `max_usd` is hit. Same provider only. |
| `on_fallback` | `Callable \| None` | `None` | Callback on fallback switch. Receives `(spent, limit, fallback_model)`. |
| `hard_cap` | `float \| None` | `max_usd * 2` | Absolute ceiling when fallback is active. |
| `price_per_1k_tokens` | `dict \| None` | `None` | Override pricing: `{"input": 0.001, "output": 0.003}`. |
| `persistent` | `bool` | `False` | **DEPRECATED v0.2.3**: Budgets always accumulate now. |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `spent` | `float` | Total USD spent (includes children). |
| `remaining` | `float \| None` | USD remaining (based on effective limit). |
| `limit` | `float \| None` | Effective limit (auto-capped if nested). |
| `name` | `str \| None` | Budget name. |
| `parent` | `Budget \| None` | **v0.2.3**: Parent budget, or `None` if root. |
| `children` | `list[Budget]` | **v0.2.3**: List of child budgets. |
| `active_child` | `Budget \| None` | **v0.2.3**: Currently active child. |
| `full_name` | `str` | **v0.2.3**: Hierarchical path (e.g., `"workflow.research"`). |
| `spent_direct` | `float` | **v0.2.3**: Direct spend (excluding children). |
| `spent_by_children` | `float` | **v0.2.3**: Sum of all child spend. |
| `model_switched` | `bool` | `True` if fallback was activated. |
| `switched_at_usd` | `float \| None` | Spend level when fallback triggered. |
| `fallback_spent` | `float` | Cost on the fallback model. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `summary()` | `str` | Formatted spend summary with model breakdown. |
| `summary_data()` | `dict` | Structured spend data as dictionary. |
| `tree()` | `str` | **v0.2.3**: Visual hierarchy of budget tree. |
| `reset()` | `None` | Reset spend tracking (only outside context). |

### `BudgetExceededError`

| Attribute | Description |
|-----------|-------------|
| `spent` | Total spend when limit was hit. |
| `limit` | The configured `max_usd`. |
| `model` | Model that triggered the error. |
| `tokens` | `{"input": N, "output": N}` from the last call. |

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
