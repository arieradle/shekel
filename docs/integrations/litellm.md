---
title: LiteLLM Budget Control – 100+ LLM Providers, One Budget
description: "Enforce hard spend limits across 100+ LLM providers through LiteLLM. Hard caps, fallback models, loop detection, and velocity limits — all via LiteLLMs unified interface."
tags:
  - litellm
  - agent-frameworks
  - budget-enforcement
  - cost-tracking
---

# LiteLLM Integration

Shekel natively supports [LiteLLM](https://github.com/BerriAI/litellm), the unified gateway that routes to 100+ LLM providers using an OpenAI-compatible interface. Wrap any LiteLLM call in a `budget()` context to enforce hard spend limits, trigger circuit-breakers, and switch to cheaper fallback models before a runaway agent drains your wallet.

## Installation

```bash
pip install shekel[litellm]
```

Or alongside other extras:

```bash
pip install "shekel[litellm,langfuse]"
```

## Why LiteLLM + Shekel?

LiteLLM already gives you a single interface to OpenAI, Anthropic, Gemini, Cohere, Ollama, Azure, Bedrock, and 90+ more. The problem is nothing stops a buggy agent from looping indefinitely across all of them. Shekel adds the circuit-breaker: a hard dollar cap that raises `BudgetExceededError` the moment the combined spend crosses your limit, regardless of which provider LiteLLM happened to route to.

```python
import litellm
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=2.00) as b:
        # Spend tracked cumulatively across all providers
        litellm.completion(model="gpt-4o-mini", messages=[...])
        litellm.completion(model="claude-3-haiku-20240307", messages=[...])
        litellm.completion(model="gemini/gemini-1.5-flash", messages=[...])
        # BudgetExceededError fires the moment total crosses $2.00
except BudgetExceededError as e:
    print(f"Stopped at ${e.spent:.4f}")
```

## Basic Usage

```python
import litellm
from shekel import budget

with budget(max_usd=0.50) as b:
    response = litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.choices[0].message.content)

print(f"Cost: ${b.spent:.4f}")
```

## Async Support

```python
import asyncio
import litellm
from shekel import budget

async def run():
    async with budget(max_usd=1.00) as b:
        response = await litellm.acompletion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello async!"}],
        )
        print(response.choices[0].message.content)
    print(f"Cost: ${b.spent:.4f}")

asyncio.run(run())
```

## Streaming

```python
import litellm
from shekel import budget

with budget(max_usd=0.50) as b:
    stream = litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Count to 5"}],
        stream=True,
    )
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="", flush=True)

print(f"\nStreaming cost: ${b.spent:.4f}")
```

## Budget Enforcement

Hard cap and early warnings work exactly as with any other provider:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.10, warn_at=0.8) as b:
        for i in range(100):
            litellm.completion(
                model="gpt-4o",
                messages=[{"role": "user", "content": f"Question {i}"}],
            )
except BudgetExceededError as e:
    print(f"Stopped at ${e.spent:.4f} after {b.calls_used} calls")
```

## Fallback Models

Switch to a cheaper LiteLLM-routed model when budget runs low:

```python
import litellm
from shekel import budget

with budget(
    max_usd=1.00,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
) as b:
    response = litellm.completion(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello"}],
    )

if b.model_switched:
    print(f"Switched to {b.fallback['model']} at ${b.switched_at_usd:.4f}")
```

## How It Works

Shekel's `LiteLLMAdapter` patches the `litellm.completion` and `litellm.acompletion` module-level functions when the first `budget()` context is entered, and restores them when the last one exits.

LiteLLM returns responses in OpenAI-compatible format (`response.usage.prompt_tokens`, `response.usage.completion_tokens`), so token extraction is straightforward regardless of which underlying provider was used.

Model names may include a provider prefix (e.g. `gemini/gemini-1.5-flash`, `anthropic/claude-3-haiku-20240307`). Shekel passes these through to its pricing engine, which falls back to [tokencost](https://github.com/AgentOps-AI/tokencost) for extended model coverage.

## Extended Model Pricing

For accurate pricing on the full range of providers LiteLLM supports:

```bash
pip install "shekel[litellm,all-models]"
```

This installs `tokencost`, which covers 400+ models including Gemini, Cohere, Mistral, and many more.

## With LangGraph or CrewAI

LiteLLM can serve as the LLM backend for agent frameworks. Shekel tracks costs regardless:

```python
from langgraph.graph import StateGraph, END
import litellm
from shekel import budget

def call_litellm(state):
    response = litellm.completion(
        model="gemini/gemini-1.5-flash",
        messages=[{"role": "user", "content": state["question"]}],
    )
    return {"answer": response.choices[0].message.content}

graph = StateGraph({"question": str, "answer": str})
graph.add_node("llm", call_litellm)
graph.set_entry_point("llm")
graph.add_edge("llm", END)
app = graph.compile()

with budget(max_usd=0.50) as b:
    result = app.invoke({"question": "What is 2+2?", "answer": ""})
    print(f"Cost: ${b.spent:.4f}")
```

## Next Steps

- [LangGraph Integration](langgraph.md)
- [Extending Shekel](../extending.md) — add your own provider adapter
- [Supported Models](../models.md)
