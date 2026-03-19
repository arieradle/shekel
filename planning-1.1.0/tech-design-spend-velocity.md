# Technical Design: Spend Velocity Circuit Breaker

**Feature:** `max_velocity="$0.50/min"` — rolling-window burn-rate enforcement
**Target release:** v1.1.0
**Status:** Draft
**Date:** 2026-03-19

---

## 1. Architecture Overview

Velocity enforcement is a thin layer inside `Budget._record_spend()`. It does not require a new class, backend, or async machinery. The check is synchronous, pure-Python, and runs entirely inside the existing `_record_spend` call after the LLM response has been received.

### Existing `_record_spend` pipeline (v1.0.x)

```
_record_spend(cost, model, tokens)
  ├─ accumulate _spent, _spent_direct, _last_model, _last_tokens
  ├─ append to _calls
  ├─ increment _calls_made
  ├─ _check_warn()       ← warn_at threshold
  ├─ _check_limit()      ← max_usd hard cap
  └─ _check_call_limit() ← max_llm_calls hard cap
```

### New `_record_spend` pipeline (v1.1.0)

```
_record_spend(cost, model, tokens)
  ├─ accumulate _spent, _spent_direct, _last_model, _last_tokens
  ├─ append to _calls
  ├─ increment _calls_made
  ├─ _append_velocity_entry(cost)  ← NEW: deque bookkeeping
  ├─ _check_velocity_warn()        ← NEW: warn_velocity threshold
  ├─ _check_velocity_limit()       ← NEW: max_velocity hard cap
  ├─ _check_warn()                 ← existing warn_at threshold
  ├─ _check_limit()                ← existing max_usd hard cap
  └─ _check_call_limit()           ← existing max_llm_calls hard cap
```

**Ordering rationale:** velocity checks run before `_check_warn()` and `_check_limit()` so that a runaway loop is stopped at the velocity level first (providing the most specific error type), rather than being masked by the total cap. Both can fire in sequence in theory; in practice velocity fires first when burn rate is the pathological condition.

---

## 2. Velocity Spec Parser

### Function signature

```python
# shekel/_budget.py

def _parse_velocity_spec(spec: str) -> tuple[float, float]:
    """Parse a velocity spec string into (limit_usd, window_seconds).

    Supported formats:
        "$0.50/min"   -> (0.50, 60.0)
        "$2/hr"       -> (2.0, 3600.0)
        "$0.10/30s"   -> (0.10, 30.0)
        "$1/1.5min"   -> (1.0, 90.0)
        "$5/h"        -> (5.0, 3600.0)
        "$0.25/sec"   -> (0.25, 1.0)

    Returns:
        (limit_usd, window_seconds) — both positive floats.

    Raises:
        ValueError: if spec cannot be parsed or values are non-positive.
    """
```

### Regex pattern

```python
_VELOCITY_RE = re.compile(
    r"^\s*"
    r"\$(?P<amount>[\d.]+)"
    r"\s*/\s*"
    r"(?P<count>[\d.]*)"        # optional multiplier, e.g. "30" in "30s"
    r"\s*(?P<unit>sec|min|hr|h|m|s)\b"
    r"\s*$",
    re.IGNORECASE,
)

_VELOCITY_UNIT_SECONDS: dict[str, float] = {
    "s": 1.0,
    "sec": 1.0,
    "min": 60.0,
    "m": 60.0,
    "hr": 3600.0,
    "h": 3600.0,
}
```

### Parse logic (pseudocode)

```python
def _parse_velocity_spec(spec: str) -> tuple[float, float]:
    m = _VELOCITY_RE.match(spec.strip())
    if not m:
        raise ValueError(f"Cannot parse velocity spec: {spec!r}. "
                         f"Expected format: '$<amount>/<count><unit>', e.g. '$0.50/min'")
    amount = float(m.group("amount"))
    if amount <= 0:
        raise ValueError(f"Velocity amount must be > 0, got {amount}")
    unit = m.group("unit").lower()
    unit_seconds = _VELOCITY_UNIT_SECONDS[unit]
    count_str = m.group("count")
    count = float(count_str) if count_str else 1.0
    if count <= 0:
        raise ValueError(f"Velocity window multiplier must be > 0, got {count}")
    window_seconds = count * unit_seconds
    return amount, window_seconds
```

### Parser is a module-level pure function

`_parse_velocity_spec` is not a method. It has no side effects. It is called once in `Budget.__init__` and the result is stored as `self._velocity_limit_usd` and `self._velocity_window_seconds`. This keeps validation at construction time, consistent with how `max_usd` validation works today.

---

## 3. Rolling Window Data Structure

