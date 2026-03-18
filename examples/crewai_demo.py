# Requires: pip install shekel[openai] crewai
"""
CrewAI demo: per-agent and per-task circuit breaking with shekel.

Shekel patches Agent.execute_task transparently — every agent execution
gets a pre-execution budget gate with no crew or agent changes needed.

Shows four patterns:
1. Global cap only — zero config, shekel auto-detects CrewAI
2. Per-agent caps — b.agent(agent.role, max_usd=X)
3. Per-agent + per-task caps — combined enforcement
4. b.tree() — full spend breakdown after execution
"""

import os


def main() -> None:
    try:
        from crewai import Agent, Crew, Task  # type: ignore[import]
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install shekel[openai] crewai")
        return

    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        return

    from shekel import BudgetExceededError, budget
    from shekel.exceptions import AgentBudgetExceededError, TaskBudgetExceededError

    researcher = Agent(
        role="Senior Researcher",
        goal="Find key facts about the topic",
        backstory="Expert researcher with broad knowledge.",
        llm="gpt-4o-mini",
        verbose=False,
    )
    writer = Agent(
        role="Content Writer",
        goal="Summarize research into a clear paragraph",
        backstory="Skilled writer who distills complex ideas.",
        llm="gpt-4o-mini",
        verbose=False,
    )

    research_task = Task(
        name="research",
        description="Research the topic: {topic}",
        expected_output="A bullet list of 3 key facts.",
        agent=researcher,
    )
    write_task = Task(
        name="write",
        description="Write a one-paragraph summary of the research.",
        expected_output="A single paragraph.",
        agent=writer,
    )

    crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task], verbose=False)

    # ------------------------------------------------------------------
    # 1. Global cap only — zero config, shekel auto-detects CrewAI
    # ------------------------------------------------------------------
    print("=== Global cap only ===")
    # No configuration needed — shekel auto-detects CrewAI and enforces the cap
    try:
        with budget(max_usd=5.00, name="global") as b:
            crew.kickoff(inputs={"topic": "climate change"})
        print(f"Done. Spent: ${b.spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Per-agent caps — use agent.role as the key directly
    # ------------------------------------------------------------------
    print("\n=== Per-agent caps ===")
    try:
        with budget(max_usd=5.00, name="agents") as b:
            # Use agent.role directly — eliminates key mismatch risk
            b.agent(researcher.role, max_usd=2.00)
            b.agent(writer.role, max_usd=1.00)
            crew.kickoff(inputs={"topic": "quantum computing"})
        print(f"Done. Spent: ${b.spent:.4f}")
    except AgentBudgetExceededError as e:
        print(f"Agent cap exceeded: {e}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: {e}")

    print(b.tree())
    # agents: $X.XX / $5.00 (direct: $X.XX)
    #   [agent] Senior Researcher: $X.XX / $2.00  (X%)
    #   [agent] Content Writer:    $X.XX / $1.00  (X%)

    # ------------------------------------------------------------------
    # 3. Per-agent + per-task caps
    # ------------------------------------------------------------------
    print("\n=== Per-agent + per-task caps ===")
    try:
        with budget(max_usd=5.00, name="full") as b:
            b.agent(researcher.role, max_usd=2.00)
            b.agent(writer.role, max_usd=1.00)
            # Use task.name directly — eliminates key mismatch risk
            b.task(research_task.name, max_usd=1.50)
            b.task(write_task.name, max_usd=0.80)
            crew.kickoff(inputs={"topic": "renewable energy"})
        print(f"Done. Spent: ${b.spent:.4f}")
    except TaskBudgetExceededError as e:
        print(f"Task cap exceeded: {e}")
    except AgentBudgetExceededError as e:
        print(f"Agent cap exceeded: {e}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 4. b.tree() — full spend breakdown
    # ------------------------------------------------------------------
    print("\n=== Spend breakdown ===")
    print(b.tree())
    # full: $X.XX / $5.00 (direct: $X.XX)
    #   [agent] Senior Researcher: $X.XX / $2.00  (X%)
    #   [agent] Content Writer:    $X.XX / $1.00  (X%)
    #   [task]  research:          $X.XX / $1.50  (X%)
    #   [task]  write:             $X.XX / $0.80  (X%)


if __name__ == "__main__":
    main()
