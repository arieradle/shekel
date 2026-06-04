---
title: Per-Tenant Budgets – Enforce Per-User LLM Spend Limits
description: "Enforce isolated per-user or per-tenant LLM spend limits in SaaS apps using shekel and Redis. Each tenant gets an independent cap — same backend, zero per-tenant config."
tags:
  - per-tenant
  - multi-tenant
  - saas
  - redis
  - budget-enforcement
---

# Per-Tenant Budgets

**Give every user their own isolated LLM spend cap — same Redis backend, zero per-tenant infrastructure.**

```python
with budget(max_usd=0.10, tenant_id=user.id, name="api", backend=RedisBackend()) as b:
    run_agent()
# Each user gets an independent $0.10 cap. No shared state. No cross-contamination.
```

When `tenant_id` is set, shekel namespaces all Redis state under `shekel:tb:{name}:{tenant_id}`. Two tenants with the same `name` never share counters.

---

## Installation

```bash
pip install shekel[redis]
```

---

## Quick Start

```python
from shekel import budget
from shekel.backends.redis import RedisBackend

backend = RedisBackend()  # reads REDIS_URL from env

# Enforce a $0.10 monthly cap for user "user-42"
with budget(max_usd=0.10, tenant_id="user-42", name="api", backend=backend) as b:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )
```

!!! note "Required parameters"
    `tenant_id` requires both `name` and `backend`. Omitting either raises `ValueError`.

---

## FastAPI SaaS Example

A production-ready endpoint that enforces per-user spend, returns HTTP 429 on exhaustion, and lets admins inspect quotas:

```python
from fastapi import FastAPI, Depends, HTTPException, Request
from shekel import budget
from shekel.backends.redis import AsyncRedisBackend
from shekel.exceptions import BudgetExceededError

app = FastAPI()
backend = AsyncRedisBackend(url="redis://redis:6379/0")

MONTHLY_CAP_USD = 0.10  # $0.10 per user per 30 days

async def get_current_user(request: Request) -> str:
    return request.headers["X-User-ID"]  # your auth here

@app.post("/chat")
async def chat(prompt: str, user_id: str = Depends(get_current_user)):
    try:
        async with budget(
            max_usd=MONTHLY_CAP_USD,
            tenant_id=user_id,
            name="api",
            backend=backend,
            window_seconds=86400 * 30,  # 30-day rolling window (default)
        ) as b:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            return {
                "reply": response.choices[0].message.content,
                "spent": b.spent,
            }
    except BudgetExceededError as e:
        raise HTTPException(
            status_code=429,
            detail="Monthly spend limit reached.",
            headers={"Retry-After": str(int(e.retry_after or 0))},
        )
```

---

## Async Usage

`budget()` with `tenant_id` works identically in async contexts — just use `async with`:

```python
from shekel import budget
from shekel.backends.redis import AsyncRedisBackend

backend = AsyncRedisBackend()

async with budget(
    max_usd=0.10,
    tenant_id=user_id,
    name="api",
    backend=backend,
) as b:
    await call_llm()

print(f"Tenant {user_id} spent: ${b.spent:.4f}")
```

---

## Redis Key Scheme

Each tenant's state lives in its own Redis hash, completely isolated from other tenants:

| Key pattern | Example | Contains |
|---|---|---|
| `shekel:tb:{name}:{tenant_id}` | `shekel:tb:api:user-42` | `usd:spent`, `usd:max`, `usd:window_s`, `usd:start`, `spec_hash` |

Without `tenant_id`, the key is `shekel:tb:{name}` (shared across all callers). With `tenant_id`, an extra segment is appended so no two tenants ever touch the same hash.

---

## Quota Management

`RedisBackend` (and `AsyncRedisBackend`) expose five admin methods for managing tenant quotas programmatically.

### `get_tenant_spend(name, tenant_id) → float`

Return the current window spend for a tenant. Returns `0.0` if the tenant has never been seen.

```python
spent = backend.get_tenant_spend(name="api", tenant_id="user-42")
print(f"User 42 has spent ${spent:.4f} this window")
```

### `get_tenant_limit(name, tenant_id) → float | None`

Return the active spend limit for a tenant. Returns `None` if the tenant has no recorded limit.

```python
limit = backend.get_tenant_limit(name="api", tenant_id="user-42")
if limit is not None:
    print(f"User 42 limit: ${limit:.2f}")
```

### `set_tenant_limit(name, tenant_id, max_usd)`

Override the spend limit for a tenant without resetting their accumulated spend. Useful for upgrades (free → pro) or admin adjustments.

```python
# Upgrade user to a $1.00 monthly cap
backend.set_tenant_limit(name="api", tenant_id="user-42", max_usd=1.00)
```

