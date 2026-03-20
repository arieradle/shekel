# Accumulating Budgets

Budget variables automatically accumulate across multiple uses.

## Overview

When you reuse the same budget variable across multiple `with` blocks, spending automatically accumulates. This is perfect for tracking costs across:

- Multi-turn conversations
- Batch processing jobs
- Per-user daily/monthly limits
- Long-running workflows

## How It Works

All budget variables naturally accumulate:

```python
from shekel import budget

# Create a budget
session = budget(max_usd=5.00, name="session")

# Run 1
with session:
    process_batch_1()
print(f"After batch 1: ${session.spent:.4f}")  # $0.30

# Run 2 - spend accumulates automatically!
with session:
    process_batch_2()
print(f"After batch 2: ${session.spent:.4f}")  # $0.65

# Run 3
with session:
    process_batch_3()
print(f"Total session: ${session.spent:.4f}")  # $1.05
```

Fresh Budget Per Instance

Want a fresh budget? Just create a new instance:

```python
# Each creates a fresh budget
with budget(max_usd=1.00): process_1()  # $0.30
with budget(max_usd=1.00): process_2()  # $0.35 (fresh, not $0.65)
```

## Budgets Always Accumulate

Budget variables always accumulate across multiple uses — reuse the same variable and spend adds up automatically.

## Multi-Turn Conversations

Perfect for chatbots and conversational agents:

```python
user_session = budget(max_usd=2.00, name="user_chat")

def handle_user_message(message: str):
    with user_session:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": message}],
        )
        return response.choices[0].message.content

# User sends multiple messages - costs accumulate
response1 = handle_user_message("Hello!")
print(f"After message 1: ${user_session.spent:.4f}")

response2 = handle_user_message("Tell me about Python")
print(f"After message 2: ${user_session.spent:.4f}")

response3 = handle_user_message("Thanks!")
print(f"Total conversation: ${user_session.spent:.4f}")
```

## Batch Processing

Process data in batches with accumulated spending:

```python
from shekel import budget, BudgetExceededError

def process_all_items(items: list, budget_usd: float):
    session = budget(max_usd=budget_usd, name="batch_job")
    results = []

    # Process in batches of 10
    for i in range(0, len(items), 10):
        batch = items[i:i+10]

        try:
            with session:
                for item in batch:
                    result = process_item(item)
                    results.append(result)

            print(f"Batch {i//10 + 1}: ${session.spent:.4f} spent so far")

        except BudgetExceededError:
            print(f"Budget exhausted after {len(results)} items")
            break

    return results

# Process with $10 budget
results = process_all_items(my_items, budget_usd=10.00)
```

## Per-User Daily Limits

Enforce daily spending limits per user:

```python
from datetime import datetime
from typing import Dict

class UserBudgetManager:
    def __init__(self):
        self.user_budgets: Dict[str, tuple] = {}

    def get_budget(self, user_id: str, daily_limit: float = 5.00):
        today = datetime.now().date()

        if user_id in self.user_budgets:
            budget_obj, budget_date = self.user_budgets[user_id]

            # Reset if it's a new day
            if budget_date != today:
                budget_obj = budget(max_usd=daily_limit, name=f"user_{user_id}")
                self.user_budgets[user_id] = (budget_obj, today)
        else:
            budget_obj = budget(max_usd=daily_limit, name=f"user_{user_id}")
            self.user_budgets[user_id] = (budget_obj, today)

        return budget_obj

# Usage
manager = UserBudgetManager()

def handle_request(user_id: str, prompt: str):
    user_budget = manager.get_budget(user_id, daily_limit=5.00)

    with user_budget:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

# Each user has their own daily budget
handle_request("user_123", "Hello")
handle_request("user_456", "Hi there")
handle_request("user_123", "Another message")  # Accumulates with first
```

## Resetting Budgets

Reset a budget back to zero with `.reset()`:

```python
session = budget(max_usd=10.00, name="session")

# Use it
with session:
    process_batch_1()
print(f"Spent: ${session.spent:.4f}")

# Reset to zero
session.reset()
print(f"After reset: ${session.spent:.4f}")  # $0.0000

# Use again from zero
with session:
    process_batch_2()
```

Reset Safety

You cannot reset a budget while it's active (inside a `with` block). This raises `RuntimeError`:

```python
session = budget(max_usd=10.00, name="session")

with session:
    session.reset()  # ❌ RuntimeError
```

Reset between contexts:

```python
with session:
    process()

session.reset()  # ✅ OK

with session:
    process_again()
```

## Accumulation with Fallback

Combine accumulating budgets with fallback models:

```python
session = budget(
    max_usd=5.00,
    fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
    name="session"
)

# Run 1 - uses gpt-4o
with session:
    response1 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "First"}],
    )

# Run 2 - might switch to gpt-4o-mini if $5 exceeded
with session:
    response2 = client.chat.completions.create(
        model="gpt-4o",  # Automatically becomes gpt-4o-mini if switched
        messages=[{"role": "user", "content": "Second"}],
    )

# Run 3 - definitely using gpt-4o-mini if switched
with session:
    response3 = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Third"}],
    )

if session.model_switched:
    print(f"Switched to fallback at ${session.switched_at_usd:.4f}")
    print(f"Total on fallback: ${session.fallback_spent:.4f}")
```

## Accumulation with Warnings