### Deque of `(timestamp, delta)` tuples

```python
from collections import deque

# In Budget.__init__:
self._velocity_window: deque[tuple[float, float]] = deque()
# Each entry: (time.monotonic() at record time, cost_usd of that call)
```

### Pruning logic

On each `_record_spend()` call, before checking velocity:

```python
def _prune_velocity_window(self, now: float) -> None:
    """Remove entries older than the velocity window."""
    cutoff = now - self._velocity_window_seconds
    while self._velocity_window and self._velocity_window[0][0] < cutoff:
        self._velocity_window.popleft()
```

### Append logic

After pruning, append the new entry:

```python
def _append_velocity_entry(self, cost: float) -> None:
    now = time.monotonic()
    self._prune_velocity_window(now)
    self._velocity_window.append((now, cost))
```

### Window sum

```python
@property
def _velocity_window_sum(self) -> float:
    return sum(delta for _, delta in self._velocity_window)
```

**Why deque?** `popleft()` is O(1). The window typically contains only a handful of entries (N calls within a short time window). Memory is bounded: entries older than `window_seconds` are pruned on every call. No background thread or timer needed.

**Why monotonic clock?** `time.monotonic()` is guaranteed non-decreasing and immune to wall-clock adjustments (NTP, DST, etc.). All existing shekel timing uses `time.monotonic()`.

---

## 4. Exact Check Logic

### `_check_velocity_warn()`

```python
def _check_velocity_warn(self) -> None:
    if self._warn_velocity_limit_usd is None:
        return
    window_sum = self._velocity_window_sum
    if (
        not self._velocity_warn_fired
        and window_sum >= self._warn_velocity_limit_usd
    ):
        self._velocity_warn_fired = True
        if self.on_warn is not None:
            self.on_warn(window_sum, self._warn_velocity_limit_usd)
        else:
            warnings.warn(
                f"shekel: velocity warning — ${window_sum:.4f} spent in the last "
                f"{self._velocity_window_seconds:.0f}s "
                f"(warn_velocity limit: ${self._warn_velocity_limit_usd:.2f})",
                stacklevel=5,
            )
```

**`_velocity_warn_fired` reset:** reset to `False` in `_reset_velocity_window()` which is called from `_reset_state()`. It is also reset when the velocity window has fully rolled over (all entries pruned). The window-rollover reset is handled lazily: when `_prune_velocity_window` empties the deque, `_velocity_warn_fired` is set to `False` so the warning can fire again in the next window.

### `_check_velocity_limit()`

```python
def _check_velocity_limit(self) -> None:
    if self._velocity_limit_usd is None:
        return
    window_sum = self._velocity_window_sum
    if window_sum > self._velocity_limit_usd:
        if self.warn_only:
            if self.on_warn is not None:
                self.on_warn(window_sum, self._velocity_limit_usd)
            else:
                warnings.warn(
                    f"shekel: velocity limit would be exceeded — "
                    f"${window_sum:.4f} in {self._velocity_window_seconds:.0f}s "
                    f"(limit: ${self._velocity_limit_usd:.2f}/window). "
                    f"warn_only=True, continuing.",
                    stacklevel=5,
                )
            return
        raise SpendVelocityExceededError(
            spent_in_window=window_sum,
            limit_usd=self._velocity_limit_usd,
            window_seconds=self._velocity_window_seconds,
            model=self._last_model,
            tokens=self._last_tokens,
        )
```

### "First call always passes" invariant

The deque starts empty. `_append_velocity_entry(cost)` appends *before* `_check_velocity_limit()` is called. However, the check fires when `window_sum > limit_usd`. On the very first call:
- The deque has zero entries before the call
- The call is appended: deque now has one entry with the call's cost
- `_check_velocity_limit()` runs: `window_sum == cost_of_first_call`
- If that one call costs more than the velocity limit, the check fires

This is correct and expected behavior: the check is not "first call always passes" in an unconditional sense — it is "a single call can exceed the velocity limit if it's individually expensive." The velocity circuit breaker protects against *accumulation* within the window. A single expensive call is a different risk addressed by `max_usd`.

A deliberate design choice: since spend is attributed *after* the LLM call completes, the first call in any window always completes. The guard fires starting at the second call that would push the window sum over the limit.

---

## 5. Files to Create / Modify

### Modified files

