# Requires: pip install shekel[openai]
"""
Basic OpenAI examples: budget enforcement, fallback, streaming, batch processing.
"""

import os

from shekel import BudgetExceededError, budget


def main() -> None:
    try:
        import openai
    except ImportError:
        print("Run: pip install shekel[openai]")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

    client = openai.OpenAI(api_key=api_key)

    # ------------------------------------------------------------------
    # 1. Basic budget enforcement
    # ------------------------------------------------------------------
    print("=== Basic budget ===")
    try:
        with budget(max_usd=0.10, warn_at=0.8) as b:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say hello in one sentence."}],
            )
            print(response.choices[0].message.content)
        print(f"Spent: ${b.spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Versioned model names resolve automatically
    # ------------------------------------------------------------------
    print("\n=== Versioned model name ===")
    with budget() as b:
        response = client.chat.completions.create(
            # "gpt-4o-2024-08-06" resolves to gpt-4o pricing automatically
            model="gpt-4o-2024-08-06",
            messages=[{"role": "user", "content": "Say hi."}],
            max_tokens=10,
        )
        print(response.choices[0].message.content)
    print(f"Cost (gpt-4o-2024-08-06 → gpt-4o pricing): ${b.spent:.6f}")

    # ------------------------------------------------------------------
    # 3. Fallback to cheaper model
    # ------------------------------------------------------------------
    print("\n=== Fallback model ===")
    with budget(max_usd=0.001, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
        )
        print(response.choices[0].message.content)
    if b.model_switched:
        print(f"Switched to fallback at ${b.switched_at_usd:.4f}")
    print(f"Total: ${b.spent:.4f}")

    # ------------------------------------------------------------------
    # 3. Streaming with budget
    # ------------------------------------------------------------------
    print("\n=== Streaming ===")
    with budget(max_usd=0.10) as b:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Count from 1 to 5."}],
            stream=True,
        )
        for chunk in stream:
            print(chunk.choices[0].delta.content or "", end="", flush=True)
    print(f"\nStreaming cost: ${b.spent:.4f}")

    # ------------------------------------------------------------------
    # 4. Batch processing with early stop
    # ------------------------------------------------------------------
    print("\n=== Batch processing ===")
    items = ["apple", "banana", "cherry", "date", "elderberry"]
    results = []
    try:
        with budget(max_usd=0.05) as b:
            for item in items:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": f"One fun fact about {item}."}],
                    max_tokens=30,
                )
                results.append(response.choices[0].message.content)
    except BudgetExceededError:
        print(f"Budget hit after {len(results)}/{len(items)} items")
    print(f"Batch cost: ${b.spent:.4f}")
    print(b.summary())


if __name__ == "__main__":
    main()
