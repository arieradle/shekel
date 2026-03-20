---
title: Spend Velocity – LLM Burn-Rate Circuit Breaker
description: "Cap how fast your AI agent spends money, not just how much. Stop a bursty agent that burns $40 in two minutes before your total USD cap fires. SpendVelocityExceededError."
tags:
  - agent-safety
  - budget-enforcement
  - circuit-breaker
---

# Spend Velocity

**Cap how fast you burn money, not just how much. One parameter.**

A `max_usd=50.00` cap won't save you if your agent blows $40 in the first two minutes. Spend velocity adds a burn-rate circuit breaker alongside the total cap.

---

## The problem

Total spend caps and velocity caps protect against different failure modes:

| Failure mode | Protected by |
|---|---|
| Agent runs for 8 hours, accumulates $48 | `max_usd` cap |
| Agent bursts $40 in 2 minutes, then idles | Velocity cap |
| Agent loops on a cheap tool, slow drain | Loop guard |

A misconfigured agent with a fast LLM can spend at $10/min or faster. By the time a `max_usd=50` cap fires, $50 is already gone. A velocity cap of `"$1/min"` stops it after the first dollar.

---

## Quick Start

```python
from shekel import budget, SpendVelocityExceededError

try:
    with budget(max_velocity="$0.50/min") as b:
        run_my_agent()
except SpendVelocityExceededError as e:
    print(f"Burn rate too high: ${e.velocity_per_min:.4f}/min (limit: ${e.limit_per_min:.4f}/min)")
```

No changes to your agent code. Works with all auto-patched providers: OpenAI, Anthropic, Gemini, LiteLLM.

---

## Spec format

The velocity spec uses the same string DSL as temporal budgets:

```
$<amount>/<count><unit>
```

| Example | Meaning |
|---|---|
| `"$0.50/min"` | $0.50 per minute |
| `"$5/hr"` | $5 per hour |
| `"$0.01/sec"` | $0.01 per second |
| `"$100/day"` | $100 per day |

All specs are internally normalized to **USD per minute** for comparison and error reporting. `$5/hr` becomes `$0.0833/min`; `$0.01/sec` becomes `$0.60/min`.

Supported time units: `sec`, `s`, `min`, `m`, `hr`, `h`, `hour`, `day`, `d`.

---

## Velocity-only guard (no `max_usd`)

You can use velocity without a total cap — useful when you want to throttle spend rate but don't have a hard total budget:

```python
# Allow at most $1 per minute — no total ceiling
with budget(max_velocity="$1/min") as b:
    run_streaming_agent()

print(f"Spent: ${b.spent:.4f}")
```

This is useful for API tiers, rate-limiting proxies, or services where total spend is metered externally but you want a local burst guard.

---

## Compound guardrails

Combine `max_usd` and `max_velocity` to protect against both slow drain and fast burn:

```python
try:
    with budget(
        max_usd=50.00,            # never spend more than $50 total
        max_velocity="$1/min",   # never burn faster than $1/min
    ) as b:
        run_agent()
except SpendVelocityExceededError as e:
    print(f"Velocity exceeded: ${e.velocity_per_min:.4f}/min")
except BudgetExceededError as e:
    print(f"Total cap hit: ${e.spent:.4f}")
```

Both guards are checked on every LLM call. Whichever fires first wins.

---

## Velocity warning

Add `warn_velocity` to get a soft warning before the hard stop. It must be less than `max_velocity`:

```python
def on_velocity_warn(current_rate, limit_rate):
    print(f"Velocity warning: ${current_rate:.4f}/min (limit: ${limit_rate:.4f}/min)")

with budget(
    max_velocity="$1/min",
    warn_velocity="$0.75/min",    # warn at 75% of the velocity limit
    on_warn=on_velocity_warn,
) as b:
    run_agent()
```

The `warn_velocity` callback fires once per budget context when the threshold is crossed. The hard stop at `max_velocity` fires independently when the limit is actually exceeded.

---

## `warn_only` mode

Use `warn_only=True` in staging to observe velocity patterns without blocking:

```python
with budget(max_velocity="$0.50/min", warn_only=True) as b:
    run_agent()
# Never raises — logs a warning when velocity exceeds $0.50/min

print(f"Peak velocity observed: see logs")
```

Use this to calibrate `max_velocity` before enabling enforcement in production.

---

## Reading the exception

`SpendVelocityExceededError` carries the measured velocity and the configured limit:

```python
from shekel import budget, SpendVelocityExceededError

try:
    with budget(max_velocity="$0.50/min") as b:
        run_agent()
except SpendVelocityExceededError as e:
    print(f"Velocity:       ${e.velocity_per_min:.4f}/min")
    print(f"Limit:          ${e.limit_per_min:.4f}/min")
    print(f"Window (s):     {e.window_seconds:.1f}")
    print(f"USD spent:      ${e.usd_spent:.4f}")
    print(f"Elapsed (s):    {e.elapsed_seconds:.1f}")
```

All velocity values are normalized to **per minute** regardless of the spec unit you used. `e.velocity_per_min` is always in USD/min.

| Attribute | Type | Description |
|-----------|------|-------------|
| `velocity_per_min` | `float` | Measured spend velocity in USD/min at the time of blocking |
| `limit_per_min` | `float` | The configured velocity limit in USD/min |
| `window_seconds` | `float` | Rolling window over which velocity was measured |
| `usd_spent` | `float` | Total USD spent when blocked |
| `elapsed_seconds` | `float` | Seconds elapsed since the budget context opened |

`SpendVelocityExceededError` subclasses `BudgetExceededError`, so existing `except BudgetExceededError` blocks catch it automatically.

---

## Nested budgets

Velocity is measured independently per budget context. A child context has its own velocity clock:

```python
with budget(max_usd=20.00, max_velocity="$2/min", name="outer") as outer:
    with budget(max_usd=5.00, max_velocity="$0.50/min", name="inner") as inner:
        run_fast_stage()  # inner velocity cap fires if inner burns > $0.50/min
    # inner spend rolls up to outer automatically
```

The inner's velocity cap is tighter — it fires if the inner stage alone burns faster than `$0.50/min`, regardless of the outer budget's velocity. Both are enforced independently.

---

## What it doesn't cover

**TemporalBudget interaction** — Spend velocity measures the rate within a single `budget()` context (from `__enter__` to `__exit__`). It does not interact with `TemporalBudget` rolling-window counters. For long-running services where you want per-hour or per-day rate limits, use `budget("$5/hr", name="api")` instead.

**Distributed velocity** — `max_velocity` is local to a single process. If you have multiple processes spending concurrently, their individual velocities are independent. For distributed velocity enforcement, use `RedisBackend` with a `TemporalBudget`.

---

## Next Steps

- [Loop Guard](loop-guard.md) — detect repeated tool calls
- [Temporal Budgets](temporal-budgets.md) — rolling-window rate limits for multi-process deployments
- [API Reference](../api-reference.md)
