# Budget Enforcement

Learn how to enforce spending limits with hard caps, soft warnings, and custom callbacks.

## Hard Budget Caps

The most common use case is enforcing a strict budget limit:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=1.00) as b:
        run_my_agent()
    print(f"Success! Spent: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: {e}")
```

When the budget is exceeded:

1. Shekel raises `BudgetExceededError`
1. The exception contains detailed information
1. No further API calls are allowed in that context

Hard Caps Stop Execution

When `max_usd` is exceeded, shekel raises an exception immediately. The current API call completes, but no further calls are made. Use [fallback models](https://arieradle.github.io/shekel/1.1.0/usage/fallback-models/index.md) if you want to continue with a cheaper model instead.

## Soft Warnings

Get early warnings before hitting the limit:

```python
with budget(max_usd=10.00, warn_at=0.8) as b:
    run_my_agent()
```

This prints a warning when spending reaches $8.00 (80% of $10.00):

```text
UserWarning: shekel: $8.0234 spent — 80% of $10.00 budget reached.
```

### Custom Warning Thresholds

The `warn_at` parameter accepts any value between 0.0 and 1.0:

```python
# Warn at 50%
with budget(max_usd=5.00, warn_at=0.5):
    run_agent()  # Warns at $2.50

# Warn at 90%
with budget(max_usd=5.00, warn_at=0.9):
    run_agent()  # Warns at $4.50

# Warn at 95%
with budget(max_usd=5.00, warn_at=0.95):
    run_agent()  # Warns at $4.75
```

Finding the Right Threshold

- **0.5-0.7** - Good for experimental/development work
- **0.8** - Recommended default for production
- **0.9-0.95** - For tighter budgets where you want maximum usage

## Custom Warning Callbacks

Replace the default warning with your own handler:

```python
def my_warning_handler(spent: float, limit: float):
    print(f"⚠️  ALERT: ${spent:.2f} of ${limit:.2f} used!")
    print(f"   {(spent/limit)*100:.1f}% of budget consumed")

with budget(max_usd=5.00, warn_at=0.8, on_warn=my_warning_handler):
    run_my_agent()
```

### Logging Integration

Integrate with Python's logging framework:

```python
import logging

logger = logging.getLogger(__name__)

def log_budget_warning(spent: float, limit: float):
    logger.warning(
        "Budget warning",
        extra={
            "spent": spent,
            "limit": limit,
            "percentage": (spent / limit) * 100,
        }
    )

with budget(max_usd=10.00, warn_at=0.8, on_warn=log_budget_warning):
    run_my_agent()
```

### Alerting Services

Send alerts to external services:

```python
import requests

def send_slack_alert(spent: float, limit: float):
    webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    message = {
        "text": f"⚠️ LLM Budget Alert: ${spent:.2f} / ${limit:.2f} used"
    }
    requests.post(webhook_url, json=message)

with budget(max_usd=50.00, warn_at=0.8, on_warn=send_slack_alert):
    run_production_agent()
```

### Multiple Actions

Trigger multiple actions in your callback:

```python
def comprehensive_alert(spent: float, limit: float):
    # 1. Log it
    logger.warning(f"Budget at {(spent/limit)*100:.0f}%")

    # 2. Send to monitoring
    metrics.gauge("llm.budget.used", spent)

    # 3. Alert on-call
    if spent / limit > 0.9:
        pagerduty.trigger("high-llm-spend")

with budget(max_usd=100.00, warn_at=0.8, on_warn=comprehensive_alert):
    run_my_agent()
```

## Handling BudgetExceededError

The exception provides rich debugging information:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.50) as b:
        expensive_operation()
except BudgetExceededError as e:
    # Exception attributes
    print(f"Spent: ${e.spent:.4f}")       # How much was spent
    print(f"Limit: ${e.limit:.2f}")       # The configured limit
    print(f"Model: {e.model}")            # Which model triggered it
    print(f"Tokens: {e.tokens}")          # Last call's token counts

    # Token breakdown
    input_tokens = e.tokens["input"]
    output_tokens = e.tokens["output"]
    print(f"Last call: {input_tokens} in, {output_tokens} out")
```

### Graceful Degradation

Handle budget errors gracefully:

