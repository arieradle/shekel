---
title: Decorators – Wrap Python Functions with LLM Budget Enforcement
description: Use the @with_budget decorator to enforce an independent LLM spend limit on every function call. Ideal for reusable LLM utility functions and agent tools.
tags:
  - budget-enforcement
  - cost-tracking
  - llm-guardrails
  - getting-started
---

# Decorators

Use the `@with_budget` decorator to wrap functions with automatic budget enforcement.

## Basic Decorator Usage

Instead of wrapping every function body with `with budget()`:

```python
# Without decorator
def generate_summary(text: str) -> str:
    with budget(max_usd=0.10):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Summarize: {text}"}],
        )
        return response.choices[0].message.content
```

Use the decorator:

```python
from shekel import with_budget

# With decorator
@with_budget(max_usd=0.10)
def generate_summary(text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize: {text}"}],
    )
    return response.choices[0].message.content

# Budget enforced automatically on every call
summary = generate_summary("Long text here...")
```

!!! tip "Cleaner Code"
    Decorators make your code cleaner by moving budget configuration out of the function body. Perfect for reusable functions that always need the same budget constraints.

## How It Works

The decorator creates a fresh budget context for each function call:

```python
@with_budget(max_usd=0.50)
def process_item(item: str):
    # Each call gets its own budget
    ...

# Call 1 - fresh $0.50 budget
process_item("item1")

# Call 2 - another fresh $0.50 budget
process_item("item2")

# Call 3 - another fresh $0.50 budget
process_item("item3")
```

Each invocation is independent — budgets don't accumulate across calls.

## All Budget Parameters

The decorator supports all budget parameters:

```python
@with_budget(
    max_usd=1.00,
    warn_at=0.8,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
    price_per_1k_tokens=None,
    on_warn=None,
    on_fallback=None,
)
def my_function():
    ...
```

### Example with Multiple Parameters

```python
def log_warning(spent: float, limit: float):
    logger.warning(f"Budget warning: ${spent:.2f} / ${limit:.2f}")

@with_budget(
    max_usd=2.00,
    warn_at=0.8,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
    on_warn=log_warning,
)
def generate_report(data: dict) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Report: {data}"}],
    )
    return response.choices[0].message.content
```

## Async Functions

The decorator works seamlessly with async functions:

```python
from shekel import with_budget

@with_budget(max_usd=0.50)
async def async_summarize(text: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize: {text}"}],
    )
    return response.choices[0].message.content

# Use with await
summary = await async_summarize("Long text...")
```

## Error Handling

Handle budget errors like any other exception:

```python
from shekel import with_budget, BudgetExceededError

@with_budget(max_usd=0.01)
def expensive_call():
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Long prompt..."}],
    )
    return response.choices[0].message.content

try:
    result = expensive_call()
except BudgetExceededError as e:
    print(f"Budget exceeded: ${e.spent:.4f}")
```

## Return Values

The decorator preserves return values:

```python
@with_budget(max_usd=0.50)
def get_completion(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

result = get_completion("What is Python?")
print(result)  # The actual completion text
```

## Multiple Decorators

Combine with other decorators:

```python
from functools import lru_cache
from shekel import with_budget

@lru_cache(maxsize=100)
@with_budget(max_usd=0.10)
def cached_completion(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content

# First call - makes API request
result1 = cached_completion("What is Python?")

# Second call - returns from cache, no budget used
result2 = cached_completion("What is Python?")
```

!!! tip "Decorator Order"
    When combining decorators, `@with_budget` should typically be closest to the function definition (bottom of the stack) to ensure budget tracking happens for every actual execution.

## Class Methods

Use decorators on methods:

```python
class ReportGenerator:
    def __init__(self, client):
        self.client = client
    
    @with_budget(max_usd=1.00)
    def generate(self, data: dict) -> str:
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Report: {data}"}],
        )
        return response.choices[0].message.content

# Usage
generator = ReportGenerator(client)
report = generator.generate({"sales": 1000})
```

## Static and Class Methods

Works with static and class methods:

