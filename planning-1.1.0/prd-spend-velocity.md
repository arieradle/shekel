# PRD: Spend Velocity Circuit Breaker (`max_velocity`)

**Feature:** `max_velocity="$0.50/min"` — rolling-window burn-rate enforcement
**Target release:** v1.1.0
**Status:** Draft
**Date:** 2026-03-19

---

## 1. Problem Statement

Shekel's current budget enforcement model is purely cumulative: it compares total spend against a fixed cap (`max_usd`) and raises `BudgetExceededError` only when that ceiling is crossed. This model is insufficient for runaway detection in two failure modes:

**Failure mode A — cap never hit, but spend rate is catastrophic.**
An agent with `max_usd=100.00` burning $2/second will cost $120 in a minute. The cap stops the bleeding eventually, but not before significant damage is done. By the time the cap fires, the damage-per-minute is already embedded in the bill.

**Failure mode B — slow cap, fast burn, invisible until too late.**
A $5/hr `TemporalBudget` is designed for a steady trickle of ambient API calls. A misconfigured agent loop that calls GPT-4o 50 times in 10 seconds will blow through $5 before the human operator can react. Total spend never exceeds the cap, so nothing fires.

**The core gap:** no existing shekel primitive tracks *burn rate* — spend per unit time. A $5 total budget spent in 30 seconds is an emergency signal. A $5 total budget spent across an 8-hour session is expected. The amount is the same; the meaning is opposite.

### Why this matters for production LLM applications

- Infinite agent loops, prompt injection attacks, and misconfigured retry logic can all produce runaway spend in seconds
- Cloud LLM billing is real-time; there is no "undo"
- Monitoring/alerting tools operate on lag; by the time a Datadog alert fires, the damage is done
- The only reliable circuit breaker is in-process, synchronous, and checked before every call

---

## 2. Target Users and Jobs-to-Be-Done

| User | Context | Job-to-be-done |
|------|---------|----------------|
| **Production ML engineer** | Deploys LLM agents to production with `max_usd` caps | Detect runaway loops before they burn through the monthly API budget |
| **Platform/infra team** | Manages shared LLM API keys used by multiple services | Enforce per-service rate limits that are independent of session length |
| **LLM agent developer** | Iterating locally on agent code with real API keys | Protect against accidentally triggering an infinite loop during development |
| **Compliance/FinOps engineer** | Sets spending guardrails for internal tools | Enforce "no more than $X per minute" SLA-style constraints regardless of total budget |

---

## 3. User Stories

**US-1 — Runaway loop protection**
As a production ML engineer, I want to add `max_velocity="$0.50/min"` to my budget so that an accidentally infinite agent loop raises an error within seconds, before it can do significant financial damage, even if my `max_usd` cap is large.

**US-2 — Compound guardrails**
As a platform engineer, I want to combine `max_usd=50.00` with `max_velocity="$2/min"` so that my agent has a generous total budget for long-running tasks but cannot spike beyond a reasonable burn rate at any point.

**US-3 — Velocity warning before hard stop**
As an LLM agent developer, I want to receive a `warn_velocity` callback before the hard velocity limit fires so that I can log a warning or degrade gracefully instead of having the error surface to the end user unexpectedly.

**US-4 — Fine-grained window control**
As a FinOps engineer, I want to express velocity limits using natural time specs like `"$0.10/30s"` or `"$10/hr"` so that I can match the velocity window to my organization's billing granularity without doing manual math.

**US-5 — Velocity in warn-only mode**
As an LLM agent developer, I want `warn_only=True` to suppress velocity errors just as it suppresses cap errors, so that I can use velocity as an observability signal during development without breaking my application flow.

---

## 4. Success Metrics

| Metric | Target |
|--------|--------|
| Time-to-circuit-break on infinite loop (100 calls/sec) | < 2 window durations |
| False positive rate on legitimate bursty workloads | 0% (velocity check is purely additive; existing caps unchanged) |
| API surface change | Additive only — zero breaking changes to existing `Budget`/`budget()` signatures |
| Test coverage | 100% line coverage on velocity code paths |
| Parsing error clarity | `ValueError` with human-readable message on any malformed spec |

---

## 5. Scope

### In scope

