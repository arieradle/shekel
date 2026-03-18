# Requires: pip install shekel[openai] langchain langchain-openai
"""
LangChain demo: per-chain circuit breaking with shekel.

Shekel patches Runnable._call_with_config and RunnableSequence.invoke
transparently — every chain gets a pre-execution budget gate with no
chain changes needed.

Shows three patterns:
1. Per-chain USD caps — ChainBudgetExceededError before the chain runs
2. Nested budgets with chain caps — tree() shows spend breakdown
3. Combining node caps (LangGraph) and chain caps (LangChain)
"""

import os


def main() -> None:
    try:
        from langchain_core.output_parsers import StrOutputParser  # type: ignore[import]
        from langchain_core.prompts import ChatPromptTemplate  # type: ignore[import]
        from langchain_openai import ChatOpenAI  # type: ignore[import]
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install shekel[openai] langchain langchain-openai")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

    from shekel import BudgetExceededError, budget
    from shekel.providers.langchain import ChainBudgetExceededError  # type: ignore[import]

    llm = ChatOpenAI(model="gpt-4o-mini", api_key=api_key, max_tokens=80)

    retriever_prompt = ChatPromptTemplate.from_template("Find facts about: {topic}")
    summarizer_prompt = ChatPromptTemplate.from_template("Summarize in one sentence: {text}")

    retriever_chain = retriever_prompt | llm | StrOutputParser()
    summarizer_chain = summarizer_prompt | llm | StrOutputParser()

    # ------------------------------------------------------------------
    # 1. Per-chain USD caps
    # ------------------------------------------------------------------
    print("=== Per-chain caps ===")
    try:
        with budget(max_usd=5.00, name="pipeline") as b:
            b.chain("retriever", max_usd=0.20)
            b.chain("summarizer", max_usd=1.00)

            facts = retriever_chain.invoke({"topic": "climate change"})
            summary = summarizer_chain.invoke({"text": facts})
            print(f"Summary: {summary}")
    except (BudgetExceededError, ChainBudgetExceededError) as e:
        print(f"Budget exceeded: {e}")

    print(b.tree())
    # pipeline: $X.XX / $5.00
    #   [chain] retriever:  $X.XX / $0.20  (X%)
    #   [chain] summarizer: $X.XX / $1.00  (X%)

    # ------------------------------------------------------------------
    # 2. Chain cap exceeded — ChainBudgetExceededError
    # ------------------------------------------------------------------
    print("\n=== Chain cap exceeded ===")
    try:
        with budget(max_usd=5.00, name="tight") as b:
            b.chain("retriever", max_usd=0.00001)  # intentionally tiny
            retriever_chain.invoke({"topic": "AI"})
    except ChainBudgetExceededError as e:
        print(f"Chain '{e.chain_name}' exceeded: ${e.spent:.6f} > ${e.limit:.6f}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 3. Nested budgets — per-stage isolation
    # ------------------------------------------------------------------
    print("\n=== Nested per-stage budgets ===")
    workflow = budget(max_usd=10.00, name="workflow")
    try:
        with workflow:
            with budget(max_usd=2.00, name="research"):
                facts = retriever_chain.invoke({"topic": "quantum computing"})

            with budget(max_usd=3.00, name="writing"):
                summary = summarizer_chain.invoke({"text": facts})

            print(f"Result: {summary}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    print(workflow.tree())
    # workflow: $X.XX / $10.00
    #   research: $X.XX / $2.00
    #   writing:  $X.XX / $3.00


if __name__ == "__main__":
    main()
