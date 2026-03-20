# OpenAI Integration

One `pip install` and one `with budget():` — shekel intercepts every OpenAI call automatically, enforces hard spend limits, and shows you exactly what was spent. No API keys, no SDK changes, no configuration.

## Installation

```bash
pip install shekel[openai]
```

## Basic Usage

```python
import openai
from shekel import budget

client = openai.OpenAI()

with budget(max_usd=0.50) as b:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.choices[0].message.content)

print(f"Cost: ${b.spent:.4f}")
```

## All Supported Models

Shekel supports all OpenAI models with automatic version resolution:

```python
# Base models
models = ["gpt-4o", "gpt-4o-mini", "o1", "o1-mini", "gpt-3.5-turbo"]

# Versioned models (automatically resolved)
versioned = [
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-05-13",
    "gpt-4o-mini-2024-07-18",
]

with budget() as b:
    for model in models:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=10,
        )
    print(f"Total: ${b.spent:.4f}")
```

## Streaming

```python
with budget(max_usd=0.50) as b:
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Count to 10"}],
        stream=True,
    )

    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="", flush=True)

print(f"\nCost: ${b.spent:.4f}")
```

## Async

```python
import asyncio

async def main():
    async with budget(max_usd=0.50) as b:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(response.choices[0].message.content)

    print(f"Cost: ${b.spent:.4f}")

asyncio.run(main())
```

## Batch Processing

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
    print(f"Processed {len(results)}/{len(items)} items")

print(f"Cost: ${b.spent:.4f}")
```

## Complete Example

Full example with all OpenAI features from the codebase:

```python
import openai
from shekel import budget, BudgetExceededError

client = openai.OpenAI()

# 1. Basic budget enforcement
print("=== Basic budget ===")
try:
    with budget(max_usd=0.10, warn_at=0.8) as b:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say hello"}],
        )
        print(response.choices[0].message.content)
    print(f"Spent: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: {e}")

# 2. Versioned model names
print("\n=== Versioned model ===")
with budget() as b:
    response = client.chat.completions.create(
        model="gpt-4o-2024-08-06",  # Resolves to gpt-4o
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=10,
    )
    print(response.choices[0].message.content)
print(f"Cost: ${b.spent:.6f}")

# 3. Fallback to cheaper model
print("\n=== Fallback ===")
with budget(max_usd=0.001, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "What is the capital of France?"}],
    )
    print(response.choices[0].message.content)
if b.model_switched:
    print(f"Switched at ${b.switched_at_usd:.4f}")
print(f"Total: ${b.spent:.4f}")

# 4. Streaming
print("\n=== Streaming ===")
with budget(max_usd=0.10) as b:
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Count to 5"}],
        stream=True,
    )
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="", flush=True)
print(f"\nCost: ${b.spent:.4f}")

# 5. Batch with early stop
print("\n=== Batch ===")
items = ["red", "blue", "green"]
results = []
try:
    with budget(max_usd=0.05) as b:
        for item in items:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Color: {item}"}],
                max_tokens=20,
            )
            results.append(response.choices[0].message.content)
except BudgetExceededError:
    print(f"Stopped at {len(results)}/{len(items)}")
print(f"Cost: ${b.spent:.4f}")
```

## Next Steps

- [Anthropic Integration](https://arieradle.github.io/shekel/1.1.0/integrations/anthropic/index.md)
- [LangGraph Integration](https://arieradle.github.io/shekel/1.1.0/integrations/langgraph/index.md)
- [Streaming Guide](https://arieradle.github.io/shekel/1.1.0/usage/streaming/index.md)
