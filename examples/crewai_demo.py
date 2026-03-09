# Requires: pip install shekel[openai] crewai
"""
CrewAI example: budget enforcement across a multi-agent crew.
"""

import os

from shekel import BudgetExceededError, budget


def main() -> None:
    try:
        from crewai import Agent, Crew, Task  # type: ignore[import]
    except ImportError:
        print("Run: pip install shekel[openai] crewai")
        return

    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        return

    researcher = Agent(
        role="Research Analyst",
        goal="Find key facts about the given topic",
        backstory="You are an expert researcher who finds concise, accurate information.",
        llm="gpt-4o-mini",
        verbose=False,
    )

    writer = Agent(
        role="Content Writer",
        goal="Write a short summary based on research findings",
        backstory="You write clear, engaging summaries.",
        llm="gpt-4o-mini",
        verbose=False,
    )

    research_task = Task(
        description="Research 3 key facts about Python programming language.",
        expected_output="A bullet list of 3 facts.",
        agent=researcher,
    )

    write_task = Task(
        description="Write a 2-sentence summary based on the research.",
        expected_output="A 2-sentence summary.",
        agent=writer,
    )

    crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task], verbose=False)

    # ------------------------------------------------------------------
    # Run crew with budget cap
    # ------------------------------------------------------------------
    print("=== CrewAI with budget ===")

    def on_warn(spent: float, limit: float) -> None:
        print(f"  Warning: ${spent:.4f} of ${limit:.2f} used")

    try:
        with budget(max_usd=0.50, warn_at=0.8, on_exceed=on_warn) as b:
            result = crew.kickoff()
        print(result)
        print(f"\nCrew cost: ${b.spent:.4f}")
        print(b.summary())
    except BudgetExceededError as e:
        print(f"Crew exceeded budget: {e}")


if __name__ == "__main__":
    main()