```python
def process_with_budget(items: list, budget_usd: float):
    results = []

    try:
        with budget(max_usd=budget_usd) as b:
            for item in items:
                result = expensive_api_call(item)
                results.append(result)
    except BudgetExceededError as e:
        print(f"Processed {len(results)}/{len(items)} items before budget limit")
        print(f"Spent: ${e.spent:.4f}")

    return results

# Process what we can afford
results = process_with_budget(my_items, budget_usd=5.00)
```

### Retry with Cheaper Model

Catch the error and retry with a different approach:

```python
try:
    with budget(max_usd=1.00):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )
except BudgetExceededError:
    print("Expensive model exceeded budget, trying cheaper alternative")
    with budget(max_usd=0.10):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
```

Automatic Fallback

Instead of manually catching and retrying, consider using [fallback models](https://arieradle.github.io/shekel/1.1.0/usage/fallback-models/index.md) for automatic model switching.

## Budget Guards

Create reusable budget guards for different operations:

```python
class BudgetGuard:
    def __init__(self, operation: str, max_usd: float):
        self.operation = operation
        self.max_usd = max_usd

    def __enter__(self):
        print(f"Starting {self.operation} with ${self.max_usd:.2f} budget")
        self.budget = budget(max_usd=self.max_usd, warn_at=0.8)
        return self.budget.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        result = self.budget.__exit__(exc_type, exc_val, exc_tb)
        if exc_type is None:
            print(f"{self.operation} completed: ${self.budget.spent:.4f}")
        return result

# Usage
with BudgetGuard("user-query", max_usd=0.50) as b:
    handle_user_query()

with BudgetGuard("batch-processing", max_usd=10.00) as b:
    process_batch()
```

## Environment-Based Budgets

Adjust budgets based on environment:

```python
import os

def get_budget_limit() -> float:
    env = os.getenv("ENVIRONMENT", "development")

    budgets = {
        "development": 1.00,
        "staging": 10.00,
        "production": 100.00,
    }

    return budgets.get(env, 1.00)

with budget(max_usd=get_budget_limit()) as b:
    run_my_agent()
```

## Per-User Budgets

Track and enforce per-user spending limits:

```python
user_budgets = {
    "user_123": 5.00,
    "user_456": 10.00,
    "premium_user": 50.00,
}

def process_user_request(user_id: str, request: str):
    user_limit = user_budgets.get(user_id, 1.00)  # Default $1

    try:
        with budget(max_usd=user_limit) as b:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": request}],
            )
            return response.choices[0].message.content
    except BudgetExceededError:
        return "Your query budget has been exceeded. Please upgrade your plan."
```

## Combining with Rate Limiting

Use shekel alongside rate limiting for comprehensive control:

```python
from ratelimit import limits, sleep_and_retry

# Rate limit: 10 calls per minute
@sleep_and_retry
@limits(calls=10, period=60)
def call_llm_with_limits(prompt: str):
    # Budget limit: $1 per call
    with budget(max_usd=1.00):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
```

## Testing Budget Enforcement

Test that your budget limits work correctly:

```python
import pytest
from shekel import budget, BudgetExceededError

def test_budget_enforcement():
    with pytest.raises(BudgetExceededError) as exc_info:
        with budget(max_usd=0.001):  # Very low limit
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "Long prompt..."}],
            )

    assert exc_info.value.spent > 0.001
    assert exc_info.value.limit == 0.001

def test_warning_callback():
    warning_fired = []

    def capture_warning(spent, limit):
        warning_fired.append((spent, limit))

    with budget(max_usd=1.00, warn_at=0.5, on_warn=capture_warning):
        # Make calls that trigger warning
        ...

    assert len(warning_fired) == 1
    assert warning_fired[0][1] == 1.00
```

## Next Steps

- **[Fallback Models](https://arieradle.github.io/shekel/1.1.0/usage/fallback-models/index.md)** - Automatic model switching instead of raising
- **[Accumulating Budgets](https://arieradle.github.io/shekel/1.1.0/usage/accumulating-budgets/index.md)** - Multi-session tracking
- **[API Reference](https://arieradle.github.io/shekel/1.1.0/api-reference/index.md)** - Complete budget() parameters
