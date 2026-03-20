---
title: Distributed Budgets – Enforce LLM Spend Limits Across Processes with Redis
description: "Enforce shared LLM API spend limits atomically across multiple processes, workers, or Kubernetes pods. Atomic Lua-script enforcement, circuit breaker, fail-closed by default."
tags:
  - distributed
  - redis
  - rate-limiting
  - budget-enforcement
---

# Distributed Budgets

**Enforce shared LLM spend limits across multiple processes, workers, or pods using Redis.**

The default `InMemoryBackend` stores budget state in-process — it works perfectly for single-process applications but cannot coordinate spend across multiple workers. `RedisBackend` and `AsyncRedisBackend` solve this by storing rolling-window state atomically in Redis.

---

## Installation

```bash
pip install shekel[redis]
```

---

## Quick Start

### Synchronous (threading, Flask, Django, etc.)

```python
from shekel import budget
from shekel.backends.redis import RedisBackend

backend = RedisBackend()  # reads REDIS_URL from env

api_budget = budget("$5/hr", name="api-tier", backend=backend)

with api_budget:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
```

### Asynchronous (FastAPI, LangGraph, asyncio)

```python
from shekel import budget
from shekel.backends.redis import AsyncRedisBackend

backend = AsyncRedisBackend()  # reads REDIS_URL from env

api_budget = budget("$5/hr", name="api-tier", backend=backend)

async with api_budget:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
```

!!! note "Use the right backend for your context"
    Use `RedisBackend` in synchronous code (threading-based servers) and `AsyncRedisBackend` in async code. Mixing them is not supported.

---

## Configuration

### Redis URL

```python
# Explicit URL
backend = RedisBackend(url="redis://user:pass@host:6379/0")

# From environment variable (default)
# Set REDIS_URL=redis://... in your environment
backend = RedisBackend()

# TLS (e.g. Redis Cloud, AWS Elasticache with TLS)
backend = RedisBackend(url="rediss://...", tls=True)
```

### Fail-Closed vs Fail-Open

Controls what happens when Redis is unreachable:

```python
# Fail-closed (default) — raise BudgetExceededError when Redis is down
backend = RedisBackend(on_unavailable="closed")

# Fail-open — allow calls through when Redis is down
backend = RedisBackend(on_unavailable="open")
```

!!! danger "Fail-Open Risk"
    `on_unavailable="open"` allows all LLM calls through when Redis is unreachable. Use this only if availability is more important than cost protection.

### Circuit Breaker

The circuit breaker stops calling Redis after repeated failures, reducing latency during outages:

```python
backend = RedisBackend(
    circuit_breaker_threshold=3,   # open circuit after 3 consecutive errors (default)
    circuit_breaker_cooldown=10.0, # wait 10s before retrying (default)
)
```

When the circuit is open, the backend immediately applies the `on_unavailable` policy (fail-closed or fail-open) without attempting a Redis call.

---

## How It Works

All state is stored in a single Redis hash per budget name:

```
shekel:tb:{name}
  spec_hash        → "<hex>"       (config fingerprint for mismatch detection)
  usd:max          → "5.0"         (limit)
  usd:window_s     → "3600"        (window duration)
  usd:start        → "1234567890"  (window start, ms)
  usd:spent        → "2.34"        (current spend)
```

Each call executes a **single Lua script** on Redis that:

1. Checks if the window has expired (and resets if so)
2. Checks all counters atomically against their limits
3. Commits all counters atomically (or rejects all)

This ensures **one round-trip** and **no race conditions** between concurrent workers.

---

## Inspecting and Resetting State

### Read current window spend

```python
backend = RedisBackend()
state = backend.get_state("api-tier")
# {'usd': 2.34}
print(f"Current window spend: ${state.get('usd', 0):.4f}")
```

### Reset a budget

Clears all window state — the next call starts a fresh window:

```python
backend.reset("api-tier")
```

Async variant:

```python
await backend.reset("api-tier")
```

### Close the connection

```python
backend.close()        # sync
await backend.close()  # async
```

---

## Config Mismatch Detection

If two workers start the same budget name with different limits or window sizes, shekel raises `BudgetConfigMismatchError`:

```python
from shekel.exceptions import BudgetConfigMismatchError

try:
    async with api_budget:
        await call_llm()
except BudgetConfigMismatchError as e:
    print(f"Config mismatch: {e}")
    # Fix: ensure all workers use the same budget parameters
    # Or reset: await backend.reset("api-tier")
```

!!! warning "Config Mismatches in Rolling Deployments"
    During rolling deployments where the new version changes budget parameters, you may see `BudgetConfigMismatchError`. To handle this, call `backend.reset(budget_name)` after deploying or use a versioned budget name (e.g. `"api-tier-v2"`).

---

## Multi-Tenant API Example

Enforce per-tenant spend limits across a horizontally scaled API:

```python
from fastapi import FastAPI, HTTPException
from shekel import budget, BudgetExceededError
from shekel.backends.redis import AsyncRedisBackend

app = FastAPI()
redis_backend = AsyncRedisBackend(url="redis://redis:6379/0")

TENANT_LIMITS = {
    "free": "$1/hr",
    "pro": "$10/hr",
    "enterprise": "$100/hr",
}

@app.post("/chat/{tenant_id}")
async def chat(tenant_id: str, prompt: str):
    tier = get_tenant_tier(tenant_id)  # your lookup
    limit = TENANT_LIMITS.get(tier, "$1/hr")

    tenant_budget = budget(limit, name=f"tenant-{tenant_id}", backend=redis_backend)

    try:
        async with tenant_budget:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            return {"reply": response.choices[0].message.content}
    except BudgetExceededError as e:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {e.retry_after:.0f}s.",
            headers={"Retry-After": str(int(e.retry_after or 0))},
        )
```

---

## Docker Compose Setup

```yaml
services:
  app:
    build: .
    environment:
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

See [Docker & Containers](../docker.md) for a full production setup.

---

## Production Checklist

- [ ] Set `REDIS_URL` to a persistent Redis instance (not ephemeral)
- [ ] Enable Redis persistence (`appendonly yes`) to survive restarts
- [ ] Use TLS (`rediss://` URL + `tls=True`) for connections over untrusted networks
- [ ] Set `on_unavailable` based on your priority (availability vs. cost safety)
- [ ] Monitor Redis memory — shekel keys auto-expire at `2x window duration`
- [ ] Use versioned budget names during rolling deployments to avoid `BudgetConfigMismatchError`

---

## API Reference

### `RedisBackend` / `AsyncRedisBackend`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str \| None` | `$REDIS_URL` or `redis://127.0.0.1:6379/0` | Redis connection URL |
| `tls` | `bool` | `False` | Force TLS on the connection |
| `on_unavailable` | `"closed" \| "open"` | `"closed"` | Policy when Redis is unreachable |
| `circuit_breaker_threshold` | `int` | `3` | Consecutive errors before opening circuit |
| `circuit_breaker_cooldown` | `float` | `10.0` | Seconds before retrying after circuit opens |

### Methods

| Method | Description |
|---|---|
| `get_state(budget_name)` | Returns `{counter: spent}` for the current window |
| `reset(budget_name)` | Clears all window state for the budget |
| `close()` | Closes the Redis connection |

---

## Next Steps

- **[Temporal Budgets](temporal-budgets.md)** - Rolling-window budget fundamentals
- **[Docker & Containers](../docker.md)** - Full containerized production setup
- **[API Reference](../api-reference.md)** - Complete parameter reference
