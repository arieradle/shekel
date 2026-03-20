---
title: Google Gemini Budget Control – Spend Limits and Cost Tracking
description: Enforce hard USD spend limits on Google Gemini API calls (Gemini 2.0 Flash, 2.5 Flash, 2.5 Pro). Hard caps, fallback models, nested budgets — zero SDK changes.
tags:
  - gemini
  - budget-enforcement
  - llm-guardrails
  - cost-tracking
---

# Google Gemini Integration

One `pip install shekel[gemini]` and one `with budget():` — shekel intercepts every Gemini call, enforces hard spend limits, and shows you exactly what was spent. All the same budget controls (hard caps, fallback models, nested budgets, `BudgetExceededError`) work identically to OpenAI and Anthropic.

## Installation

```bash
pip install shekel[gemini]
```

## Why a dedicated adapter?

Unlike OpenAI and Anthropic, Gemini uses its own SDK (`google-genai`) that makes direct API calls — it does **not** route through the OpenAI SDK. Without a dedicated adapter, `budget()` would be completely blind to Gemini spend.

Shekel's `GeminiAdapter` patches four methods at runtime:

- `google.genai.models.Models.generate_content` — sync non-streaming calls
- `google.genai.models.Models.generate_content_stream` — sync streaming calls
- `google.genai.models.AsyncModels.generate_content` — async non-streaming calls
- `google.genai.models.AsyncModels.generate_content_stream` — async streaming calls

All Shekel features (nested budgets, fallback models, `BudgetExceededError`) work identically across sync and async.

## Basic Integration

```python
import google.genai as genai
from shekel import budget

client = genai.Client(api_key="your-gemini-key")

with budget(max_usd=1.00) as b:
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents="Explain quantum computing in one sentence.",
    )
    print(response.candidates[0].content.parts[0].text)
    print(f"Cost: ${b.spent:.6f}")
```

## Streaming

Gemini streaming uses a **separate method** (`generate_content_stream`) rather than a `stream=True` kwarg — Shekel patches both:

```python
with budget(max_usd=1.00) as b:
    for chunk in client.models.generate_content_stream(
        model="gemini-2.0-flash-lite",
        contents="List three benefits of Python.",
    ):
        if chunk.candidates:
            print(chunk.candidates[0].content.parts[0].text, end="", flush=True)
    print()
    print(f"Cost: ${b.spent:.6f}")
```

## Async

Both `AsyncModels.generate_content` and `AsyncModels.generate_content_stream` are tracked automatically:

```python
import asyncio
import google.genai as genai
from shekel import budget

client = genai.Client(api_key="your-gemini-key")

async def main() -> None:
    async with budget(max_usd=1.00) as b:
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents="Explain quantum computing in one sentence.",
        )
        print(response.text)
        print(f"Cost: ${b.spent:.6f}")

asyncio.run(main())
```

Async streaming works the same way — iterate `client.aio.models.generate_content_stream(...)` with `async for`.

## Nested Budgets

Track costs across multi-step Gemini workflows:

```python
with budget(max_usd=5.00, name="pipeline") as total:
    with budget(max_usd=1.00, name="research") as research:
        client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents="Summarise recent AI trends.",
        )

    with budget(max_usd=2.00, name="analysis") as analysis:
        client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Analyse the implications of those trends.",
        )

print(f"Research: ${research.spent:.6f}")
print(f"Analysis: ${analysis.spent:.6f}")
print(f"Total:    ${total.spent:.6f}")
print(total.tree())
```

## Fallback Models

Switch to a cheaper Gemini model when spend reaches a threshold:

```python
with budget(
    max_usd=0.50,
    fallback={"at_pct": 0.8, "model": "gemini-2.0-flash-lite"},
) as b:
    # Starts with gemini-2.0-flash; auto-switches at 80% ($0.40)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Write a detailed market analysis.",
    )

if b.model_switched:
    print(f"Switched to fallback at ${b.switched_at_usd:.4f}")
```

!!! note "Same-provider fallback only"
    Fallback must be another Gemini model. Cross-provider fallback (e.g. Gemini → GPT-4o) is not supported.

## Budget Enforcement

Stop a runaway Gemini loop automatically:

```python
from shekel import BudgetExceededError

try:
    with budget(max_usd=2.00) as b:
        for _ in range(100):  # Shekel stops this when budget runs out
            client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents="Analyse this document.",
            )
except BudgetExceededError as e:
    print(f"Stopped at ${e.spent:.4f} — saved the rest of the budget.")
```

## Supported Models and Pricing

| Model | Input (per 1k tokens) | Output (per 1k tokens) |
|---|---|---|
| `gemini-2.5-pro` | $0.00125 | $0.01000 |
| `gemini-2.5-flash` | $0.000075 | $0.00030 |
| `gemini-2.0-flash` | $0.000075 | $0.00030 |
| `gemini-2.0-flash-lite` | $0.000075 | $0.00030 |
| `gemini-1.5-pro` | $0.00125 | $0.00500 |
| `gemini-1.5-flash` | $0.000075 | $0.00030 |

Shekel uses prefix matching, so `gemini-2.0-flash-001` and similar versioned names resolve automatically.

## Custom Pricing

For models not in the pricing table, pass `price_per_1k_tokens`:

```python
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.0001, "output": 0.0003},
) as b:
    client.models.generate_content(
        model="gemini-3-flash-preview",
        contents="Hello.",
    )
```

## Tips for Gemini + Shekel

1. **Use `generate_content_stream` for long responses** — streaming lets you stop mid-generation if the budget is hit
2. **Wrap at the workflow level**, not per-call, for accurate total cost tracking
3. **Set `warn_at=0.8`** to log a warning before the budget cap triggers
4. **Gemini free tier has per-minute limits** — use exponential backoff for production workloads

## Next Steps

- [HuggingFace Integration](huggingface.md)
- [Nested Budgets](../usage/nested-budgets.md)
- [Fallback Models](../usage/fallback-models.md)
- [Extending Shekel](../extending.md)