After calling `set_tenant_limit`, subsequent `budget(max_usd=1.00, tenant_id="user-42", ...)` calls succeed. Passing the old limit raises `BudgetConfigMismatchError` — see [Limit-change flow](#limit-change-flow).

### `reset_tenant(name, tenant_id)`

Zero out a tenant's accumulated spend while preserving their limit. Use this at the start of a new billing period.

```python
backend.reset_tenant(name="api", tenant_id="user-42")
# spend → 0.0, limit unchanged
```

### `list_tenants(name) → list[str]`

Return all tenant IDs that have ever recorded spend for the given budget name.

```python
tenants = backend.list_tenants(name="api")
for tid in tenants:
    spent = backend.get_tenant_spend(name="api", tenant_id=tid)
    limit = backend.get_tenant_limit(name="api", tenant_id=tid)
    print(f"{tid}: ${spent:.4f} / ${limit:.2f}")
```

### Async equivalents

All five methods are available as coroutines on `AsyncRedisBackend`:

```python
spent = await backend.get_tenant_spend(name="api", tenant_id="user-42")
limit = await backend.get_tenant_limit(name="api", tenant_id="user-42")
await backend.set_tenant_limit(name="api", tenant_id="user-42", max_usd=1.00)
await backend.reset_tenant(name="api", tenant_id="user-42")
tenants = await backend.list_tenants(name="api")
```

---

## `shekel tenants` CLI

The `shekel tenants` command inspects and manages tenant quotas from the command line — no code changes needed.

### List tenants

```bash
shekel tenants list --name api
```

```
Tenant           Spent      Limit      % Used
user-1           $0.0821    $0.1000    82.1%
user-2           $0.0034    $0.1000     3.4%
org:user-3       $0.0990    $0.1000    99.0%
```

JSON output:

```bash
shekel tenants list --name api --json
```

```json
[
  {"tenant_id": "user-1", "spent": 0.0821, "limit": 0.1},
  {"tenant_id": "user-2", "spent": 0.0034, "limit": 0.1},
  {"tenant_id": "org:user-3", "spent": 0.0990, "limit": 0.1}
]
```

### Set a limit

```bash
shekel tenants set-limit --name api --tenant user-1 --max-usd 0.50
```

### Reset spend

```bash
shekel tenants reset --name api --tenant user-1
```

### Flag reference

| Flag | Description |
|---|---|
| `--name` | Budget name (required for all subcommands) |
| `--tenant` | Tenant ID (required for `set-limit` and `reset`) |
| `--max-usd` | New spend limit in USD (required for `set-limit`) |
| `--redis-url` | Redis URL (default: `$REDIS_URL`) |
| `--json` | Output as JSON instead of a table |

---

## Limit-Change Flow

When the tenant limit changes (e.g. a user upgrades), shekel detects the mismatch via a stored `spec_hash` and raises `BudgetConfigMismatchError` if you call `budget()` with the old limit.

**Correct flow:**

```python
# 1. Admin raises the limit in Redis
backend.set_tenant_limit(name="api", tenant_id="user-1", max_usd=0.50)

# 2. Next request uses the new limit — no mismatch
with budget(max_usd=0.50, tenant_id="user-1", name="api", backend=backend):
    call_llm()
```

**Incorrect — still passing old limit:**

```python
backend.set_tenant_limit(name="api", tenant_id="user-1", max_usd=0.50)

# Passing old limit 0.10 → BudgetConfigMismatchError
with budget(max_usd=0.10, tenant_id="user-1", name="api", backend=backend):
    call_llm()
```

The mismatch check is **per-tenant** — changing user-1's limit has no effect on user-2.

---

## Error Reference

| Exception | When raised |
|---|---|
| `ValueError` | `tenant_id=""` (empty string), or `tenant_id` set without `backend`, or `tenant_id` set without `name` |
| `BudgetExceededError` | Tenant's spend cap is reached during a call |
| `BudgetConfigMismatchError` | Same `(name, tenant_id)` called with a different `max_usd` than what's stored in Redis |

```python
from shekel.exceptions import BudgetExceededError, BudgetConfigMismatchError

try:
    with budget(max_usd=0.10, tenant_id=user_id, name="api", backend=backend):
        call_llm()
except BudgetExceededError as e:
    # Tenant is over their cap — retry_after tells them when the window resets
    print(f"Limit reached. Retry in {e.retry_after:.0f}s")
except BudgetConfigMismatchError:
    # Limit was changed in Redis but code still uses the old value
    print("Budget config mismatch — check set_tenant_limit()")
```

---

## `tenant_id` on the Budget Object

The `tenant_id` is accessible on the budget instance after the context exits:

```python
with budget(max_usd=0.10, tenant_id="user-42", name="api", backend=backend) as b:
    call_llm()

print(b.tenant_id)   # "user-42"
print(b.spent)       # e.g. 0.0023
```

`b.summary()` also surfaces the tenant:

```
Budget: api
Tenant: user-42
Spent:  $0.0023 / $0.1000 (2.3%)
Calls:  1
```

---

## Next Steps

- **[Distributed Budgets](distributed-budgets.md)** — shared caps across multiple workers using Redis
- **[Temporal Budgets](temporal-budgets.md)** — rolling-window rate limits
- **[API Reference](../api-reference.md)** — complete parameter and method reference