Get warned once when the threshold is reached:

```python
def warn_user(spent: float, limit: float):
    print(f"⚠️  You've spent ${spent:.2f} of your ${limit:.2f} budget")

session = budget(
    max_usd=10.00,
    warn_at=0.8,
    on_warn=warn_user,
    name="session"
)

# Run 1 - no warning
with session:
    process_small_task()  # Costs $2

# Run 2 - no warning
with session:
    process_small_task()  # Costs $2 (total: $4)

# Run 3 - WARNING! (crosses 80% = $8)
with session:
    process_small_task()  # Costs $5 (total: $9)
    # Prints: ⚠️  You've spent $9.00 of your $10.00 budget
```

The warning fires only once per budget instance, not on every context entry.

## Tracking Session History

Budget variables maintain full call history:

```python
session = budget(max_usd=10.00, name="session")

# Multiple runs
with session:
    call_1()

with session:
    call_2()
    call_3()

with session:
    call_4()

# View complete history
print(session.summary())
```

Output shows all calls across all contexts:

```text
┌─ Shekel Budget Summary ────────────────────────────────────┐
│ Total: $2.3450  Limit: $10.00  Calls: 4  Status: OK
├────────────────────────────────────────────────────────────┤
│  #    Model                        Input  Output      Cost
│  ────────────────────────────────────────────────────────
│  1    gpt-4o-mini                  1,200     300  $0.0003
│  2    gpt-4o-mini                  1,500     450  $0.0004
│  3    gpt-4o-mini                  2,000     500  $0.0005
│  4    gpt-4o                       1,000     250  $0.0048
├────────────────────────────────────────────────────────────┤
│  gpt-4o-mini: 3 calls  $0.0012
│  gpt-4o: 1 calls  $0.0048
└────────────────────────────────────────────────────────────┘
```

## Thread Safety Warning

Thread Safety

Budget objects are **not thread-safe** when shared across threads. Each thread should use its own budget instance.

**Bad** (race conditions):

```python
session = budget(max_usd=10.00, name="session")

def worker():
    with session:  # ❌ Multiple threads sharing
        process()

threads = [Thread(target=worker) for _ in range(10)]
```

**Good** (separate budgets):

```python
def worker(worker_id: int):
    session = budget(max_usd=1.00, name=f"worker_{worker_id}")
    with session:  # ✅ Each thread has its own
        process()

threads = [Thread(target=worker, args=(i,)) for i in range(10)]
```

Within a single thread, budgets are safe with async/await:

```python
async def process_items():
    session = budget(max_usd=10.00, name="session")

    async with session:
        await process_batch_1()

    async with session:
        await process_batch_2()

    print(f"Total: ${session.spent:.4f}")
```

## When to Accumulate

| Use Case         | Accumulate?          | Why                          |
| ---------------- | -------------------- | ---------------------------- |
| Single API call  | No (fresh instance)  | No need for accumulation     |
| One-off task     | No (fresh instance)  | Self-contained operation     |
| Multi-turn chat  | Yes (reuse variable) | Track full conversation cost |
| Batch processing | Yes (reuse variable) | Enforce total batch budget   |
| Per-user limits  | Yes (reuse variable) | Daily/monthly spend tracking |
| Testing          | No (fresh instance)  | Isolated test cases          |
| Long workflows   | Yes (reuse variable) | Multi-step process budget    |

## Complete Example

Here's a complete example combining all features:

```python
from shekel import budget, BudgetExceededError

class ConversationManager:
    def __init__(self, user_id: str, daily_limit: float = 5.00):
        self.user_id = user_id
        self.session = budget(
            max_usd=daily_limit,
            warn_at=0.8,
            fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
            on_warn=self._warn_user,
            on_fallback=self._notify_fallback,
            name=f"user_{user_id}"
        )

    def _warn_user(self, spent: float, limit: float):
        print(f"{self.user_id}: 80% budget used (${spent:.2f}/${limit:.2f})")

    def _notify_fallback(self, spent: float, limit: float, fallback: str):
        print(f"{self.user_id}: Switched to {fallback} at ${spent:.2f}")

    def send_message(self, message: str) -> str:
        try:
            with self.session:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": message}],
                )
                return response.choices[0].message.content
        except BudgetExceededError:
            return "Daily budget exceeded. Please try again tomorrow."

    def get_stats(self):
        return {
            "spent": self.session.spent,
            "limit": self.session.limit,
            "remaining": self.session.remaining,
            "switched": self.session.model_switched,
        }

    def reset_daily(self):
        self.session.reset()

# Usage
user = ConversationManager("user_123", daily_limit=5.00)

print(user.send_message("Hello!"))
print(user.send_message("What's the weather?"))
print(user.send_message("Tell me a joke"))

print(user.get_stats())
```

## Next Steps

- **[Nested Budgets](https://arieradle.github.io/shekel/1.1.0/usage/nested-budgets/index.md)** - Hierarchical budget tracking
- **[Streaming](https://arieradle.github.io/shekel/1.1.0/usage/streaming/index.md)** - Budget tracking for streaming responses
- **[Decorators](https://arieradle.github.io/shekel/1.1.0/usage/decorators/index.md)** - Using @with_budget
- **[API Reference](https://arieradle.github.io/shekel/1.1.0/api-reference/index.md)** - Complete budget parameters
