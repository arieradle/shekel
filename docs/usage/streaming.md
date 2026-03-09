# Streaming

Budget tracking works seamlessly with streaming responses from both OpenAI and Anthropic.

## OpenAI Streaming

Track costs for OpenAI streaming responses:

```python
from shekel import budget
import openai

client = openai.OpenAI()

with budget(max_usd=0.50) as b:
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Count from 1 to 10"}],
        stream=True,
    )
    
    for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        print(content, end="", flush=True)

print(f"\nStreaming cost: ${b.spent:.4f}")
```

!!! tip "How It Works"
    Shekel automatically sets `stream_options={"include_usage": True}` on OpenAI streaming requests. This causes OpenAI to include usage information in the final chunk, which shekel uses to track costs accurately.

## Anthropic Streaming

Track costs for Anthropic streaming responses:

```python
import anthropic
from shekel import budget

client = anthropic.Anthropic()

with budget(max_usd=0.50) as b:
    with client.messages.stream(
        model="claude-3-haiku-20240307",
        max_tokens=1000,
        messages=[{"role": "user", "content": "Write a haiku"}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)

print(f"\nStreaming cost: ${b.spent:.4f}")
```

## Budget Enforcement with Streaming

Budget limits work with streaming — the cost is checked after the stream completes:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.01) as b:  # Very low limit
        stream = client.chat.completions.create(
            model="gpt-4o",  # Expensive model
            messages=[{"role": "user", "content": "Write a long essay"}],
            stream=True,
        )
        
        for chunk in stream:
            print(chunk.choices[0].delta.content or "", end="")
    
    print(f"\nCompleted: ${b.spent:.4f}")

except BudgetExceededError as e:
    print(f"\n\nBudget exceeded after stream: ${e.spent:.4f}")
```

!!! warning "Cost Checked After Stream"
    With streaming, shekel can only check the budget **after** the full stream completes. The stream will complete even if it exceeds the budget, and the error is raised afterward. Use [fallback models](fallback-models.md) for better control.

## Streaming with Fallback

Combine streaming with model fallback:

```python
with budget(max_usd=1.00, fallback="gpt-4o-mini") as b:
    # First stream - uses gpt-4o
    stream1 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "First question"}],
        stream=True,
    )
    for chunk in stream1:
        print(chunk.choices[0].delta.content or "", end="")
    
    print(f"\nFirst stream: ${b.spent:.4f}")
    
    # Second stream - might use gpt-4o-mini if switched
    stream2 = client.chat.completions.create(
        model="gpt-4o",  # Automatically becomes gpt-4o-mini if fallback activated
        messages=[{"role": "user", "content": "Second question"}],
        stream=True,
    )
    for chunk in stream2:
        print(chunk.choices[0].delta.content or "", end="")
    
    if b.model_switched:
        print(f"\nSwitched to fallback at ${b.switched_at_usd:.4f}")
```

## Async Streaming

Full support for async streaming:

### OpenAI Async Streaming

```python
import asyncio
from shekel import budget

async def stream_with_budget():
    async with budget(max_usd=0.50) as b:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Count to 10"}],
            stream=True,
        )
        
        async for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            print(content, end="", flush=True)
    
    print(f"\nAsync streaming cost: ${b.spent:.4f}")

asyncio.run(stream_with_budget())
```

### Anthropic Async Streaming

```python
import asyncio
import anthropic
from shekel import budget

async def stream_with_budget():
    client = anthropic.AsyncAnthropic()
    
    async with budget(max_usd=0.50) as b:
        async with client.messages.stream(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=[{"role": "user", "content": "Write a poem"}],
        ) as stream:
            async for text in stream.text_stream:
                print(text, end="", flush=True)
    
    print(f"\nAsync streaming cost: ${b.spent:.4f}")

asyncio.run(stream_with_budget())
```

## Multiple Streams

Track costs across multiple streams:

```python
with budget(max_usd=1.00) as b:
    questions = [
        "What is Python?",
        "What is JavaScript?",
        "What is Rust?",
    ]
    
    for i, question in enumerate(questions, 1):
        print(f"\n=== Question {i} ===\n")
        
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": question}],
            stream=True,
        )
        
        for chunk in stream:
            print(chunk.choices[0].delta.content or "", end="")
        
        print(f"\n\nAfter {i} streams: ${b.spent:.4f}")
    
    print(f"\n\nTotal for all streams: ${b.spent:.4f}")
