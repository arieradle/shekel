# Requires: pip install shekel[openai]
"""
LangGraph demo: budget enforcement with shekel.

Shekel works with LangGraph out of the box — just wrap with budget().
All LLM calls inside graph nodes are automatically tracked.

Shows three patterns:
1. Basic budget enforcement
2. Fallback model when budget threshold is reached
3. Nested budgets for multi-node graphs
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

    client = openai.OpenAI(api_key=api_key)

    class State(TypedDict):
        question: str
        answer: str

    def call_llm(state: State) -> State:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": state["question"]}],
            max_tokens=50,
        )
        return {"question": state["question"], "answer": response.choices[0].message.content}

    graph = StateGraph(State)
    graph.add_node("llm", call_llm)
    graph.set_entry_point("llm")
    graph.add_edge("llm", END)
    app = graph.compile()

    # ------------------------------------------------------------------
    # 1. Basic budget enforcement
    # ------------------------------------------------------------------
    print("=== Basic budget enforcement ===")
    try:
        with budget(max_usd=0.10, name="demo", warn_at=0.8) as b:
            result = app.invoke({"question": "What is 2+2?", "answer": ""})
            print(f"Answer: {result['answer']}")
            print(f"Spent: ${b.spent:.4f} / ${b.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Fallback model when threshold is reached
    # ------------------------------------------------------------------
    print("\n=== Fallback model ===")
    with budget(
        max_usd=0.001,
        name="fallback-demo",
        fallback={"at_pct": 0.5, "model": "gpt-4o-mini"},
    ) as b:
        result = app.invoke({"question": "What is the capital of France?", "answer": ""})
        print(f"Answer: {result['answer']}")
    if b.model_switched:
        print(f"Switched to fallback at ${b.switched_at_usd:.6f}")
    print(f"Total: ${b.spent:.4f}")


if __name__ == "__main__":
    main()
