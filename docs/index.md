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

## What's New in v0.2.6

<div class="grid cards" markdown>

-   :material-swap-horizontal:{ .lg .middle } **[Smart Fallback](changelog.md#026)**

    ---

    `fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}` — automatically switch to a cheaper model instead of crashing. Fallback shares the same `max_usd` budget.

-   :material-bell-outline:{ .lg .middle } **[Early Warning Callbacks](changelog.md#026)**

    ---

    `on_warn` callback fires at `warn_at` threshold before the budget is exhausted.

-   :material-counter:{ .lg .middle } **[Call-Count Budgets](changelog.md#026)**

    ---

    `max_llm_calls=50` caps by number of LLM API calls, combinable with `max_usd`.

-   :material-transit-connection-variant:{ .lg .middle } **[LiteLLM Support](integrations/litellm.md)**

    ---

    Native adapter for LiteLLM — hard budget caps and circuit-breaking across 100+ providers (Gemini, Cohere, Ollama, Azure, Bedrock…). One limit, every provider.

    ```python
    pip install shekel[litellm]
    ```

-   :material-google:{ .lg .middle } **[Google Gemini](integrations/gemini.md)**

    ---

    Native adapter for the `google-genai` SDK — enforce budgets on `generate_content` and streaming. Pricing bundled for Gemini 2.0 Flash, 2.5 Flash, and 2.5 Pro.

    ```python
    pip install shekel[gemini]
    ```

-   :material-robot:{ .lg .middle } **[HuggingFace Inference API](integrations/huggingface.md)**

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
