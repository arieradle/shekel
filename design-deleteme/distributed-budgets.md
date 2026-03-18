# Design Decision: Distributed Budgets

**Date:** 2026-03-17  
**Status:** Draft  
**Branch:** feat/distributed-budgets

---

## Context

Shekel currently enforces budgets in-process via `InMemoryBackend`. This does not survive process restarts and cannot be shared across pods or services. Users need budgets that:

- Persist across process restarts
- Are enforced consistently across multiple pods/services
- Have their own lifecycle independent of any single process

---

## Decision

Implement a **Redis-backed `TemporalBudgetBackend`** as the first distributed backend. The existing `TemporalBudgetBackend` protocol is upgraded to be **generic and counter-based** so future backends (gossip, Postgres, etc.) can plug in without protocol changes.

---

## API

### Two forms, never mixed. Mixing raises `ValueError`.

```python
# SPEC STRING — richer form; each cap fully self-described with its own window
budget("$5/hr", name="api")
budget("100 calls/hr", name="api")
budget("$5/hr + 100 calls/day", name="api")        # per-cap windows, valid
budget("$5/hr + 100 calls/hr + 20 tools/hr", name="api")

# KWARGS — convenience shorthand; one window_seconds applies to all caps
budget(name="api", max_usd=5.0, window_seconds=3600)
budget(name="api", max_usd=5.0, max_llm_calls=100, window_seconds=3600)
# Need different windows per cap? → use spec string

# MIXING → ValueError immediately
budget("$5/hr", name="api", max_llm_calls=100)  # ← raises ValueError
```

| Need | Form |
|------|------|
| One cap | either form |
| Multi-cap, same window | either form |
| Multi-cap, different windows | spec string only |

### Spec string identifiers

| Spec string token | kwargs equivalent | Meaning |
|-------------------|-------------------|---------|
| `$N` or `N usd` | `max_usd` | USD spend |
| `N calls` | `max_llm_calls` | LLM calls |
| `N tools` | `max_tool_calls` | Tool calls |
| `N tokens` | `max_tokens` | Tokens (future) |

Window units: `s`, `sec`, `min`, `hr`, `h`. (`day`/`week`/`month` out of scope v1.)

---

## Backend Protocol (updated)

Generic named-counter protocol. Backend is unaware of "USD" or "calls" — it manages named counters with limits.

```python
class TemporalBudgetBackend(Protocol):
    def check_and_add(
        self,
        budget_name: str,
        amounts: dict[str, float],          # {"usd": 0.03, "llm_calls": 1}
        limits: dict[str, float | None],    # {"usd": 5.0, "llm_calls": 100, "tool_calls": None}
        windows: dict[str, float],          # {"usd": 3600, "llm_calls": 86400}
    ) -> tuple[bool, str | None]:           # (allowed, first_exceeded_counter or None)
        ...

    def get_state(self, budget_name: str) -> dict[str, float]:
        # {"usd": 2.34, "llm_calls": 45}
        ...

    def reset(self, budget_name: str) -> None: ...
```

- `None` limit = no cap; counter is still tracked for observability.
- Returns `(False, "usd")` or `(False, "llm_calls")` so caller raises the right exception.
- **Atomic all-or-nothing:** if any counter would exceed, none are incremented.
- **Future caps:** just new keys in `amounts`/`limits`/`windows` dicts — zero protocol changes.

---

## Redis Backend

### Connection

```python
from shekel.backends.redis import RedisBackend, AsyncRedisBackend

# Auto-discover from env (REDIS_URL):
backend = RedisBackend()

# Explicit:
backend = RedisBackend(url="redis://user:pass@host:6379/0", tls=True)

# Async contexts (FastAPI, LangGraph):
backend = AsyncRedisBackend()

# Use:
with budget("$5/hr", name="api", backend=backend):
    run_agent()
```

- **Lazy connect** on first `check_and_add` call.
- **Connection pool** — not one connection per call.
- `close()` / context manager for explicit lifecycle; also safe without — pool auto-closes on GC.

### Key layout

