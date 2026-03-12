# Requires: pip install shekel[gemini]
"""
Gemini demo: budget enforcement with shekel + google-genai SDK.

Shekel patches google.genai.models.Models at runtime so every
client.models.generate_content() and generate_content_stream() call
is automatically tracked inside an active budget().

Shows three patterns:
1. Basic generate_content with budget tracking
2. Streaming with token accumulation
3. Fallback to a cheaper Gemini model at a spend threshold
"""

import os


def main() -> None:
    try:
        import google.genai as genai
    except ImportError:
        print("Missing dependency: google-genai")
        print("Run: pip install shekel[gemini]")
        return

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY to run this demo.")
        return

    from shekel import BudgetExceededError, budget

    client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # 1. Basic budget enforcement
    # ------------------------------------------------------------------
    print("=== Basic budget enforcement ===")
    try:
        with budget(max_usd=0.10, name="demo", warn_at=0.8) as b:
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents="What is 2+2? Answer in one word.",
            )
            text = response.candidates[0].content.parts[0].text
            print(f"Answer: {text.strip()}")
            print(f"Spent: ${b.spent:.6f} / ${b.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Streaming with token accumulation
    # ------------------------------------------------------------------
    print("\n=== Streaming ===")
    try:
        with budget(max_usd=0.10, name="streaming") as b:
            full_text = ""
            for chunk in client.models.generate_content_stream(
                model="gemini-2.0-flash-lite",
                contents="Count from 1 to 5, one number per line.",
            ):
                if chunk.candidates:
                    for part in chunk.candidates[0].content.parts:
                        full_text += part.text
            print(f"Response: {full_text.strip()}")
            print(f"Spent: ${b.spent:.6f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 3. Fallback model when threshold is reached
    # ------------------------------------------------------------------
    print("\n=== Fallback model ===")
    with budget(
        max_usd=0.0001,
        name="fallback-demo",
        fallback={"at_pct": 0.5, "model": "gemini-2.0-flash-lite"},
    ) as b:
        try:
            client.models.generate_content(
                model="gemini-2.0-flash",
                contents="What is the capital of France?",
            )
        except BudgetExceededError:
            pass
    if b.model_switched:
        print(f"Switched to fallback at ${b.switched_at_usd:.8f}")
    print(f"Total: ${b.spent:.6f}")


if __name__ == "__main__":
    main()
