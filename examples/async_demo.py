# Requires: pip install shekel[openai]
"""
Async example: concurrent agents and nested async budgets.

Shows two patterns:
1. Concurrent agents — each task gets its own isolated budget via ContextVar
2. Nested async budgets — async with budget() nesting works identically to sync
"""

import asyncio
import os

from shekel import BudgetExceededError, budget


async def run_agent(name: str, task: str, max_usd: float) -> dict:
    try:
        import openai
    except ImportError:
        raise RuntimeError("Run: pip install shekel[openai]")

    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        async with budget(max_usd=max_usd) as b:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": task}],
                max_tokens=60,
            )
        result = response.choices[0].message.content
        return {"name": name, "result": result, "spent": b.spent, "ok": True}
    except BudgetExceededError as e:
        return {"name": name, "result": None, "spent": e.spent, "ok": False}


async def nested_async_example() -> None:
    try:
        import openai
    except ImportError:
        raise RuntimeError("Run: pip install shekel[openai]")

    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    print("=== Nested async budgets ===\n")

    async with budget(max_usd=1.00, name="pipeline") as total:
        async with budget(max_usd=0.05, name="step-1") as step1:
            await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "One word: sky colour?"}],
                max_tokens=5,
            )

        async with budget(max_usd=0.05, name="step-2") as step2:
            await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "One word: grass colour?"}],
                max_tokens=5,
            )

    print(f"step-1: ${step1.spent:.6f}")
    print(f"step-2: ${step2.spent:.6f}")
    print(f"total:  ${total.spent:.6f}  (= step-1 + step-2)")


async def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        return

    print("=== Concurrent agents with isolated budgets ===\n")

    # Run three agents concurrently — each has its own budget, fully isolated
    agents = await asyncio.gather(
        run_agent("researcher", "Give one key fact about transformers in ML.", max_usd=0.05),
        run_agent("writer", "Write one sentence about the future of AI.", max_usd=0.05),
        run_agent("reviewer", "Give one tip for writing clean Python code.", max_usd=0.05),
    )

    total = 0.0
    for agent in agents:
        status = "OK" if agent["ok"] else "BUDGET HIT"
        print(f"[{agent['name']}] ${agent['spent']:.4f} — {status}")
        if agent["result"]:
            print(f"  {agent['result']}")
        total += agent["spent"]

    print(f"\nCombined spend: ${total:.4f}")

    print()
    await nested_async_example()


if __name__ == "__main__":
    asyncio.run(main())
