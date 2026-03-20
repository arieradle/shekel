---
title: Basic Usage – LLM Budget Tracking and Enforcement in Python
description: Track LLM API spend and enforce hard USD caps with one line of Python. Works with OpenAI, Anthropic, LiteLLM, and any framework that calls them. No API keys, no setup.
tags:
  - budget-enforcement
  - cost-tracking
  - openai
  - anthropic
  - getting-started
---

# Basic Usage

This guide covers the fundamentals of using shekel to enforce LLM API budgets and track spend.

## Track-Only Mode

Use `budget()` without `max_usd` to measure spend without enforcing a hard cap:

```python
from shekel import budget
import openai

client = openai.OpenAI()

with budget() as b:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.choices[0].message.content)

print(f"Cost: ${b.spent:.4f}")
print(f"Limit: {b.limit}")  # None in track-only mode
```

!!! tip "Track-Only Mode"
    Without `max_usd`, shekel records spend but never raises `BudgetExceededError`. Use this to measure baseline costs before setting a hard cap, or in production when you want visibility without the risk of interrupting service.

    You can also track from the CLI without touching the script:
    ```bash
    shekel run agent.py          # no --budget = track only
    shekel run agent.py --dry-run  # explicit dry-run mode
    ```

## Enforcing a Budget

Add a hard cap to any script — two ways:

```python
with budget(max_usd=1.00) as b:
    run_agent()
# or from the CLI — zero code changes:
# shekel run agent.py --budget 1
```

## Accessing Budget Information

The budget context manager provides several properties:

```python
with budget(max_usd=1.00) as b:
    run_agent()

# After execution
print(f"Spent: ${b.spent:.4f}")           # Total USD spent
print(f"Remaining: ${b.remaining:.4f}")   # USD remaining (or None)
print(f"Limit: ${b.limit}")               # Configured max_usd (or None)
```

## Multiple API Calls

Shekel automatically tracks all API calls within the context:

```python
with budget(max_usd=0.50) as b:
    # Multiple calls accumulate
    response1 = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "First question"}],
    )
    
    response2 = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Second question"}],
    )
    
    response3 = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Third question"}],
    )

print(f"Total for 3 calls: ${b.spent:.4f}")
```

## Mixing OpenAI and Anthropic

Shekel tracks both OpenAI and Anthropic calls in the same budget:

```python
import openai
import anthropic
from shekel import budget

openai_client = openai.OpenAI()
anthropic_client = anthropic.Anthropic()

with budget(max_usd=1.00) as b:
    # OpenAI call
    openai_response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello from OpenAI"}],
    )
    
    # Anthropic call
    anthropic_response = anthropic_client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hello from Anthropic"}],
    )

print(f"Combined cost: ${b.spent:.4f}")
```

## Error Handling

When a budget is exceeded, shekel raises `BudgetExceededError`:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.01) as b:  # Very low limit
        response = client.chat.completions.create(
            model="gpt-4o",  # Expensive model
            messages=[{"role": "user", "content": "Tell me a story"}],
        )
except BudgetExceededError as e:
    print(f"Budget exceeded!")
    print(f"Spent: ${e.spent:.4f}")
    print(f"Limit: ${e.limit:.2f}")
    print(f"Model: {e.model}")
    print(f"Tokens: {e.tokens}")
```

The exception provides rich information:

| Attribute | Description |
|-----------|-------------|
| `e.spent` | Total USD spent when limit was hit |
| `e.limit` | The configured `max_usd` |
| `e.model` | Model that triggered the error |
| `e.tokens` | Token counts `{"input": N, "output": N}` |

## Nested Contexts

Budget contexts are properly isolated — nested contexts don't interfere:

```python
# Outer budget
with budget(max_usd=5.00) as outer:
    response1 = client.chat.completions.create(...)
    
    # Inner budget (separate tracking)
    with budget(max_usd=1.00) as inner:
        response2 = client.chat.completions.create(...)
        print(f"Inner: ${inner.spent:.4f}")
    
    response3 = client.chat.completions.create(...)
    print(f"Outer: ${outer.spent:.4f}")
