# Requires: pip install shekel[anthropic]
"""
Basic Anthropic examples: budget enforcement, fallback, streaming.
"""

import os

from shekel import BudgetExceededError, budget


def main() -> None:
    try:
        import anthropic
    except ImportError:
        print("Run: pip install shekel[anthropic]")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY to run this demo.")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # 1. Basic budget enforcement
    # ------------------------------------------------------------------
    print("=== Basic budget ===")
    try:
        with budget(max_usd=0.10, warn_at=0.8) as b:
            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=100,
                messages=[{"role": "user", "content": "Say hello in one sentence."}],
            )
            print(message.content[0].text)
        print(f"Spent: ${b.spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Fallback to cheaper model
    # ------------------------------------------------------------------
    print("\n=== Fallback model ===")
    with budget(max_usd=0.001, fallback={"at_pct": 0.8, "model": "claude-3-haiku-20240307"}) as b:
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=50,
            messages=[{"role": "user", "content": "What is the capital of France?"}],
        )
        print(message.content[0].text)
    if b.model_switched:
        print(f"Switched to fallback at ${b.switched_at_usd:.4f}")
    print(f"Total: ${b.spent:.4f}")

    # ------------------------------------------------------------------
    # 3. Streaming with budget
    # ------------------------------------------------------------------
    print("\n=== Streaming ===")
    with budget(max_usd=0.10) as b:
        with client.messages.stream(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": "Count from 1 to 5."}],
        ) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
    print(f"\nStreaming cost: ${b.spent:.4f}")

    # ------------------------------------------------------------------
    # 4. Track-only mode — profile without enforcing
    # ------------------------------------------------------------------
    print("\n=== Track-only ===")
    with budget() as b:
        client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=50,
            messages=[{"role": "user", "content": "What is 2+2?"}],
        )
    print(f"That call cost: ${b.spent:.4f}")
    print(b.summary())


if __name__ == "__main__":
    main()
