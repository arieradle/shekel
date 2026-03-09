# API Reference

Complete reference for all shekel APIs.

## `budget()`

Context manager for tracking and enforcing LLM API budgets.

### Signature

```python
def budget(
    max_usd: float | None = None,
    warn_at: float | None = None,
    on_exceed: Callable[[float, float], None] | None = None,
    price_per_1k_tokens: dict[str, float] | None = None,
    fallback: str | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
    persistent: bool = False,
    hard_cap: float | None = None,
) -> Budget
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_usd` | `float \| None` | `None` | Maximum spend in USD. `None` = track-only mode (no enforcement). |
| `warn_at` | `float \| None` | `None` | Fraction (0.0-1.0) of `max_usd` at which to warn. |
| `on_exceed` | `Callable[[float, float], None] \| None` | `None` | Callback fired at `warn_at` threshold. Receives `(spent, limit)`. |
| `price_per_1k_tokens` | `dict[str, float] \| None` | `None` | Override pricing: `{"input": X, "output": Y}` per 1k tokens. |
| `fallback` | `str \| None` | `None` | Model to switch to when `max_usd` is hit. Same provider only. |
| `on_fallback` | `Callable[[float, float, str], None] \| None` | `None` | Callback on fallback switch. Receives `(spent, limit, fallback_model)`. |
| `persistent` | `bool` | `False` | If `True`, accumulate spend across multiple `with` blocks. |
| `hard_cap` | `float \| None` | `max_usd * 2` | Absolute ceiling when fallback is active. Default: `max_usd * 2`. |

### Returns

`Budget` object that can be used as a context manager.

### Examples

#### Track-Only Mode

```python
with budget() as b:
    run_agent()
print(f"Cost: ${b.spent:.4f}")
```

#### Budget Enforcement

```python
with budget(max_usd=1.00) as b:
    run_agent()
```

#### Early Warning

```python
with budget(max_usd=5.00, warn_at=0.8) as b:
    run_agent()  # Warns at $4.00
```

#### Custom Warning Callback

```python
def my_handler(spent: float, limit: float):
    print(f"Alert: ${spent:.2f} / ${limit:.2f}")

with budget(max_usd=10.00, warn_at=0.8, on_exceed=my_handler):
    run_agent()
```

#### Model Fallback

```python
with budget(max_usd=1.00, fallback="gpt-4o-mini") as b:
    run_agent()
```

#### Persistent Budget

```python
session = budget(max_usd=10.00, persistent=True)

with session:
    process_batch_1()

with session:
    process_batch_2()  # Accumulates
```

#### Custom Pricing

```python
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.002, "output": 0.006}
):
    run_agent()
```

---

## `Budget` Class

The budget context manager object.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `spent` | `float` | Total USD spent in this budget context. |
| `remaining` | `float \| None` | Remaining USD budget, or `None` if track-only mode. |
| `limit` | `float \| None` | The configured `max_usd`, or `None` if track-only. |
| `model_switched` | `bool` | `True` if fallback was activated. |
| `switched_at_usd` | `float \| None` | USD spent when fallback occurred, or `None`. |
| `fallback_spent` | `float` | USD spent on the fallback model. |

### Methods

#### `reset()`

Reset spend tracking to zero. Only works when budget is not active.

```python
session = budget(max_usd=10.00, persistent=True)

with session:
    process()

session.reset()  # Back to $0

with session:
    process_again()
```

**Raises:** `RuntimeError` if called inside an active `with` block.

#### `summary()`

Return formatted spend summary as a string.

```python
with budget(max_usd=5.00) as b:
    run_agent()

print(b.summary())
```

**Returns:** Multi-line string with formatted table of calls, costs, and totals.

#### `summary_data()`

Return structured spend data as a dict.

```python
with budget() as b:
    run_agent()

data = b.summary_data()
print(data["total_spent"])
print(data["total_calls"])
print(data["by_model"])
```

**Returns:** Dictionary with keys:
- `total_spent`: Total USD
- `limit`: Budget limit
- `hard_cap`: Configured hard cap
- `effective_hard_cap`: Actual hard cap used
- `model_switched`: Boolean
- `switched_at_usd`: Switch point
- `fallback_model`: Fallback model name
- `fallback_spent`: Cost on fallback
- `total_calls`: Number of API calls
- `calls`: List of all call records
- `by_model`: Aggregated stats per model

---

## `@with_budget`

Decorator that wraps functions with a budget context.

### Signature

```python
def with_budget(
    max_usd: float | None = None,
    warn_at: float | None = None,
    on_exceed: Callable[[float, float], None] | None = None,
    price_per_1k_tokens: dict[str, float] | None = None,
    fallback: str | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
)
```

### Parameters

Same as `budget()`, except no `persistent` or `hard_cap` (decorator creates fresh budget per call).

### Examples

#### Basic Decorator

```python
from shekel import with_budget

@with_budget(max_usd=0.50)
def generate_summary(text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize: {text}"}],
    )
    return response.choices[0].message.content
```

#### Async Decorator

```python
@with_budget(max_usd=0.50)
async def async_generate(prompt: str) -> str:
    response = await client.chat.completions.create(...)
    return response.choices[0].message.content
```

#### With All Parameters

```python
@with_budget(
    max_usd=2.00,
    warn_at=0.8,
    fallback="gpt-4o-mini",
    on_exceed=my_warning_handler
)
def process_request(data: dict) -> str:
    ...
```

---

## `BudgetExceededError`

Exception raised when budget limit is exceeded.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `spent` | `float` | Total USD spent when limit was hit. |
| `limit` | `float` | The configured `max_usd`. |
| `model` | `str` | Model that triggered the error. |
| `tokens` | `dict[str, int]` | Token counts: `{"input": N, "output": N}`. |

### Example

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.50):
        expensive_operation()
except BudgetExceededError as e:
    print(f"Spent: ${e.spent:.4f}")
    print(f"Limit: ${e.limit:.2f}")
    print(f"Model: {e.model}")
    print(f"Tokens: {e.tokens['input']} in, {e.tokens['output']} out")
```

---

## Type Signatures

For type checking with mypy, pyright, etc:

```python
from shekel import budget, with_budget, BudgetExceededError
from typing import Callable

# Budget context manager
b: budget = budget(max_usd=1.00)

# Decorator
@with_budget(max_usd=0.50)
def my_func() -> str:
    ...

# Callbacks
def warn_callback(spent: float, limit: float) -> None:
    ...

def fallback_callback(spent: float, limit: float, fallback: str) -> None:
    ...
```

---

## Next Steps

- [Basic Usage](usage/basic-usage.md) - Learn the fundamentals
- [Budget Enforcement](usage/budget-enforcement.md) - Hard caps and warnings
- [Fallback Models](usage/fallback-models.md) - Automatic model switching