```

!!! note "Context Isolation"
    Each `with budget()` block creates an independent tracking context using Python's `ContextVar`. Concurrent agents and nested contexts never interfere with each other.

## Custom Model Pricing

For models not in shekel's built-in table, provide custom pricing:

```python
# Custom model or unlisted provider
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.002, "output": 0.006}
) as b:
    response = client.chat.completions.create(
        model="my-custom-model",
        messages=[{"role": "user", "content": "Hello"}],
    )

print(f"Cost with custom pricing: ${b.spent:.4f}")
```

!!! tip "Custom Pricing"
    Custom pricing overrides shekel's built-in table. Use this for:
    
    - Private/proprietary models
    - Fine-tuned models with different pricing
    - Models not yet in shekel's database
    - Testing with mock pricing

## Versioned Model Names

Shekel automatically resolves versioned model names to the correct pricing:

```python
with budget() as b:
    # All of these resolve to "gpt-4o" pricing
    client.chat.completions.create(
        model="gpt-4o",              # Base name
        messages=[{"role": "user", "content": "Hello"}],
    )
    
    client.chat.completions.create(
        model="gpt-4o-2024-08-06",   # Versioned name
        messages=[{"role": "user", "content": "Hello"}],
    )
    
    client.chat.completions.create(
        model="gpt-4o-2024-05-13",   # Different version
        messages=[{"role": "user", "content": "Hello"}],
    )

print(f"All tracked under gpt-4o pricing: ${b.spent:.4f}")
```

## Batch Processing

Track costs for batch operations with early termination:

```python
from shekel import budget, BudgetExceededError

items = ["apple", "banana", "cherry", "date", "elderberry"]
results = []

try:
    with budget(max_usd=0.10) as b:
        for item in items:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Fact about {item}"}],
                max_tokens=30,
            )
            results.append(response.choices[0].message.content)
except BudgetExceededError:
    print(f"Budget hit after {len(results)}/{len(items)} items")

print(f"Processed {len(results)} items for ${b.spent:.4f}")
```

## Spend Summary

Get a detailed breakdown of all calls:

```python
with budget(max_usd=2.00) as b:
    # Make various API calls
    for i in range(10):
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Question {i}"}],
        )

# Print formatted summary
print(b.summary())
```

Output:

```
┌─ Shekel Budget Summary ────────────────────────────────────┐
│ Total: $0.0045  Limit: $2.00  Calls: 10  Status: OK
├────────────────────────────────────────────────────────────┤
│  #    Model                        Input  Output      Cost
│  ────────────────────────────────────────────────────────
│  1    gpt-4o-mini                    120      30  $0.0000
│  2    gpt-4o-mini                    115      28  $0.0000
│  3    gpt-4o-mini                    118      31  $0.0000
│  ...
├────────────────────────────────────────────────────────────┤
│  gpt-4o-mini: 10 calls  $0.0045
└────────────────────────────────────────────────────────────┘
```

Or get structured data:

```python
data = b.summary_data()
print(f"Total calls: {data['total_calls']}")
print(f"Total spent: ${data['total_spent']:.4f}")
print(f"Models used: {list(data['by_model'].keys())}")
```

## Next Steps

**Protect against the other ways agents go wrong:**

- **[Loop Guard](loop-guard.md)** — detect and stop infinite tool-call loops before they drain your budget
- **[Spend Velocity](spend-velocity.md)** — cap burn rate so a bursty agent can't blow through `max_usd` in seconds
- **[Tool Budgets](tool-budgets.md)** — cap total tool dispatches and charge per-tool

**Go deeper:**

- **[Budget Enforcement](budget-enforcement.md)** — hard caps, warnings, and `warn_only` mode
- **[Fallback Models](fallback-models.md)** — automatic model switching instead of crashing
- **[Nested Budgets](nested-budgets.md)** — per-stage limits for multi-step pipelines
- **[Accumulating Budgets](accumulating-budgets.md)** — multi-session tracking
- **[CLI Reference](../cli.md)** — `shekel run` for code-free enforcement
- **[API Reference](../api-reference.md)** — complete parameter reference
