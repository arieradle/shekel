# Requires: pip install shekel[openai]
"""
Persistent / session budget example.

Shows how to accumulate spend across multiple with-blocks —
useful for multi-turn conversations, user session caps, or
multi-step pipelines with a single total budget.
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
    # Multi-turn conversation with a total session budget
    # ------------------------------------------------------------------
    print("=== Multi-turn session budget ===")

    session = budget(max_usd=0.20, persistent=True, warn_at=0.8)
    messages = [{"role": "system", "content": "You are a helpful assistant. Be concise."}]

    questions = [
        "What is machine learning?",
        "What is deep learning?",
        "What is a neural network?",
    ]

    try:
        for question in questions:
            messages.append({"role": "user", "content": question})
            with session:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=60,
                )
            answer = response.choices[0].message.content
            messages.append({"role": "assistant", "content": answer})
            print(f"Q: {question}")
            print(f"A: {answer}")
            print(f"   [session total: ${session.spent:.4f}]")
            print()
    except BudgetExceededError as e:
        print(f"Session budget exceeded: {e}")

    print(session.summary())

    # ------------------------------------------------------------------
    # Multi-step pipeline with shared budget
    # ------------------------------------------------------------------
    print("\n=== Multi-step pipeline ===")

    pipeline_budget = budget(max_usd=0.30, persistent=True)

    def step(name: str, prompt: str) -> str:
        with pipeline_budget:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
            )
        result = response.choices[0].message.content or ""
        print(f"  {name}: ${pipeline_budget.spent:.4f} total spent")
        return result

    try:
        outline = step("outline", "List 3 topics for a blog post about AI in one sentence each.")
        draft = step("draft", f"Write one sentence expanding on: {outline[:100]}")
        review = step("review", f"Improve this sentence in one sentence: {draft[:100]}")
        print(f"\nFinal: {review}")
        print(pipeline_budget.summary())
    except BudgetExceededError as e:
        print(f"Pipeline exceeded budget: {e}")


if __name__ == "__main__":
    main()
