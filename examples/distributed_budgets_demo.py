# Requires: pip install shekel[openai,redis]
"""
Distributed budgets demo: enforce LLM cost limits across multiple processes.

RedisBackend uses an atomic Lua script (one round-trip) to enforce rolling-window
caps across any number of workers hitting the same Redis instance.

Shows three patterns:
1. Basic distributed enforcement with RedisBackend
2. Multi-cap spec — simultaneous USD + call-count rolling windows
3. Distributed budget + per-node caps (LangGraph)
"""

import os


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

    try:
        import openai
        from shekel.backends.redis import RedisBackend
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install shekel[openai] redis")
        return

    from shekel import BudgetExceededError, budget

    client = openai.OpenAI(api_key=api_key)

    # ------------------------------------------------------------------
    # 1. Basic distributed enforcement
    # ------------------------------------------------------------------
    print("=== Distributed enforcement ===")
    try:
        backend = RedisBackend(redis_url=redis_url)
        with budget(max_usd=5.00, name="shared-pool", backend=backend) as b:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "What is 2+2?"}],
                max_tokens=20,
            )
            print(f"Answer: {resp.choices[0].message.content}")
            print(f"Spent: ${b.spent:.4f} / $5.00")
    except BudgetExceededError as e:
        print(f"Distributed budget exceeded: {e}")
    except Exception as e:
        print(f"Redis unavailable: {e}")
        print("Start Redis with: docker run -p 6379:6379 redis:alpine")
        return

    # ------------------------------------------------------------------
    # 2. Multi-cap rolling-window spec
    # ------------------------------------------------------------------
    print("\n=== Multi-cap: $5/hr + 100 calls/hr ===")
    try:
        backend = RedisBackend(redis_url=redis_url)
        with budget("$5/hr + 100 calls/hr", name="api-tier", backend=backend) as b:
            for i in range(3):
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": f"Question {i+1}: capital of France?"}],
                    max_tokens=10,
                )
                print(f"  [{i+1}] {resp.choices[0].message.content}")
    except BudgetExceededError as e:
        # e.retry_after tells callers when the window resets
        retry = getattr(e, "retry_after", None)
        print(f"Rate limit hit. Retry after: {retry:.1f}s" if retry else f"Limit: {e}")

    # ------------------------------------------------------------------
    # 3. Distributed budget + per-node LangGraph caps
    # ------------------------------------------------------------------
    print("\n=== Distributed + per-node caps ===")
    try:
        from langgraph.graph import END, StateGraph  # type: ignore[import]
        from typing_extensions import TypedDict

        class State(TypedDict):
            query: str
            answer: str

        def answer_node(state: State) -> State:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": state["query"]}],
                max_tokens=40,
            )
            return {**state, "answer": resp.choices[0].message.content or ""}

        graph = StateGraph(State)
        graph.add_node("answer", answer_node)
        graph.set_entry_point("answer")
        graph.add_edge("answer", END)
        app = graph.compile()

        backend = RedisBackend(redis_url=redis_url)
        with budget("$5/hr", name="graph-pool", backend=backend) as b:
            b.node("answer", max_usd=0.10)
            result = app.invoke({"query": "Name a planet.", "answer": ""})
            print(f"Answer: {result['answer']}")

        print(b.tree())

    except ImportError:
        print("langgraph not installed — pip install langgraph")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")


if __name__ == "__main__":
    main()
