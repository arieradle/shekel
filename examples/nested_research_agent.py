"""
Nested Budgets Example: AI Research Assistant

This example demonstrates hierarchical budget tracking for a multi-stage
AI workflow. Each stage has its own budget, and costs automatically
propagate up to parent budgets.

Run with: python examples/nested_research_agent.py
"""

from shekel import budget


def search_papers(topic: str) -> list[str]:
    """Simulate searching for academic papers (uses LLM for query expansion)."""
    print(f"  🔍 Searching for papers on: {topic}")
    # In real code: call OpenAI to expand search queries
    # client.chat.completions.create(...)
    return ["paper1.pdf", "paper2.pdf", "paper3.pdf"]


def summarize_papers(papers: list[str]) -> list[str]:
    """Summarize each paper using LLM."""
    print(f"  📄 Summarizing {len(papers)} papers...")
    # In real code: call OpenAI to summarize each paper
    # client.chat.completions.create(...)
    return ["summary1", "summary2", "summary3"]


def analyze_summaries(summaries: list[str]) -> dict:
    """Extract key insights from summaries."""
    print(f"  🧠 Analyzing {len(summaries)} summaries...")
    # In real code: call OpenAI for analysis
    # client.chat.completions.create(...)
    return {"key_themes": ["theme1", "theme2"], "recommendations": ["rec1", "rec2"]}


def generate_report(insights: dict) -> str:
    """Generate research report from insights."""
    print("  📝 Generating research report...")
    # In real code: call OpenAI to draft report
    # client.chat.completions.create(...)
    return "Research Report: ..."


def polish_report(draft: str) -> str:
    """Polish and finalize the report."""
    print("  ✨ Polishing final report...")
    # In real code: call OpenAI for editing
    # client.chat.completions.create(...)
    return draft + " [POLISHED]"


def research_agent(topic: str, max_budget: float = 10.0):
    """
    AI Research Assistant with hierarchical budget tracking.

    Budget breakdown:
    - Search phase: $2.00 (20%)
    - Analysis phase: $5.00 (50%)
    - Report phase: $3.00 (30%)
    """
    print("\n🤖 Starting AI Research Agent")
    print(f"📊 Topic: {topic}")
    print(f"💰 Total Budget: ${max_budget:.2f}\n")

    with budget(max_usd=max_budget, name="research_agent") as agent:
        # Phase 1: Search ($2 budget)
        print("Phase 1: Search")
        with budget(max_usd=2.00, name="search") as search:
            papers = search_papers(topic)
            # Simulate spending
            search._spent = 0.85
            search._spent_direct = 0.85

        print(f"  ✅ Search complete: ${search.spent:.2f} spent\n")

        # Phase 2: Analysis ($5 budget)
        print("Phase 2: Analysis")
        with budget(max_usd=5.00, name="analysis") as analysis:
            summaries = summarize_papers(papers)
            # Simulate spending
            analysis._spent = 1.20
            analysis._spent_direct = 1.20

            insights = analyze_summaries(summaries)
            # Simulate more spending
            analysis._spent += 2.30
            analysis._spent_direct += 2.30

        print(f"  ✅ Analysis complete: ${analysis.spent:.2f} spent\n")

        # Phase 3: Report Generation ($3 budget)
        print("Phase 3: Report Generation")
        with budget(max_usd=3.00, name="report_generation") as report:
            draft = generate_report(insights)
            # Simulate spending
            report._spent = 1.80
            report._spent_direct = 1.80

        print(f"  ✅ Report generation complete: ${report.spent:.2f} spent\n")

        # Final polish (uses parent budget)
        print("Phase 4: Final Polish (parent budget)")
        final = polish_report(draft)
        # Simulate parent spending
        agent._spent += 0.45
        agent._spent_direct += 0.45

        print("  ✅ Polish complete: $0.45 spent\n")

    # Print final cost breakdown
    print("=" * 60)
    print("💰 FINAL COST BREAKDOWN")
    print("=" * 60)
    print(f"Total spent: ${agent.spent:.2f} / ${max_budget:.2f}")
    print(f"Direct spend (polish): ${agent.spent_direct:.2f}")
    print(f"Child spend: ${agent.spent_by_children:.2f}")
    print(f"Budget remaining: ${agent.remaining:.2f}")
    print("\nBudget Tree:")
    print(agent.tree())
    print("=" * 60)

    return final


if __name__ == "__main__":
    # Example 1: Successful run within budget
    print("\n" + "=" * 60)
    print("EXAMPLE 1: Normal Execution")
    print("=" * 60)
    report = research_agent("AI safety alignment", max_budget=10.0)

    # Example 2: Tight budget (demonstrates auto-capping)
    print("\n\n" + "=" * 60)
    print("EXAMPLE 2: Tight Budget (Auto-Capping)")
    print("=" * 60)
    print("Note: With only $5 budget, later stages will be auto-capped!\n")

    with budget(max_usd=5.00, name="tight_workflow") as workflow:
        # First stage uses $3
        with budget(max_usd=3.00, name="stage1") as s1:
            s1._spent = 3.00
            s1._spent_direct = 3.00
            print(f"Stage 1 spent: ${s1.spent:.2f}")

        # Second stage wants $5, but only $2 left
        # It will be auto-capped to $2!
        with budget(max_usd=5.00, name="stage2") as s2:
            print("Stage 2 requested: $5.00")
            print(f"Stage 2 actual limit: ${s2.limit:.2f} (auto-capped!)")
            s2._spent = 1.50  # Can't exceed $2
            s2._spent_direct = 1.50

    print(f"\nTotal workflow spent: ${workflow.spent:.2f}")
    print("Workflow tree:")
    print(workflow.tree())