```
shekel:tb:{name}
  spec_hash          → "abc123"          (hash of {counter: (limit, window_s)}; mismatch detection)
  usd:max            → "5.0"
  usd:window_s       → "3600"
  usd:window_start   → "1710000000000"   (Redis TIME in ms)
  usd:spent          → "2.34"
  calls:max          → "100"
  calls:window_s     → "86400"
  calls:window_start → "1710000000000"
  calls:spent        → "45"
  tools:max          → ""                (empty = no cap, still tracked)
  tools:window_s     → "3600"
  tools:window_start → "1710000000000"
  tools:spent        → "3"
```

Per-cap `window_start` and `window_s` → counters reset independently. One Redis hash per budget name.

### Lua semantics (per call)

```
1. For each counter in amounts:
   a. Read counter:window_start, counter:window_s from hash
   b. Call redis.call('TIME') → now_ms
   c. If now_ms - window_start >= window_s * 1000: reset counter:spent = 0, counter:window_start = now_ms
   d. If counter:max != "" AND spent + amount > max: return (0, counter_name)
2. All counters passed: HINCRBYFLOAT each counter:spent; PEXPIRE key (TTL = max window_s * 2000); return (1, nil)
```

One round-trip. One atomic operation. All-or-nothing.

### Identity and mismatch detection

- First writer stores spec hash (`{counter: (limit, window_s)}` dict hashed) alongside the counters.
- Every subsequent attaching process computes spec hash locally and compares.
- Mismatch → `BudgetConfigMismatchError("Budget 'api' already registered with different limits/windows")`.
- `reset()` → `DEL` key (clears spec hash and all counters; next writer registers fresh).

### Failure behavior

| Failure | Default behavior | Config |
|---------|-----------------|--------|
| Redis unreachable / timeout | **Fail-closed** → raise `BudgetExceededError("Backend unavailable — failing closed")` | `on_unavailable="open"` to allow through |
| Redis error (OOM, READONLY) | Same as unreachable | Same |
| 3 consecutive errors | Circuit breaker → stop calling Redis for 10s cooldown | Configurable |
| Process restart | Spend state in Redis → **no data loss** | — |
| Redis node restart | Needs AOF/replication (HA Redis or managed) | Deployment concern |

Emits `on_backend_unavailable(budget_name, error)` observability event before raising or allowing.

### Multi-region

Use a globally replicated Redis-compatible store (e.g. **AWS MemoryDB multi-region**, ElastiCache Global Datastore). Shekel connects to a single endpoint (regional proxy to global primary). **Enforce on primary only** to avoid stale-replica over-spend. Cross-region write latency and RPO/RTO are deployment concerns, not Shekel concerns.

### TTL and cleanup

- Each counter's TTL = `counter_window_s * 2` ms — renewed on every write via `PEXPIRE`.
- If budget is abandoned, key auto-expires.
- `reset()` → `DEL` key entirely.

---

## Enforcement

- **Post-flight:** `check_and_add` fires after LLM call completes with actual cost. One call may overshoot just before enforcement — same semantics as `InMemoryBackend`, documented.
- **Raise on first exceeded counter.** Deterministic check order: `usd → llm_calls → tool_calls → custom`.
- Error carries counter name: `BudgetExceededError("Budget 'api' exceeded: calls (100/hr)")`.

---

## Observability

New event added to `ObservabilityAdapter` (default no-op):

```python
def on_backend_unavailable(self, budget_name: str, error: Exception) -> None: ...
```

All existing events (`on_window_reset`, `on_budget_exceeded`, `on_cost_update`, etc.) fire as normal.

---

## Testing with Redis

### Recommended for GitHub CI: service container (free, no hosted API)

**You do not need a paid or hosted Redis API for CI.** GitHub Actions can run a real Redis server next to the job using a **service container** — same Redis wire protocol as production, no external account.

```yaml
# .github/workflows/… (excerpt)
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5
    env:
      REDIS_URL: redis://127.0.0.1:6379/0
    steps:
      - uses: actions/checkout@v4
      # … install Python, pytest …
      - run: pytest tests/ -m redis  # or run integration tests when REDIS_URL is set
```

