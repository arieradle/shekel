---
title: HuggingFace Budget Control – Inference API Spend Limits
description: "Enforce hard USD spend limits on HuggingFace Inference API calls. Hard caps, fallback models, and nested budgets for any model on the HuggingFace hub."
tags:
  - budget-enforcement
  - llm-guardrails
  - cost-tracking
---

# HuggingFace Integration

One `pip install shekel[huggingface]` and one `with budget():` — shekel intercepts every HuggingFace `InferenceClient` call, enforces hard spend limits, and shows you exactly what was spent. Hard caps, fallback models, nested budgets, and `BudgetExceededError` all work identically to OpenAI and Anthropic.

## Installation

```bash
pip install shekel[huggingface]
```

## Why a dedicated adapter?

HuggingFace's `InferenceClient` uses its own HTTP layer — it does **not** call the OpenAI SDK under the hood. Without a dedicated adapter, `budget()` would be completely blind to HuggingFace spend.

Shekel's `HuggingFaceAdapter` patches two methods at runtime:

- `InferenceClient.chat_completion` — sync calls
- `AsyncInferenceClient.chat_completion` — async calls

Since `client.chat.completions.create()` delegates to `chat_completion` internally, all calls through either interface are tracked automatically.

## Important: Custom Pricing Required

!!! warning "No bundled HuggingFace pricing"
    HuggingFace hosts thousands of models with varying pricing. Shekel has no standard pricing table for HuggingFace models.

    **Always pass `price_per_1k_tokens` to `budget()`** so Shekel can calculate costs:

    ```python
    with budget(max_usd=1.00, price_per_1k_tokens={"input": 0.001, "output": 0.001}):
        ...
    ```

    If you omit this, `b.spent` will always be `0.0` even though tokens were consumed.

## Basic Integration

```python
from huggingface_hub import InferenceClient
from shekel import budget

client = InferenceClient(token="your-hf-token")

with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.001, "output": 0.001},
) as b:
    response = client.chat.completions.create(
        model="meta-llama/Llama-3.2-1B-Instruct",
        messages=[{"role": "user", "content": "Explain transformers in one sentence."}],
        max_tokens=50,
    )
    print(response.choices[0].message.content)
    print(f"Cost: ${b.spent:.6f}")
```

## Streaming

```python
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.001, "output": 0.001},
) as b:
    full_text = ""
    for chunk in client.chat.completions.create(
        model="meta-llama/Llama-3.2-1B-Instruct",
        messages=[{"role": "user", "content": "List three ML frameworks."}],
        max_tokens=60,
        stream=True,
    ):
        delta = chunk.choices[0].delta.content
        if delta:
            full_text += delta
            print(delta, end="", flush=True)
    print()
    print(f"Cost: ${b.spent:.6f}")
```

!!! note "Streaming usage availability"
    Many HuggingFace-hosted models do not return `usage` data in streaming chunks. In that case, `b.spent` will be `0.0` for streaming calls even if tokens were consumed. Non-streaming calls generally do return usage data.

## Async

`AsyncInferenceClient` is tracked automatically — no extra setup needed:

```python
import asyncio
from huggingface_hub import AsyncInferenceClient
from shekel import budget

client = AsyncInferenceClient(token="your-hf-token")

async def main() -> None:
    async with budget(
        max_usd=1.00,
        price_per_1k_tokens={"input": 0.001, "output": 0.001},
    ) as b:
        response = await client.chat_completion(
            model="meta-llama/Llama-3.2-1B-Instruct",
            messages=[{"role": "user", "content": "Explain transformers in one sentence."}],
            max_tokens=50,
        )
        print(response.choices[0].message.content)
        print(f"Cost: ${b.spent:.6f}")

asyncio.run(main())
```

!!! note "Streaming usage availability"
    The same caveat applies to async streaming: many HuggingFace-hosted models do not return `usage` data in streaming chunks, so `b.spent` may be `0.0` for streaming calls.

## Nested Budgets

```python
with budget(
    max_usd=5.00,
    name="pipeline",
    price_per_1k_tokens={"input": 0.001, "output": 0.001},
) as total:
    with budget(
        max_usd=1.00,
        name="step-1",
        price_per_1k_tokens={"input": 0.001, "output": 0.001},
    ) as step1:
        client.chat.completions.create(
            model="meta-llama/Llama-3.2-1B-Instruct",
            messages=[{"role": "user", "content": "Summarise this document."}],
            max_tokens=100,
        )

print(f"Step 1: ${step1.spent:.6f}")
print(f"Total:  ${total.spent:.6f}")
```

## Budget Enforcement

```python
from shekel import BudgetExceededError

try:
    with budget(
        max_usd=0.10,
        price_per_1k_tokens={"input": 0.001, "output": 0.001},
    ) as b:
        for _ in range(100):  # Shekel stops this when budget runs out
            client.chat.completions.create(
                model="meta-llama/Llama-3.2-1B-Instruct",
                messages=[{"role": "user", "content": "Analyse this."}],
                max_tokens=50,
            )
except BudgetExceededError as e:
    print(f"Stopped at ${e.spent:.4f}")
```

## Free vs Paid Models

HuggingFace offers two tiers for inference:

| Tier | Description | Pricing |
|---|---|---|
| Free (Serverless) | Limited RPM, shared infrastructure | Free but rate-limited |
| PRO / Inference Endpoints | Dedicated infrastructure | Pay per token / per hour |

For most chat models, use `InferenceClient` with an `hf_*` token. Free-tier models may return 503 when overloaded — add retry logic for production use.

## Tips for HuggingFace + Shekel

1. **Always set `price_per_1k_tokens`** — there is no default pricing for HuggingFace models
2. **Use non-streaming calls for accurate cost tracking** — many models omit usage in streaming
3. **Check model availability** — not all models are available on HuggingFace's serverless API
4. **Handle 503 errors** — free-tier endpoints can be temporarily unavailable under load
5. **Use `max_tokens`** to cap response length and control costs

## Next Steps

- [Google Gemini Integration](gemini.md)
- [Nested Budgets](../usage/nested-budgets.md)
- [Budget Enforcement](../usage/budget-enforcement.md)
- [Extending Shekel](../extending.md)
