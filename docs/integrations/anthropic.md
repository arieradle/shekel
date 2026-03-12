# Anthropic Integration

One `pip install` and one `with budget():` — shekel intercepts every Anthropic call automatically, enforces hard spend limits, and shows you exactly what was spent. No API keys, no SDK changes, no configuration.

## Installation

```bash
pip install shekel[anthropic]
```

## Basic Usage

```python
import anthropic
from shekel import budget

client = anthropic.Anthropic()

with budget(max_usd=0.50) as b:
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.content[0].text)

print(f"Cost: ${b.spent:.4f}")
```

## All Supported Models

Shekel supports all Claude models:

```python
models = [
    "claude-3-5-sonnet-20241022",
    "claude-3-haiku-20240307",
    "claude-3-opus-20240229",
]

with budget() as b:
    for model in models:
        response = client.messages.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": "Hi"}],
        )
        print(f"{model}: {response.content[0].text[:30]}...")
    
    print(f"Total: ${b.spent:.4f}")
```

## Streaming

```python
with budget(max_usd=0.50) as b:
    with client.messages.stream(
        model="claude-3-haiku-20240307",
        max_tokens=1000,
        messages=[{"role": "user", "content": "Write a haiku"}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)

print(f"\nCost: ${b.spent:.4f}")
```

## Async

```python
import asyncio
from anthropic import AsyncAnthropic

async def main():
    client = AsyncAnthropic()
    
    async with budget(max_usd=0.50) as b:
        response = await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(response.content[0].text)
    
    print(f"Cost: ${b.spent:.4f}")

asyncio.run(main())
```

## Multi-Turn Conversations

```python
conversation = budget(max_usd=2.00, name="conversation")
messages = []

def chat(user_message: str):
    messages.append({"role": "user", "content": user_message})
    
    with conversation:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=messages,
        )
        assistant_message = response.content[0].text
        messages.append({"role": "assistant", "content": assistant_message})
        return assistant_message

# Multi-turn conversation - costs accumulate automatically
print(chat("Hello! What's your name?"))
print(f"After turn 1: ${conversation.spent:.4f}\n")

print(chat("Tell me about Python"))
print(f"After turn 2: ${conversation.spent:.4f}\n")

print(chat("Thanks!"))
print(f"Total conversation: ${conversation.spent:.4f}")
```

## Fallback Models

```python
with budget(max_usd=0.50, fallback={"at_pct": 0.8, "model": "claude-3-haiku-20240307"}) as b:
    response = client.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=1000,
        messages=[{"role": "user", "content": "Explain AI"}],
    )
    print(response.content[0].text)
    
    if b.model_switched:
        print(f"\nSwitched to haiku at ${b.switched_at_usd:.4f}")
```

## Complete Example

```python
import anthropic
from shekel import budget, BudgetExceededError

client = anthropic.Anthropic()

# 1. Basic usage
print("=== Basic ===")
with budget(max_usd=0.10) as b:
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{"role": "user", "content": "Say hello"}],
    )
    print(response.content[0].text)
print(f"Cost: ${b.spent:.4f}")

# 2. Streaming
print("\n=== Streaming ===")
with budget(max_usd=0.10) as b:
    with client.messages.stream(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{"role": "user", "content": "Count to 5"}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
print(f"\nCost: ${b.spent:.4f}")

# 3. Budget enforcement
print("\n=== Budget Enforcement ===")
try:
    with budget(max_usd=0.01) as b:
        response = client.messages.create(
            model="claude-3-opus-20240229",  # Expensive
            max_tokens=1000,
            messages=[{"role": "user", "content": "Long essay"}],
        )
except BudgetExceededError as e:
    print(f"Budget exceeded: ${e.spent:.4f}")
```

## Next Steps

- [OpenAI Integration](openai.md)
- [LangGraph Integration](langgraph.md)
- [Budget Enforcement](../usage/budget-enforcement.md)
