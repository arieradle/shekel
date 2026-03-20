# Fallback Models

Automatically switch to cheaper models when you hit your budget limit instead of crashing.

## Basic Fallback

Instead of raising `BudgetExceededError`, switch to a cheaper model:

```python
from shekel import budget

with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    # Starts with gpt-4o
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Tell me a story"}],
    )

# Check if fallback was activated
if b.model_switched:
    print(f"Switched to {b.fallback['model']} at ${b.switched_at_usd:.4f}")
    print(f"Spent on fallback: ${b.fallback_spent:.4f}")
```

## How It Works

1. You start with your preferred (expensive) model
1. Shekel tracks spending as normal
1. When spending reaches the `at_pct` fraction of `max_usd` (e.g., 80%):
1. **Without fallback**: No automatic switch occurs until `max_usd` is reached, then raises `BudgetExceededError`
1. **With fallback**: Switches to the specified cheaper model
1. Subsequent calls automatically use the fallback model
1. The fallback model shares the same `max_usd` budget — there is no separate ceiling. Once total spend reaches `max_usd`, `BudgetExceededError` is raised.

Graceful Degradation

Fallback models provide graceful degradation: your application keeps running with a cheaper model instead of crashing. Perfect for production environments where availability matters.

## Checking Fallback Status

The budget object provides properties to check fallback status:

```python
with budget(max_usd=2.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_my_agent()

# After execution
print(f"Model switched: {b.model_switched}")      # True/False
print(f"Switched at: ${b.switched_at_usd}")       # USD when switch occurred
print(f"Fallback spent: ${b.fallback_spent:.4f}") # Cost on fallback model
print(f"Total spent: ${b.spent:.4f}")             # Total cost (primary + fallback)
```

## Budget Enforcement with Fallback

The fallback model shares the same `max_usd` budget. Once total spending reaches `max_usd`, `BudgetExceededError` is raised:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
        # Switches to gpt-4o-mini at $0.80 (80% of $1.00)
        # Raises BudgetExceededError at $1.00
        run_expensive_operation()
except BudgetExceededError as e:
    print(f"Budget reached: ${e.spent:.4f}")
```

## Fallback Callbacks

Get notified when the fallback is activated:

```python
def on_fallback_switch(spent: float, limit: float, fallback_model: str):
    print(f"⚠️  Switched to {fallback_model}")
    print(f"   Reason: ${spent:.2f} exceeded ${limit:.2f}")

with budget(
    max_usd=5.00,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
    on_fallback=on_fallback_switch
) as b:
    run_my_agent()
```

### Logging Fallback Events

```python
import logging

logger = logging.getLogger(__name__)

def log_fallback(spent: float, limit: float, fallback_model: str):
    logger.warning(
        "LLM fallback activated",
        extra={
            "spent": spent,
            "limit": limit,
            "fallback_model": fallback_model,
            "overage": spent - limit,
        }
    )

with budget(max_usd=10.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}, on_fallback=log_fallback):
    run_production_agent()
```

### Alerting on Fallback

```python
import requests

def alert_fallback(spent: float, limit: float, fallback_model: str):
    # Send to monitoring
    requests.post("https://monitoring.example.com/events", json={
        "type": "llm_fallback",
        "spent": spent,
        "limit": limit,
        "fallback": fallback_model,
    })

with budget(max_usd=20.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}, on_fallback=alert_fallback):
    run_my_agent()
```

## Common Fallback Strategies

### GPT-4o → GPT-4o-mini

Most common pattern for OpenAI:

```python
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
```

**When to use:**

- General-purpose tasks
- Cost-sensitive applications
- Development/testing

### Claude 3 Opus → Claude 3 Haiku

For Anthropic models:

```python
with budget(max_usd=2.00, fallback={"at_pct": 0.8, "model": "claude-3-haiku-20240307"}):
    response = client.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
```

**When to use:**

- Long conversations
- High-volume applications
- Cost optimization

### o1 → GPT-4o-mini

For reasoning-heavy tasks:

```python
with budget(max_usd=5.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
    response = client.chat.completions.create(
        model="o1",
        messages=[{"role": "user", "content": "Solve this complex problem..."}],
    )
```

**When to use:**

- Complex reasoning tasks
- When you want the best possible answer but have budget constraints

## Combining USD and Call-Count Limits

You can set both `max_usd` and `max_llm_calls` at the same time. Shekel applies `at_pct` to **both** limits independently — whichever threshold is reached first triggers the fallback:

```python
with budget(
    max_usd=5.00,
    max_llm_calls=20,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
) as b:
    run_my_agent()
# Fallback activates at: $4.00 (80% of $5.00) OR 16 calls (80% of 20) — whichever comes first
```

**First-wins rule:** if your agent makes many cheap calls, it may hit the call-count threshold (`16 calls`) long before reaching the USD threshold (`$4.00`). Conversely, a few expensive calls may hit the USD threshold first. Design your thresholds with this in mind.

Tight call limits

If you want the call limit to be the primary circuit-breaker, set `max_usd` high (or omit it) and rely on `max_llm_calls` alone:

```python
with budget(max_llm_calls=20, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_my_agent()
# Switches at call 16, hard-stops at call 21
```

## `at_pct=1.0` — Reactive Fallback

Setting `at_pct=1.0` means the fallback activates only **after** a call pushes spend past `max_usd` — not proactively before it:

```python
with budget(max_usd=1.00, fallback={"at_pct": 1.0, "model": "gpt-4o-mini"}) as b:
    run_my_agent()
# No early switch — switches to gpt-4o-mini only after spending exceeds $1.00
# Then continues on gpt-4o-mini until BudgetExceededError (if still over limit)
```

**When to use `at_pct=1.0`:** when you want the primary model for as long as possible and only want a safety net to avoid a hard crash. The first call that exceeds the limit triggers the switch; subsequent calls use the cheaper model.

**When NOT to use it:** if your goal is proactive cost control, use a lower threshold like `0.8`. With `at_pct=1.0` you've already exceeded your budget before the switch happens.

## Same-Provider Requirement

Fallback models must be from the same provider:

```python
# ✅ Valid - both OpenAI
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
    client.chat.completions.create(model="gpt-4o", ...)

# ✅ Valid - both Anthropic
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "claude-3-haiku-20240307"}):
    client.messages.create(model="claude-3-opus-20240229", ...)