```

## Streaming with Progress Bars

Combine with progress indicators:

```python
from tqdm import tqdm
from shekel import budget

with budget(max_usd=0.50) as b:
    questions = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    
    for question in tqdm(questions, desc="Processing"):
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": question}],
            stream=True,
        )
        
        response_text = ""
        for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            response_text += content
        
        # Process response_text
    
    print(f"Total cost: ${b.spent:.4f}")
```

## Streaming with Real-time Cost Display

Show costs as they accumulate:

```python
from shekel import budget

session = budget(max_usd=5.00, persistent=True)

def stream_with_display(prompt: str):
    with session:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        
        for chunk in stream:
            print(chunk.choices[0].delta.content or "", end="", flush=True)
    
    print(f"\n[Cost: ${session.spent:.4f} / ${session.limit:.2f}]")

# Use multiple times
stream_with_display("Tell me about Python")
stream_with_display("Tell me about JavaScript")
stream_with_display("Tell me about Rust")
```

## Streaming with Token Tracking

Track tokens in addition to costs:

```python
with budget() as b:
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Explain quantum computing"}],
        stream=True,
    )
    
    # Collect full response
    full_response = ""
    for chunk in stream:
        content = chunk.choices[0].delta.content or ""
        full_response += content
        print(content, end="", flush=True)
    
    # Get summary with token counts
    summary = b.summary_data()
    last_call = summary["calls"][-1]
    
    print(f"\n\nInput tokens: {last_call['input_tokens']}")
    print(f"Output tokens: {last_call['output_tokens']}")
    print(f"Cost: ${last_call['cost']:.6f}")
```

## Handling Stream Interruptions

Gracefully handle interrupted streams:

```python
import signal
from shekel import budget

def handle_interrupt(signum, frame):
    print("\n\nStream interrupted by user")
    raise KeyboardInterrupt

signal.signal(signal.SIGINT, handle_interrupt)

try:
    with budget(max_usd=0.50) as b:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Write a very long story"}],
            stream=True,
        )
        
        for chunk in stream:
            print(chunk.choices[0].delta.content or "", end="", flush=True)

except KeyboardInterrupt:
    print(f"\n\nCost before interruption: ${b.spent:.4f}")
```

!!! note "Cost on Interruption"
    If you interrupt a stream (e.g., with Ctrl+C), the cost will still be recorded. OpenAI and Anthropic charge for all tokens generated, even if you don't consume the full stream.

## Streaming Best Practices

### 1. Use Persistent Budgets for Multiple Streams

```python
# Good - accumulates across streams
session = budget(max_usd=5.00, persistent=True)
for item in items:
    with session:
        stream_response(item)
```

### 2. Set Appropriate Timeouts

```python
# Add timeouts to prevent hanging
client = openai.OpenAI(timeout=30.0)

with budget(max_usd=1.00):
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    # Will timeout after 30 seconds
```

### 3. Buffer Small Chunks

```python
# Buffer output for smoother display
import sys

with budget(max_usd=0.50):
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Long response"}],
        stream=True,
    )
    
    buffer = ""
    for chunk in stream:
        buffer += chunk.choices[0].delta.content or ""
        if len(buffer) > 10:  # Flush every 10 characters
            print(buffer, end="", flush=True)
            buffer = ""
    
    if buffer:  # Flush remaining
        print(buffer, flush=True)
```

### 4. Handle Errors Gracefully

```python
from shekel import budget, BudgetExceededError

def safe_stream(prompt: str):
    try:
        with budget(max_usd=0.50) as b:
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            
            response = ""
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                response += content
                print(content, end="", flush=True)
            
            return response
    
    except BudgetExceededError as e:
        print(f"\n[Budget exceeded: ${e.spent:.4f}]")
        return None
    
    except Exception as e:
        print(f"\n[Error: {e}]")
        return None
```

## Limitations

!!! warning "Streaming Limitations"
    1. **Cost checked after completion**: Budget is enforced after the stream finishes, not during
    2. **Cannot stop mid-stream**: Once started, the stream completes even if it will exceed budget
    3. **Full cost charged**: Even if you stop consuming the stream early, you're charged for all generated tokens

    For real-time budget control, consider:
    - Using non-streaming requests
    - Setting `max_tokens` parameter to limit response length
    - Using cheaper models with streaming

## Next Steps

- **[Decorators](decorators.md)** - Using @with_budget for cleaner code
- **[Basic Usage](basic-usage.md)** - Non-streaming examples
- **[API Reference](../api-reference.md)** - Complete streaming parameters
