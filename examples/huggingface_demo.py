# Requires: pip install shekel[huggingface]
"""
HuggingFace InferenceClient demo: budget enforcement with shekel.

Shekel patches both InferenceClient.chat_completion and
AsyncInferenceClient.chat_completion at runtime so every call —
sync or async — is automatically tracked inside an active budget().

Note: HuggingFace has no standard pricing table. Always pass
price_per_1k_tokens={'input': X, 'output': Y} to budget() so Shekel
knows the cost per token for the model you're using.

Shows four patterns:
1. Basic chat completion with budget tracking
2. Streaming response with token tracking
3. BudgetExceededError handling to cap runaway costs
4. Async chat completion with async budget
"""

import asyncio
import os

_MODEL = "meta-llama/Llama-3.2-1B-Instruct"


def main() -> None:
    try:
        from huggingface_hub import InferenceClient
    except ImportError:
        print("Missing dependency: huggingface-hub")
        print("Run: pip install shekel[huggingface]")
        return

    api_key = os.environ.get("HUGGING_FACE_API")
    if not api_key:
        print("Set HUGGING_FACE_API to run this demo.")
        return

    from shekel import BudgetExceededError, budget

    client = InferenceClient(token=api_key)

    # Custom pricing — required for HuggingFace (no bundled price table)
    pricing = {"input": 0.001, "output": 0.001}  # $0.001 per 1k tokens

    # ------------------------------------------------------------------
    # 1. Basic budget enforcement
    # ------------------------------------------------------------------
    print("=== Basic budget enforcement ===")
    try:
        with budget(max_usd=0.10, name="demo", price_per_1k_tokens=pricing) as b:
            response = client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": "What is 2+2? Answer in one word."}],
                max_tokens=10,
            )
            text = response.choices[0].message.content
            print(f"Answer: {text.strip()}")
            print(f"Spent: ${b.spent:.6f} / ${b.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Streaming with token tracking
    # ------------------------------------------------------------------
    print("\n=== Streaming ===")
    try:
        with budget(max_usd=0.10, name="streaming", price_per_1k_tokens=pricing) as b:
            full_text = ""
            for chunk in client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": "Count from 1 to 3."}],
                max_tokens=20,
                stream=True,
            ):
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text += delta
            print(f"Response: {full_text.strip()}")
            print(f"Spent: ${b.spent:.6f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 3. BudgetExceededError stops runaway calls
    # ------------------------------------------------------------------
    print("\n=== Budget cap ===")
    try:
        with budget(
            max_usd=0.000001,
            name="cap-demo",
            price_per_1k_tokens={"input": 100.0, "output": 100.0},
        ):
            client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": "Hello."}],
                max_tokens=5,
            )
    except BudgetExceededError as e:
        print(f"Caught BudgetExceededError at ${e.spent:.8f} — call stopped cleanly.")

    # ------------------------------------------------------------------
    # 4. Async chat completion with async budget
    # ------------------------------------------------------------------
    asyncio.run(_async_demo(api_key, pricing))


async def _async_demo(api_key: str, pricing: dict[str, float]) -> None:
    from huggingface_hub import AsyncInferenceClient

    from shekel import budget

    client = AsyncInferenceClient(token=api_key)

    print("\n=== Async chat completion ===")
    async with budget(max_usd=0.10, name="async-demo", price_per_1k_tokens=pricing) as b:
        response = await client.chat_completion(
            model=_MODEL,
            messages=[{"role": "user", "content": "What is 2+2? Answer in one word."}],
            max_tokens=10,
        )
        text = response.choices[0].message.content or ""
        print(f"Answer: {text.strip()}")
        print(f"Spent: ${b.spent:.6f}")


if __name__ == "__main__":
    main()
