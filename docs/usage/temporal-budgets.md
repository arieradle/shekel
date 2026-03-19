# Temporal Budgets

**Rolling-window LLM spend limits — enforce `$5/hr`, `$10/30min`, or any time-based cap.**

Temporal budgets protect against runaway costs in long-running services, multi-tenant APIs, or any scenario where you need to enforce a spend limit *per time period* rather than per-session.

---

## Quick Start

```python
from shekel import budget, BudgetExceededError

# Create a $5/hour rolling-window budget
api_budget = budget("$5/hr", name="api-tier")

async with api_budget:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
```

When the window limit is hit:

```python
try:
    async with api_budget:
        response = await client.chat(...)
except BudgetExceededError as e:
    print(f"Window exceeded — retry in {e.retry_after:.0f}s")
    print(f"Spent in window: ${e.window_spent:.4f}")
```

---

## Creating Temporal Budgets

### String DSL (recommended)

```python
budget("$5/hr",    name="api-tier")    # $5 per hour
budget("$10/30min", name="burst")      # $10 per 30 minutes
budget("$1/60s",   name="realtime")    # $1 per minute
budget("$5 per 1hr", name="api")       # same as $5/hr
budget("$2.50/hr", name="lite")        # decimals work
```

Supported units: `s`, `sec`, `min`, `hr`, `h`.
Calendar units (`day`, `week`, `month`) are intentionally **not supported** — rolling windows only.

### Keyword form

```python
from shekel import budget

tb = budget(max_usd=5.0, window_seconds=3600, name="api-tier")
```

### Direct instantiation

```python
from shekel._temporal import TemporalBudget

tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="api-tier")
```

!!! note
    `name=` is required for all `TemporalBudget` instances. It uniquely identifies the window state and is used in metrics labels.

---

## Rolling Window Semantics

- Each window starts the first time a cost is recorded
- The window resets lazily on the next `__enter__` after the window duration has elapsed — **no background threads**
- Spend accumulates in the backend until the window expires
- The `TemporalBudget` object is **persistent** — reuse the same instance across multiple `async with` calls:

```python
api_budget = budget("$5/hr", name="api-tier")

# Request 1 — $0.10 spent
async with api_budget:
    await call_llm()

# Request 2 — $0.05 more (window still open, $0.15 total)
async with api_budget:
    await call_llm()

# ... eventually the window resets and spend restarts from $0
```

---

## Handling `BudgetExceededError`

`TemporalBudget` enriches `BudgetExceededError` with two extra fields:

| Field | Type | Description |
|---|---|---|
| `retry_after` | `float \| None` | Seconds until current window expires and spend resets |
| `window_spent` | `float \| None` | Total spend accumulated in the current window |

```python
try:
    async with api_budget:
        response = await client.chat(...)
except BudgetExceededError as e:
    if e.retry_after is not None:
        # Temporal budget — tell caller when to retry
        headers = {"Retry-After": str(int(e.retry_after))}
        return Response(status=429, headers=headers)
    else:
        # Regular budget exhausted
        return Response(status=402, body="Budget exhausted")
```

---

## Nesting Rules

Regular `Budget` and `TemporalBudget` can be nested freely — **except** temporal-inside-temporal:

```python
# ✅ Regular inside temporal — OK
outer = budget("$10/hr", name="outer")
with outer:
    with budget(max_usd=2.0, name="step"):
        call_llm()

# ✅ Temporal inside regular — OK
with budget(max_usd=50.0, name="session"):
    tb = budget("$5/hr", name="api")
    with tb:
        call_llm()

# ❌ Temporal inside temporal — raises ValueError
outer = budget("$10/hr", name="outer")
inner = budget("$5/hr", name="inner")
with outer:
    with inner:  # ValueError: temporal-in-temporal not supported
        call_llm()
```

The nesting guard walks up to 5 ancestor levels, so deeply nested `TemporalBudget` inside another `TemporalBudget` is always caught.

---

## Custom Backends

The default `InMemoryBackend` is simple and **not thread-safe**. For production multi-threaded or distributed use, implement `TemporalBudgetBackend`:

```python
from shekel._temporal import TemporalBudgetBackend, TemporalBudget
import threading

class ThreadSafeBackend:
    """Thread-safe in-process backend using a lock."""

    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float | None]] = {}
        self._lock = threading.Lock()

    def get_state(self, budget_name: str) -> tuple[float, float | None]:
        with self._lock:
            return self._state.get(budget_name, (0.0, None))

    def check_and_add(
        self, budget_name: str, amount: float, max_usd: float, window_seconds: float
    ) -> bool:
        import time
        with self._lock:
            spent, window_start = self._state.get(budget_name, (0.0, None))
            now = time.monotonic()
            if window_start is not None and (now - window_start) >= window_seconds:
                spent, window_start = 0.0, None
            if spent + amount > max_usd:
                return False
            self._state[budget_name] = (
                spent + amount,
                window_start if window_start is not None else now,
            )
            return True

    def reset(self, budget_name: str) -> None:
        with self._lock:
            self._state.pop(budget_name, None)

# Use your backend
tb = TemporalBudget(
    max_usd=5.0,
    window_seconds=3600,
    name="api-tier",
    backend=ThreadSafeBackend(),
)
```

The `TemporalBudgetBackend` is a `@runtime_checkable` `Protocol` — any object with `get_state`, `check_and_add`, and `reset` methods qualifies.

!!! tip "Redis backend — available now"
    `RedisBackend` and `AsyncRedisBackend` ship with shekel v1.0.2 and implement this protocol with atomic Lua-script enforcement (one round-trip), a circuit breaker, and fail-closed/open modes. See [Distributed Budgets](distributed-budgets.md) or `from shekel.backends.redis import RedisBackend`.

---

## OTel Integration

If `ShekelMeter` is registered, temporal budgets contribute to:

- **`shekel.budget.window_resets_total`** — counter incremented each time a window resets, tagged with `budget_name`

```python
from shekel.otel import ShekelMeter

meter = ShekelMeter()

tb = budget("$5/hr", name="api-tier")
async with tb:
    await call_llm()
```

The `on_window_reset` adapter event is also available for custom `ObservabilityAdapter` implementations:

```python
from shekel.integrations.base import ObservabilityAdapter

class MyAdapter(ObservabilityAdapter):
    def on_window_reset(self, data: dict) -> None:
        print(
            f"Window reset for {data['budget_name']}: "
            f"previous spend ${data['previous_spent']:.4f}, "
            f"window was {data['window_seconds']}s"
        )
```

---

## API Reference

### `TemporalBudget`

| Parameter | Type | Description |
|---|---|---|
| `max_usd` | `float` | Spend cap per window |
| `window_seconds` | `float` | Rolling window duration in seconds |
| `name` | `str` | **Required.** Unique name for this budget |
| `backend` | `TemporalBudgetBackend \| None` | Custom backend (default: `InMemoryBackend`) |

Inherits all parameters from `Budget` (`warn_at`, `on_warn`, `fallback`, etc.).

### `TemporalBudgetBackend` Protocol

| Method | Signature | Description |
|---|---|---|
| `get_state` | `(budget_name) → (spent, window_start)` | Return current window state |
| `check_and_add` | `(budget_name, amount, max_usd, window_seconds) → bool` | Atomically check and record spend |
| `reset` | `(budget_name) → None` | Clear window state |

### `BudgetExceededError` (temporal fields)

| Field | Type | Description |
|---|---|---|
| `retry_after` | `float \| None` | Seconds until window resets (`None` for regular `Budget`) |
| `window_spent` | `float \| None` | Spend in current window (`None` for regular `Budget`) |
