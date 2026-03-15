# Requires: pip install shekel[openai]
"""
Temporal budget example: rolling-window LLM spend limits.

Shows three patterns:
1. Basic $5/hr window — hard stop with retry_after
2. Multiple windows — different limits per tier
3. Custom backend — bring your own state store
"""

import asyncio
import os

from shekel import BudgetExceededError, budget

# ---------------------------------------------------------------------------
# Pattern 1: Basic rolling-window budget
# ---------------------------------------------------------------------------


async def basic_window_demo(client) -> None:
    print("=== Pattern 1: Basic $0.01/hr rolling window ===\n")

    # budget("$0.01/hr") parses the string and creates a TemporalBudget
    # The same object is reused across requests — window state persists
    api_budget = budget("$0.01/hr", name="demo-tier")

    questions = [
        "What is a rolling window budget?",
        "Why are hard cost caps useful for AI agents?",
        "What is the difference between a budget and a rate limiter?",
    ]

    for i, question in enumerate(questions, 1):
        try:
            async with api_budget:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": question}],
                    max_tokens=40,
                )
            print(f"Q{i}: {question}")
            print(f"A{i}: {response.choices[0].message.content}")
            print()
        except BudgetExceededError as e:
            print(f"Q{i}: {question}")
            if e.retry_after is not None:
                print(
                    f"     Window limit hit — retry in {e.retry_after:.0f}s "
                    f"(window spent: ${e.window_spent:.4f})"
                )
            else:
                print(f"     Budget exceeded: ${e.spent:.4f} > ${e.limit:.4f}")
            print()


# ---------------------------------------------------------------------------
# Pattern 2: Tiered limits — different budgets per user tier
# ---------------------------------------------------------------------------


async def tiered_limits_demo(client) -> None:
    print("=== Pattern 2: Tiered spend limits ===\n")

    # Different window budgets for different service tiers
    free_tier = budget("$0.005/hr", name="free")
    pro_tier = budget("$0.05/hr", name="pro")

    async def serve_request(tier_budget, tier_name: str, prompt: str) -> None:
        try:
            async with tier_budget:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=30,
                )
            print(f"  [{tier_name}] {response.choices[0].message.content}")
        except BudgetExceededError as e:
            retry = f"retry in {e.retry_after:.0f}s" if e.retry_after else "no retry info"
            print(f"  [{tier_name}] Window exceeded (${e.window_spent:.4f} spent) — {retry}")

    prompt = "Give one interesting fact about Python in one sentence."

    print("Request 1:")
    await serve_request(free_tier, "free", prompt)
    await serve_request(pro_tier, "pro", prompt)

    print("\nRequest 2:")
    await serve_request(free_tier, "free", prompt)
    await serve_request(pro_tier, "pro", prompt)

    print()


# ---------------------------------------------------------------------------
# Pattern 3: Custom backend (in-memory, keyed by user ID)
# ---------------------------------------------------------------------------


async def custom_backend_demo(client) -> None:
    print("=== Pattern 3: Per-user budget with custom backend ===\n")

    from shekel._temporal import InMemoryBackend, TemporalBudget

    # Shared backend instance — all users' windows tracked in one place
    shared_backend = InMemoryBackend()

    def get_user_budget(user_id: str) -> TemporalBudget:
        """Create a $0.01/hr budget for a specific user, backed by shared state."""
        return TemporalBudget(
            max_usd=0.01,
            window_seconds=3600,
            name=f"user:{user_id}",
            backend=shared_backend,
        )

    users = ["alice", "bob", "alice"]  # alice makes two requests

    for user_id in users:
        user_budget = get_user_budget(user_id)
        try:
            async with user_budget:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "Say hi in one word."}],
                    max_tokens=5,
                )
            spent, _ = shared_backend.get_state(f"user:{user_id}")
            print(
                f"  user={user_id}: "
                f"{response.choices[0].message.content!r}  "
                f"(window total: ${spent:.4f})"
            )
        except BudgetExceededError as e:
            print(
                f"  user={user_id}: window exceeded — "
                f"${e.window_spent:.4f} spent, retry in {e.retry_after:.0f}s"
            )

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    try:
        import openai
    except ImportError:
        print("Run: pip install shekel[openai]")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

    client = openai.AsyncOpenAI(api_key=api_key)

    await basic_window_demo(client)
    await tiered_limits_demo(client)
    await custom_backend_demo(client)


if __name__ == "__main__":
    asyncio.run(main())