- **Cost:** Included in GitHub Actions minutes for public repos; private repos use your Actions quota. No Redis vendor bill.
- **Pull speed:** `redis:7-alpine` is a small image (~tens of MB); first pull on a runner is often ~10–30s, with layer cache helping on subsequent jobs. Startup after pull is sub-second. If image pull is a concern, alternatives are pinning `redis:7-alpine` for cache stability or installing `redis-server` via `apt` on the runner (no Docker pull for Redis).
- **Isolation:** Fresh Redis per job run; tests can `FLUSHDB` or use key prefixes without polluting shared state.
- **Docs:** [Creating Redis service containers](https://docs.github.com/en/actions/guides/creating-redis-service-containers) (GitHub).

**Local dev:** `docker run -p 6379:6379 redis:7-alpine` and set `REDIS_URL=redis://127.0.0.1:6379/0`.

### Unit tests without Docker: fakeredis / mocks

- **fakeredis:** In-process fake Redis; Lua support varies by version — validate Lua scripts against a real Redis in CI if fakeredis cannot run your script.
- **Mocks:** Stub `TemporalBudgetBackend` for pure unit tests of `TemporalBudget` wiring.

### Optional: hosted “free tier” Redis (REST or TCP)

Useful for **manual smoke tests**, **fork PRs** (if you avoid secrets in fork workflows), or when you cannot use service containers — **not required** for normal CI.

| Provider | Free tier (typical) | Protocol | CI notes |
|----------|---------------------|----------|----------|
| **Upstash** | Limited commands/month, small storage | **TCP Redis** (TLS URL) and **HTTP REST** | Standard `redis-py` works with their Redis URL + TLS. REST API is a different client — Shekel should target **TCP Redis** unless you add an HTTP adapter. |
| **Redis Cloud (Redis Inc.)** | Small free instance | TCP | Create DB, put URL in **GitHub Actions secret** `REDIS_URL`; optional job `if: secrets.REDIS_URL != ''`. |
| **ElastiCache / MemoryDB** | No perpetual free tier | TCP | Pay-as-you-go; use for staging, not default CI. |

**Caveats for hosted free tier in CI:**

- **Rate / command limits** — parallel test jobs can exhaust free quotas.
- **Secrets** — fork PRs from untrusted contributors often **do not** receive repository secrets; service containers avoid that.
- **Shared DB** — multiple CI runs against one free DB can flake; prefer **ephemeral CI Redis** (service container) for PR pipelines.

**Recommendation:** **Primary CI path = Redis service container + `REDIS_URL` to localhost.** Optional nightly or manual workflow with a secret `REDIS_URL` to a hosted free tier if you want to validate TLS / cloud-specific behavior.

### Integration test layout (suggested)

| Layer | Tool | When |
|-------|------|------|
| Protocol / Lua | Real Redis (Docker locally, service in CI) | Required before merge for Redis backend |
| Budget wiring | `InMemoryBackend` or fakeredis | Fast unit tests |
| Optional cloud smoke | Secret `REDIS_URL` to Upstash/Redis Cloud | Nightly or on-demand |

---

## Out of Scope (v1)

| Item | Notes |
|------|-------|
| Gossip / no-SPoF backend | Protocol is open; not implemented in v1 |
| K8s CRD for budget config | Possible future layer; not required for Redis v1 |
| Compound spec strings (`"$5/hr + 100 calls/day"` as compound) | Spec string supports per-cap windows via individual term parsing |
| `day` / `week` / `month` calendar windows | Not supported in v1 (existing limitation) |
| Per-cap window kwargs | Use spec string form instead |
| Multi-region split-quota | Handled by global Redis product choice |

---

## Implementation Plan

1. **Upgrade `TemporalBudgetBackend` protocol** — generic counters + per-cap windows.
2. **Upgrade `InMemoryBackend`** — match new protocol (also serves as test double).
3. **Upgrade `_parse_spec`** — support `"$5/hr + 100 calls/day"` multi-cap format.
4. **Upgrade `TemporalBudget`** — build `amounts`/`limits`/`windows` dicts from config; raise on form mixing.
5. **Implement `RedisBackend` + `AsyncRedisBackend`** — Lua script, lazy pool, spec hash, circuit breaker.
6. **Add `on_backend_unavailable` to `ObservabilityAdapter`** and emit in Redis backend.
7. **Tests (TDD):** unit (fakeredis / mocks), integration against real Redis (local Docker + GitHub Actions **Redis service container** — see **Testing with Redis**), fail-closed/open, mismatch detection, multi-cap enforcement, window reset.