- New `Budget.__init__` parameters: `max_velocity: str | None` and `warn_velocity: str | None`
- `budget()` factory function updated to accept both new parameters and pass them through
- `_parse_velocity_spec(spec)` parser supporting `s`/`sec`, `m`/`min`, `h`/`hr` time units and optional numeric multiplier (e.g. `"$0.10/30s"`)
- Rolling-window velocity tracking via `collections.deque` of `(timestamp, spend_delta)` tuples inside `Budget`
- `SpendVelocityExceededError` exception subclassing `BudgetExceededError`
- Velocity check integrated into `_record_spend()` pipeline, after `warn_at` check and before cap check
- `warn_velocity` fires `on_warn` callback (or `warnings.warn`) once per velocity-window breach, then resets
- `warn_only=True` suppresses velocity raises (consistent with existing cap behavior)
- Both sync and async context manager paths covered

### Out of scope

- Persistent velocity state across process restarts (in-memory only, same as core Budget)
- Per-model or per-tool velocity limits (velocity applies to aggregate spend)
- Velocity enforcement in `TemporalBudget` (TemporalBudget already handles rolling windows; velocity is a `Budget`-level feature)
- Network-distributed velocity state (no Redis backend for velocity in this release)
- Streaming call partial-spend velocity (streaming spend is attributed at call completion, same as today)
- UI / dashboard integration (out of scope for library)

---

## 6. High-Level API Design

### Basic velocity cap

```python
from shekel import budget

with budget(max_usd=50.00, max_velocity="$0.50/min") as b:
    run_agent()  # raises SpendVelocityExceededError if $0.50 spent within any 60s window
```

### Velocity with total cap

```python
with budget(max_usd=5.00, max_velocity="$1/min") as b:
    run_agent()
    # SpendVelocityExceededError fires if burn rate exceeds $1/min
    # BudgetExceededError fires if total spend exceeds $5.00
    # whichever comes first
```

### Velocity warning before hard stop

```python
with budget(
    max_usd=10.00,
    max_velocity="$1/min",
    warn_velocity="$0.75/min",
    on_warn=lambda spent, limit: log.warning(f"High burn rate: ${spent:.4f}"),
) as b:
    run_agent()
```

### Warn-only mode — velocity as an observability signal

```python
with budget(max_velocity="$0.50/min", warn_only=True) as b:
    run_agent()  # logs warning but never raises; useful in dev/staging
```

### Short-window velocity for tight loop detection

```python
with budget(max_velocity="$0.10/30s") as b:
    run_agent()  # stops agent if $0.10 spent in any 30-second window
```

### Track-only budget with velocity guard

```python
with budget(max_velocity="$2/hr") as b:
    # No max_usd — no total cap — but velocity is still enforced
    run_agent()
```

---

## 7. Edge Cases the Product Must Handle

| Edge case | Expected behavior |
|-----------|-------------------|
| **First call in empty window** | Always allowed. A single call can never exceed velocity (no window history yet — see tech design). |
| **Single call larger than velocity limit** | Allowed — the call already happened (spend is attributed post-call). Velocity check guards the *next* call, not the current one. |
| **`warn_velocity` >= `max_velocity`** | `ValueError` at construction time with clear message. |
| **`warn_velocity` without `max_velocity`** | `ValueError` at construction time. |
| **Velocity window expires between calls** | Deque entries older than window are pruned; burn rate resets to zero. Next call starts a fresh window. |
| **`warn_only=True` + `max_velocity`** | Warning fires via `on_warn` or `warnings.warn`; `SpendVelocityExceededError` is never raised. |
| **Nested budget with parent velocity** | Parent velocity tracks spend propagated from child on child exit — not mid-child. Each budget tracks its own velocity independently. |
| **Zero-cost call (e.g. cached response)** | Appended to deque with `delta=0.0`; no effect on velocity sum. |
| **Malformed spec string** | `ValueError` with human-readable message: `"Cannot parse velocity spec: '$1.50'"` (missing unit). |
| **Fractional time units** | `"$0.50/1.5min"` → window of 90 seconds. Supported. |
| **`max_velocity` without `max_usd`** | Supported — velocity can guard a track-only budget. |
| **Async context manager** | Velocity check runs inside `_record_spend()`, which is called from sync code paths already; no separate async handling needed. |
| **`warn_fired` re-entrancy** | Velocity warn fires once per window (tracked by `_velocity_warn_fired` flag, reset when window rolls over). |

---

## 8. Non-Goals and Constraints

- Velocity enforcement must never alter the existing `warn_at` / `max_usd` behavior. It is purely additive.
- The velocity parser must be a standalone pure function. No class state at parse time.
- `SpendVelocityExceededError` must subclass `BudgetExceededError` so existing `except BudgetExceededError` handlers catch it.
- The deque pruning must happen on every `_record_spend()` call, not on a timer, to keep the implementation deterministic and free of background threads.
