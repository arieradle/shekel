# Requires: pip install shekel[litellm]
"""
LiteLLM examples: basic tracking, multi-provider, streaming, fallback, async.

LiteLLM routes to 100+ providers (OpenAI, Anthropic, Gemini, Cohere, Ollama,
Azure, Bedrock, Mistral, …) through a unified OpenAI-compatible interface.
Shekel's LiteLLMAdapter patches litellm.completion and litellm.acompletion,
so every call is tracked automatically — no matter which provider is used.
"""

import asyncio
import os

from shekel import BudgetExceededError, budget


def main() -> None:
    try:
        import litellm
    except ImportError:
        print("Run: pip install shekel[litellm]")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY (or the key for your chosen provider) to run this demo.")
        return

    # ------------------------------------------------------------------
    # 1. Basic budget tracking
    # ------------------------------------------------------------------
    print("=== Basic budget ===")
    try:
        with budget(max_usd=0.10, warn_at=0.8) as b:
            response = litellm.completion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say hello in one sentence."}],
            )
            print(response.choices[0].message.content)
        print(f"Spent: ${b.spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Multi-provider: route to different backends in one budget
    # ------------------------------------------------------------------
    print("\n=== Multi-provider under one budget ===")
    with budget(max_usd=1.00, name="multi-provider") as b:
        # OpenAI
        r1 = litellm.completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Name a color."}],
            max_tokens=5,
        )
        print(f"OpenAI:    {r1.choices[0].message.content.strip()}")

        # Anthropic — set ANTHROPIC_API_KEY to run this leg
        if os.environ.get("ANTHROPIC_API_KEY"):
            r2 = litellm.completion(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "Name a fruit."}],
                max_tokens=5,
            )
            print(f"Anthropic: {r2.choices[0].message.content.strip()}")

    print(f"Combined cost: ${b.spent:.4f}")
    print(b.summary())

    # ------------------------------------------------------------------
    # 3. Streaming
    # ------------------------------------------------------------------
    print("\n=== Streaming ===")
    with budget(max_usd=0.10) as b:
        stream = litellm.completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Count from 1 to 5."}],
            stream=True,
        )
        for chunk in stream:
            print(chunk.choices[0].delta.content or "", end="", flush=True)
    print(f"\nStreaming cost: ${b.spent:.4f}")

    # ------------------------------------------------------------------
    # 4. Fallback to cheaper model
    # ------------------------------------------------------------------
    print("\n=== Fallback model ===")
    with budget(max_usd=0.001, fallback={"at_pct": 0.5, "model": "gpt-4o-mini"}) as b:
        response = litellm.completion(
            model="gpt-4o",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            max_tokens=20,
        )
        print(response.choices[0].message.content)
    if b.model_switched:
        print(f"Switched to fallback at ${b.switched_at_usd:.6f}")
    print(f"Total: ${b.spent:.4f}")

    # ------------------------------------------------------------------
    # 5. Call-count limit (useful for rate-limit-aware agents)
    # ------------------------------------------------------------------
    print("\n=== Call-count limit ===")
    questions = ["What is 1+1?", "What is 2+2?", "What is 3+3?", "What is 4+4?"]
    answered = []
    try:
        with budget(max_llm_calls=2) as b:
            for q in questions:
                r = litellm.completion(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": q}],
                    max_tokens=5,
                )
                answered.append(r.choices[0].message.content.strip())
    except BudgetExceededError:
        pass
    print(f"Answered {len(answered)}/{len(questions)} questions (limit: 2 calls)")

    # ------------------------------------------------------------------
    # 6. Async usage
    # ------------------------------------------------------------------
    print("\n=== Async ===")

    async def async_example() -> None:
        async with budget(max_usd=0.10) as b:
            response = await litellm.acompletion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "What is Python in one sentence?"}],
                max_tokens=30,
            )
            print(response.choices[0].message.content)
        print(f"Async cost: ${b.spent:.4f}")

    asyncio.run(async_example())


if __name__ == "__main__":
    main()