| File | Changes |
|------|---------|
| `shekel/exceptions.py` | Add `SpendVelocityExceededError` class |
| `shekel/_budget.py` | Add `_parse_velocity_spec()` function; add `max_velocity`, `warn_velocity` params to `Budget.__init__`; add `_velocity_window` deque, `_velocity_limit_usd`, `_velocity_window_seconds`, `_warn_velocity_limit_usd`, `_velocity_warn_fired` instance vars; add `_append_velocity_entry()`, `_prune_velocity_window()`, `_check_velocity_warn()`, `_check_velocity_limit()` methods; update `_record_spend()`, `_reset_state()` |
| `shekel/__init__.py` | Export `SpendVelocityExceededError` |

### New files

| File | Purpose |
|------|---------|
| `tests/test_spend_velocity.py` | All velocity-specific tests |

### Files NOT modified

- `shekel/_temporal.py` — `TemporalBudget` already handles rolling windows via its backend; velocity is a `Budget`-level concern and does not extend to `TemporalBudget` in this release
- `shekel/_patch.py` — no changes to the intercept layer
- `shekel/_context.py` — no changes to context var management

---

## 6. `SpendVelocityExceededError` Exception Design

```python
# shekel/exceptions.py

class SpendVelocityExceededError(BudgetExceededError):
    """Raised when LLM spend rate exceeds the configured velocity limit.

    Subclasses BudgetExceededError so existing except-clauses catch it.

    Attributes:
        spent_in_window: Total USD spent within the velocity window.
        limit_usd: The configured velocity limit in USD.
        window_seconds: The rolling window duration in seconds.
        velocity_per_min: Normalized spend rate (USD/min) for display.
        limit_per_min: Normalized limit (USD/min) for display.
    """

    def __init__(
        self,
        spent_in_window: float,
        limit_usd: float,
        window_seconds: float,
        model: str = "unknown",
        tokens: dict[str, int] | None = None,
    ) -> None:
        self.spent_in_window = spent_in_window
        self.limit_usd = limit_usd
        self.window_seconds = window_seconds
        # Normalize to per-minute for human-readable display
        self.velocity_per_min = (spent_in_window / window_seconds) * 60.0
        self.limit_per_min = (limit_usd / window_seconds) * 60.0
        super().__init__(
            spent=spent_in_window,
            limit=limit_usd,
            model=model,
            tokens=tokens,
        )

    def __str__(self) -> str:
        input_tokens = self.tokens.get("input", 0)
        output_tokens = self.tokens.get("output", 0)
        total_tokens = input_tokens + output_tokens
        token_str = (
            f"  Last call: {self.model} — "
            f"{input_tokens} input + {output_tokens} output tokens\n"
            if total_tokens > 0
            else f"  Last call: {self.model}\n"
        )
        return (
            f"Spend velocity limit exceeded: "
            f"${self.spent_in_window:.4f} spent in {self.window_seconds:.0f}s window "
            f"(limit: ${self.limit_usd:.2f}/{self.window_seconds:.0f}s, "
            f"~${self.limit_per_min:.2f}/min)\n"
            f"{token_str}"
            f"  Tip: Increase max_velocity, add warn_velocity for early warning, "
            f"or use warn_only=True to observe without blocking."
        )
```

**Why subclass `BudgetExceededError`?** Existing production code that catches `BudgetExceededError` should automatically handle velocity errors as well. Velocity is a form of budget enforcement, not a separate error family. Callers that need to distinguish can `isinstance(exc, SpendVelocityExceededError)`.

---

## 7. `max_velocity` and `warn_velocity` Interaction

### Construction-time validation

```python
# In Budget.__init__, after parsing:
if warn_velocity is not None and max_velocity is None:
    raise ValueError("warn_velocity requires max_velocity to be set")

if (warn_velocity is not None and max_velocity is not None
        and _warn_velocity_limit_usd >= _velocity_limit_usd):
    raise ValueError(
        f"warn_velocity limit (${_warn_velocity_limit_usd:.4f}) must be less than "
        f"max_velocity limit (${_velocity_limit_usd:.4f})"
    )
```

Note: `warn_velocity` and `max_velocity` can have *different* window durations. `"$0.40/min"` as `warn_velocity` and `"$0.50/min"` as `max_velocity` both use 60-second windows — the comparison is on the `limit_usd` field, not the rate. If the windows differ, the comparison is still on `limit_usd` of each parsed spec independently; the developer is responsible for choosing coherent values.

**Recommended guidance (docstring):** use the same window duration for `warn_velocity` and `max_velocity` to avoid surprising behavior.

### Runtime interaction

Each call to `_record_spend()`:

1. `_append_velocity_entry(cost)` — prunes old entries, appends new one
2. `_check_velocity_warn()` — fires once if `window_sum >= warn_velocity.limit_usd`
3. `_check_velocity_limit()` — raises (or warns if `warn_only`) if `window_sum > max_velocity.limit_usd`

