# Requires: pip install shekel[openai] "langgraph>=0.2"
"""
Minimal LangGraph demo showing shekel budget enforcement.

This example builds a simple one-node LangGraph that calls OpenAI,
wrapped in a shekel budget context to track and cap spend.
"""

import os

from shekel import BudgetExceededError, budget


def main() -> None:
    try:
        import openai
        from langgraph.graph import END, StateGraph  # type: ignore[import]
        from typing_extensions import TypedDict
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install shekel[openai] 'langgraph>=0.2' typing_extensions")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

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

    try:
        with budget(max_usd=0.10, warn_at=0.8) as b:
            result = app.invoke({"question": "What is 2+2?", "answer": ""})
            print(f"Answer: {result['answer']}")
            print(f"Spent: ${b.spent:.4f} / ${b.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")


if __name__ == "__main__":
    main()
