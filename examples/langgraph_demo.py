# Requires: pip install shekel[openai] langgraph typing_extensions
"""
LangGraph demo: per-node circuit breaking with shekel.

Shekel patches StateGraph.add_node() transparently — every node gets a
pre-execution budget gate with no graph changes needed.

Shows three patterns:
1. Per-node USD caps — NodeBudgetExceededError before the node runs
2. Global + per-node caps together — tree() shows spend breakdown
3. Distributed enforcement with RedisBackend (optional)
"""

import os


def main() -> None:
    try:
        import openai
        from langgraph.graph import END, StateGraph  # type: ignore[import]
        from typing_extensions import TypedDict
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install shekel[openai] langgraph typing_extensions")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

    from shekel import BudgetExceededError, budget
    from shekel.providers.langgraph import NodeBudgetExceededError  # type: ignore[import]

    client = openai.OpenAI(api_key=api_key)

    class State(TypedDict):
        query: str
        data: str
        summary: str

    def fetch_data(state: State) -> State:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Find facts about: {state['query']}"}],
            max_tokens=100,
        )
        return {**state, "data": resp.choices[0].message.content or ""}

    def summarize(state: State) -> State:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Summarize: {state['data']}"}],
            max_tokens=60,
        )
        return {**state, "summary": resp.choices[0].message.content or ""}

    graph = StateGraph(State)
    graph.add_node("fetch_data", fetch_data)
    graph.add_node("summarize", summarize)
    graph.set_entry_point("fetch_data")
    graph.add_edge("fetch_data", "summarize")
    graph.add_edge("summarize", END)
    app = graph.compile()

    # ------------------------------------------------------------------
    # 1. Per-node USD caps with global budget
    # ------------------------------------------------------------------
    print("=== Per-node caps ===")
    try:
        with budget(max_usd=5.00, name="pipeline") as b:
            b.node("fetch_data", max_usd=0.50)
            b.node("summarize", max_usd=1.00)

            result = app.invoke({"query": "climate change", "data": "", "summary": ""})
            print(f"Summary: {result['summary']}")
    except (BudgetExceededError, NodeBudgetExceededError) as e:
        print(f"Budget exceeded: {e}")

    print(b.tree())
    # pipeline: $X.XX / $5.00
    #   [node] fetch_data: $X.XX / $0.50  (X%)
    #   [node] summarize:  $X.XX / $1.00  (X%)

    # ------------------------------------------------------------------
    # 2. Per-node cap exceeded — NodeBudgetExceededError
    # ------------------------------------------------------------------
    print("\n=== Node cap exceeded ===")
    try:
        with budget(max_usd=5.00, name="tight") as b:
            b.node("fetch_data", max_usd=0.0001)  # intentionally tiny cap
            app.invoke({"query": "AI trends", "data": "", "summary": ""})
    except NodeBudgetExceededError as e:
        print(f"Node '{e.node_name}' exceeded: ${e.spent:.6f} > ${e.limit:.6f}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 3. Distributed enforcement (Redis — optional)
    # ------------------------------------------------------------------
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        print("\n=== Distributed budget (Redis) ===")
        try:
            from shekel.backends.redis import RedisBackend

            backend = RedisBackend()
            with budget("$5/hr + 100 calls/hr", name="distributed-pipeline", backend=backend) as b:
                b.node("fetch_data", max_usd=0.50)
                b.node("summarize", max_usd=1.00)
                result = app.invoke({"query": "quantum computing", "data": "", "summary": ""})
                print(f"Summary: {result['summary']}")
            print(b.tree())
        except ImportError:
            print("redis package not installed — pip install shekel[redis]")
        except Exception as e:
            print(f"Redis error: {e}")
    else:
        print("\n(Set REDIS_URL to demo distributed enforcement)")


if __name__ == "__main__":
    main()