**Separate warn-fired flag:** `_velocity_warn_fired` is independent of `_warn_fired` (which tracks the `warn_at` threshold). They can both fire in the same session.

**Warn fires, then limit fires:** if a session accumulates spend that first crosses `warn_velocity` and then crosses `max_velocity`, both fire in sequence on different `_record_spend` calls. The warn always precedes the hard stop (by design, since `warn_velocity < max_velocity`).

---

## 8. Velocity and Nested Budgets

### Design principle: each budget tracks its own velocity independently

Velocity state (`_velocity_window` deque) lives on each `Budget` instance. It is not propagated up to the parent.

### Parent velocity tracking

The parent budget's velocity deque is updated when **the child context exits**, not on each child call. This is consistent with how `_spent` propagates today: `self.parent._spent += self._spent` happens in `__exit__`. The parent velocity deque receives a single entry representing the entire child session's spend delta.

This means the parent velocity window tracks *session-level* spend attributions, not individual call-level deltas. For most use cases this is correct: the parent budget is the coarser scope.

### Child velocity tracking

The child budget tracks its own call-by-call velocity. If a child has `max_velocity="$0.10/30s"`, every call inside the child's `with` block is checked against that window. This is independent of whether the parent also has `max_velocity`.

### No cross-propagation of velocity warnings

`_velocity_warn_fired` and `_warn_fired` are never copied between parent and child. Each budget fires its own warnings independently.

### Example

```python
with budget(max_usd=10.00, max_velocity="$2/min", name="parent") as parent:
    # parent velocity window accumulates child spend on child exit
    with budget(max_velocity="$0.50/min", name="child") as child:
        # child velocity checked call-by-call
        run_fast_agent()  # may raise SpendVelocityExceededError from child
    # child exits → parent._spent += child._spent
    # parent velocity window gets one entry: (now, child_total_spend)
```

---

## 9. Public API Additions

### `Budget.__init__` signature additions

```python
def __init__(
    self,
    max_usd: float | None = None,
    warn_at: float | None = None,
    on_warn: Callable[[float, float], None] | None = None,
    price_per_1k_tokens: dict[str, float] | None = None,
    fallback: dict[str, Any] | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
    name: str | None = None,
    max_llm_calls: int | None = None,
    max_tool_calls: int | None = None,
    tool_prices: dict[str, float] | None = None,
    warn_only: bool = False,
    # NEW in v1.1.0:
    max_velocity: str | None = None,
    warn_velocity: str | None = None,
) -> None:
```

### New instance variables (set in `__init__`)

```python
# Velocity spec — parsed at construction time
self._velocity_limit_usd: float | None          # None if max_velocity not set
self._velocity_window_seconds: float            # 0.0 if max_velocity not set
self._warn_velocity_limit_usd: float | None     # None if warn_velocity not set
self._warn_velocity_window_seconds: float       # 0.0 if warn_velocity not set

# Velocity runtime state
self._velocity_window: deque[tuple[float, float]]  # (monotonic_time, cost_usd)
self._velocity_warn_fired: bool                 # True after first velocity warn fires
```

### `budget()` factory function

The `budget()` factory already passes `**kwargs` through to the `Budget` constructor. No additional changes are required; `max_velocity` and `warn_velocity` flow through automatically.

### New public exception export

```python
# shekel/__init__.py
from shekel.exceptions import SpendVelocityExceededError
```

### `_reset_state()` additions

```python
def _reset_state(self) -> None:
    # ... existing resets ...
    # NEW:
    self._velocity_window.clear()
    self._velocity_warn_fired = False
```

---

## 10. Test Strategy

**File:** `tests/test_spend_velocity.py`

### Key scenarios