# ❌ Invalid - cross-provider
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
    client.messages.create(model="claude-3-opus-20240229", ...)
# Raises: ValueError: fallback model appears to be an OpenAI model but the current call is to Anthropic
```

Cross-Provider Fallback

Cross-provider fallback is not supported because OpenAI and Anthropic have different API signatures. Shekel validates that the fallback model matches the provider of the API call and raises `ValueError` if they don't match.

## Combining with Warnings

Use both warnings and fallback for maximum visibility:

```python
with budget(max_usd=5.00, warn_at=0.7, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_my_agent()

# Warning at $3.50 (70%)
# Switches to gpt-4o-mini at $4.00 (80%)
# Raises BudgetExceededError at $5.00 (100%)
```

This gives you:

1. Early warning at 70% ($3.50)
1. Automatic fallback at 80% ($4.00)
1. Hard stop at 100% ($5.00)

## Spend Summary with Fallback

The summary shows fallback usage:

```python
with budget(max_usd=2.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    run_my_agent()

print(b.summary())
```

Output:

```text
┌─ Shekel Budget Summary ────────────────────────────────────┐
│ Total: $2.5430  Limit: $2.00  Calls: 25  Status: SWITCHED
├────────────────────────────────────────────────────────────┤
│  #    Model                        Input  Output      Cost
│  ────────────────────────────────────────────────────────
│  1    gpt-4o                       1,200     300  $0.0060
│  2    gpt-4o                       1,500     450  $0.0082
│  ...
│  15   gpt-4o-mini                  1,100     280  $0.0003 ← fallback
│  16   gpt-4o-mini                  1,050     260  $0.0003 ← fallback
│  ...
├────────────────────────────────────────────────────────────┤
│  gpt-4o: 14 calls  $2.0140
│  gpt-4o-mini: 11 calls (fallback)  $0.5290
│  Switched at: $2.0140
└────────────────────────────────────────────────────────────┘
```

## Testing Fallback

Test that fallback works correctly:

```python
import pytest
from shekel import budget

def test_fallback_activation():
    with budget(max_usd=0.01, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
        # This should trigger fallback
        for i in range(10):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": f"Test {i}"}],
            )

    # Verify fallback was activated
    assert b.model_switched is True
    assert b.switched_at_usd > 0
    assert b.fallback_spent > 0

def test_fallback_callback():
    callback_fired = []

    def capture_fallback(spent, limit, fallback):
        callback_fired.append((spent, limit, fallback))

    with budget(max_usd=0.01, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}, on_fallback=capture_fallback):
        # Trigger fallback
        ...

    assert len(callback_fired) == 1
    assert callback_fired[0][2] == "gpt-4o-mini"
```

## When NOT to Use Fallback

Fallback is not appropriate when:

1. **Quality is critical** - If you need consistent model quality, use a higher budget instead
1. **Single expensive call** - If one call exceeds the budget, fallback won't help
1. **Model-specific features** - If you rely on features only available in the primary model

In these cases, use:

- Higher `max_usd` limit
- Better prompt engineering to reduce tokens
- Task decomposition to spread costs

## Advanced: Multi-Tier Fallback

Shekel supports one fallback level. For multi-tier fallback, use nested budgets:

```python
from shekel import budget, BudgetExceededError

def call_with_fallback_chain(prompt: str):
    # Try tier 1: o1
    try:
        with budget(max_usd=5.00):
            return client.chat.completions.create(model="o1", ...)
    except BudgetExceededError:
        pass

    # Try tier 2: gpt-4o with fallback to gpt-4o-mini
    try:
        with budget(max_usd=2.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}):
            return client.chat.completions.create(model="gpt-4o", ...)
    except BudgetExceededError:
        pass

    # Final tier: gpt-4o-mini with very low budget
    with budget(max_usd=0.10):
        return client.chat.completions.create(model="gpt-4o-mini", ...)
```

## Next Steps

- **[Accumulating Budgets](https://arieradle.github.io/shekel/1.1.0/usage/accumulating-budgets/index.md)** - Multi-session tracking
- **[Budget Enforcement](https://arieradle.github.io/shekel/1.1.0/usage/budget-enforcement/index.md)** - More on limits and warnings
- **[API Reference](https://arieradle.github.io/shekel/1.1.0/api-reference/index.md)** - Complete fallback parameters