```python
class AIHelper:
    @staticmethod
    @with_budget(max_usd=0.50)
    def summarize(text: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Summarize: {text}"}],
        )
        return response.choices[0].message.content
    
    @classmethod
    @with_budget(max_usd=0.50)
    def analyze(cls, data: str) -> str:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Analyze: {data}"}],
        )
        return response.choices[0].message.content

# Usage
summary = AIHelper.summarize("Long text")
analysis = AIHelper.analyze("Data here")
```

## When to Use Decorators

| Scenario | Use Decorator? | Why |
|----------|---------------|-----|
| Reusable function with fixed budget | ✅ Yes | Clean, declarative |
| One-off operation | ❌ No | Use context manager |
| Need to access budget object | ❌ No | Can't access with decorator |
| Dynamic budget per call | ❌ No | Budget is fixed |
| Class methods | ✅ Yes | Works great |
| Testing | ✅ Yes | Clean test setup |

## Limitations

### Cannot Access Budget Object

With decorators, you can't access the budget object:

```python
@with_budget(max_usd=1.00)
def my_function():
    # ❌ Can't access budget object here
    # Can't check b.spent, b.remaining, etc.
    ...
```

If you need budget information, use a context manager instead:

```python
def my_function():
    with budget(max_usd=1.00) as b:
        ...
        print(f"Spent so far: ${b.spent:.4f}")
        ...
```

### Fixed Budget Parameters

Decorator parameters are fixed at definition time:

```python
@with_budget(max_usd=1.00)  # Always $1.00
def process(item: str):
    ...

# Can't change budget per call
process("item1")  # Uses $1.00 budget
process("item2")  # Uses $1.00 budget (new instance)
```

For dynamic budgets, use context managers:

```python
def process(item: str, budget_usd: float):
    with budget(max_usd=budget_usd):
        ...

process("item1", budget_usd=0.50)
process("item2", budget_usd=2.00)  # Different budget
```

### Not Persistent

Each decorated function call gets a fresh budget:

```python
@with_budget(max_usd=1.00)
def process(item: str):
    ...

# These don't accumulate
process("item1")  # Budget: $0 → $0.10
process("item2")  # Budget: $0 → $0.12  (fresh budget!)
process("item3")  # Budget: $0 → $0.09  (fresh budget!)
```

For accumulating budgets, use context managers:

```python
def process_all(items: list):
    session = budget(max_usd=5.00, name="batch")
    
    for item in items:
        with session:
            process(item)  # Accumulates automatically
```

## Testing with Decorators

Decorators make testing clean:

```python
import pytest
from shekel import with_budget, BudgetExceededError

@with_budget(max_usd=0.01)
def expensive_operation():
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Very long prompt..."}],
    )
    return response.choices[0].message.content

def test_budget_exceeded():
    with pytest.raises(BudgetExceededError):
        expensive_operation()

def test_within_budget():
    @with_budget(max_usd=10.00)
    def cheap_operation():
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hi"}],
        )
        return response.choices[0].message.content
    
    result = cheap_operation()
    assert result is not None
```

## Best Practices

### 1. Use for Consistent Budgets

```python
# Good - same budget for all calls
@with_budget(max_usd=0.50)
def summarize(text: str) -> str:
    ...
```

### 2. Combine with Type Hints

```python
from shekel import with_budget

@with_budget(max_usd=1.00)
def generate_response(prompt: str, context: dict) -> str:
    """Generate AI response within $1.00 budget."""
    ...
```

### 3. Document Budget in Docstring

```python
@with_budget(max_usd=2.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})
def analyze_data(data: dict) -> str:
    """
    Analyze data using AI.

    Budget: $2.00 per call, fallback to gpt-4o-mini at 80% ($1.60).

    Args:
        data: Data to analyze

    Returns:
        Analysis results

    Raises:
        BudgetExceededError: If $2.00 budget is exceeded
    """
    ...
```

### 4. Keep Budget Configuration Visible

```python
# Good - budget visible
@with_budget(max_usd=0.50)
def process(item: str):
    ...

# Bad - hidden configuration
def process(item: str):
    with budget(max_usd=0.50):  # Buried in function
        ...
```

## Next Steps

- **[Basic Usage](basic-usage.md)** - Context manager patterns
- **[Accumulating Budgets](accumulating-budgets.md)** - Multi-session tracking
- **[API Reference](../api-reference.md)** - Complete decorator parameters