| Test | What it verifies |
|------|-----------------|
| `test_parse_velocity_spec_basic` | `"$0.50/min"` → `(0.50, 60.0)` |
| `test_parse_velocity_spec_multiplier` | `"$0.10/30s"` → `(0.10, 30.0)` |
| `test_parse_velocity_spec_hr` | `"$2/hr"` and `"$2/h"` → `(2.0, 3600.0)` |
| `test_parse_velocity_spec_fractional_window` | `"$1/1.5min"` → `(1.0, 90.0)` |
| `test_parse_velocity_spec_invalid_missing_unit` | `ValueError` on `"$1.50"` |
| `test_parse_velocity_spec_invalid_no_dollar` | `ValueError` on `"1.50/min"` |
| `test_parse_velocity_spec_zero_amount` | `ValueError` on `"$0/min"` |
| `test_velocity_no_raise_under_limit` | Two calls summing below limit — no error |
| `test_velocity_raises_when_exceeded` | Three quick calls exceed window limit — `SpendVelocityExceededError` raised |
| `test_velocity_window_rolls_over` | Calls in window 1 exceed limit; after window expires, new calls succeed |
| `test_velocity_first_call_single_expensive` | Single call larger than limit — raises on the *second* call that pushes sum over |
| `test_velocity_warn_fires_before_limit` | `warn_velocity` fires warning; subsequent call fires error |
| `test_velocity_warn_fires_once_per_window` | Warning fires only once even if multiple calls cross warn threshold |
| `test_velocity_warn_only_no_raise` | `warn_only=True` — never raises, warns via `warnings.warn` |
| `test_velocity_warn_only_custom_callback` | `warn_only=True` with `on_warn` — callback fires, no raise |
| `test_velocity_combined_with_max_usd` | `max_usd` and `max_velocity` coexist; velocity fires first on fast burn |
| `test_velocity_combined_with_warn_at` | `warn_at` and `warn_velocity` both fire independently |
| `test_velocity_error_subclasses_budget_exceeded` | `isinstance(exc, BudgetExceededError)` is True |
| `test_velocity_error_str_contains_window` | Error message includes window duration and limit |
| `test_velocity_error_attributes` | `.spent_in_window`, `.limit_usd`, `.window_seconds`, `.velocity_per_min` correct |
| `test_velocity_warn_velocity_requires_max_velocity` | `ValueError` when `warn_velocity` set without `max_velocity` |
| `test_velocity_warn_velocity_must_be_less_than_max` | `ValueError` when `warn_velocity >= max_velocity` |
| `test_velocity_reset_clears_window` | `budget.reset()` clears `_velocity_window` and `_velocity_warn_fired` |
| `test_velocity_async_context_manager` | Async `with budget(max_velocity=...)` raises on fast burn (async path) |
| `test_velocity_nested_child_fires_independently` | Child velocity error does not affect parent velocity window |
| `test_velocity_nested_parent_receives_child_spend_on_exit` | After child exits, parent velocity window has one entry for child's total spend |
| `test_velocity_zero_cost_calls_ignored` | Calls with `cost=0.0` appended but don't trigger velocity |
| `test_velocity_track_only_no_max_usd` | `budget(max_velocity="$0.50/min")` with no `max_usd` still enforces velocity |

### Test patterns

Use `monkeypatch` + `time.monotonic` override to simulate passage of time without sleeping:

```python
def test_velocity_window_rolls_over(monkeypatch):
    times = iter([0.0, 10.0, 10.5, 75.0, 75.5])  # jump past 60s window
    monkeypatch.setattr("time.monotonic", lambda: next(times))
    with budget(max_velocity="$0.10/min") as b:
        b._record_spend(0.06, "gpt-4o", {"input": 100, "output": 50})  # t=10.0
        b._record_spend(0.06, "gpt-4o", {"input": 100, "output": 50})  # t=10.5 → exceeds
        # ... expect SpendVelocityExceededError
```

Use `pytest.raises(SpendVelocityExceededError)` for hard-stop cases.
Use `recwarn` or `pytest.warns(UserWarning)` for warning cases.

---

## 11. Edge Cases: Implementation Notes

### Sync vs async

`_record_spend()` is called from `_patch.py` interceptors which work identically for both sync and async LLM client calls. The velocity check inside `_record_spend()` is pure synchronous code and requires no async adaptation.

### Streaming calls

Streaming API calls attribute their full cost at stream completion (current shekel behavior). `_record_spend()` is called once per stream, not per chunk. Velocity tracking inherits this: each stream completion appends one entry to the deque. No changes to streaming behavior needed.

### Thread safety

`Budget` objects are documented as not thread-safe (same caveat as the existing class). The `deque` is not protected by a lock. This is consistent with existing behavior.

### `deque` maxlen

Do not set a `maxlen` on the deque. The bound is enforced by time-based pruning, not by count. A maxlen would incorrectly drop old entries when many calls happen in a burst, understating the window sum.

### Velocity and `TemporalBudget`

`TemporalBudget` overrides `_record_spend()` and calls `super()._record_spend()` after its backend check. If `max_velocity` is passed to `TemporalBudget.__init__`, the parent `Budget.__init__` will set up the velocity deque, and the velocity check will run inside `super()._record_spend()`. This is technically functional, but the interaction between TemporalBudget's rolling window and Budget's velocity window is complex. The v1.1.0 scope explicitly excludes `TemporalBudget` velocity support; raise a `ValueError` in `TemporalBudget.__init__` if `max_velocity` is passed, with a message directing users to use the temporal spec string instead.
