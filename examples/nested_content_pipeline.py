"""
Real-World Example: Multi-Stage Content Generation Pipeline

This example uses actual OpenAI API calls to demonstrate nested budgets
in a realistic content generation workflow.

Requirements:
- pip install shekel[openai]
- export OPENAI_API_KEY=your-key-here

Run with: python examples/nested_content_pipeline.py
"""

import os

from shekel import BudgetExceededError, budget


def main():
    """Content generation pipeline with nested budget tracking."""

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Please set OPENAI_API_KEY environment variable")
        return

    import openai

    client = openai.OpenAI()

    print("🚀 Multi-Stage Content Generation Pipeline")
    print("=" * 60)

    # Main workflow budget: $0.50
    with budget(max_usd=0.50, name="content_pipeline") as pipeline:
        # Stage 1: Research ($0.15 budget)
        print("\n📚 Stage 1: Research")
        print("-" * 60)
        with budget(max_usd=0.15, name="research") as research:
            topic = "benefits of nested budgets for LLM cost control"

            print(f"Researching: {topic}")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"List 3 key benefits of {topic}. Be concise.",
                    }
                ],
                max_tokens=150,
            )

            key_points = response.choices[0].message.content
            print(f"✅ Research complete: ${research.spent:.4f}")
            print(f"   Remaining: ${research.remaining:.4f}")

        # Stage 2: Outline ($0.10 budget)
        print("\n📝 Stage 2: Outline")
        print("-" * 60)
        with budget(max_usd=0.10, name="outline") as outline:
            print("Creating content outline...")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"Create a brief outline for a blog post about: {key_points}",
                    }
                ],
                max_tokens=100,
            )

            outline_text = response.choices[0].message.content
            print(f"✅ Outline complete: ${outline.spent:.4f}")
            print(f"   Remaining: ${outline.remaining:.4f}")

        # Stage 3: Writing ($0.20 budget)
        print("\n✍️  Stage 3: Writing")
        print("-" * 60)
        with budget(max_usd=0.20, name="writing") as writing:
            print("Writing content...")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": f"Write a short paragraph based on this outline: {outline_text}",
                    }
                ],
                max_tokens=200,
            )

            draft = response.choices[0].message.content
            print(f"✅ Writing complete: ${writing.spent:.4f}")
            print(f"   Remaining: ${writing.remaining:.4f}")

        # Final polish (uses remaining parent budget)
        print("\n✨ Stage 4: Polish")
        print("-" * 60)
        print(f"Parent budget remaining: ${pipeline.remaining:.4f}")
        print("Adding final touches...")

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": f"Add a compelling title to this: {draft[:100]}...",
                }
            ],
            max_tokens=50,
        )

        final = response.choices[0].message.content
        print("✅ Polish complete")

    # Print summary
    print("\n" + "=" * 60)
    print("💰 COST BREAKDOWN")
    print("=" * 60)
    print(f"Total budget: ${pipeline.limit:.4f}")
    print(f"Total spent: ${pipeline.spent:.4f}")
    print(f"Remaining: ${pipeline.remaining:.4f}")
    print(f"\nDirect spend (polish): ${pipeline.spent_direct:.4f}")
    print(f"Child spend (stages): ${pipeline.spent_by_children:.4f}")
    print("\n🌳 Budget Tree:")
    print(pipeline.tree())
    print("=" * 60)

    print("\n📊 Per-Stage Breakdown:")
    print(f"  Research: ${research.spent:.4f} / ${research.limit:.4f}")
    print(f"  Outline:  ${outline.spent:.4f} / ${outline.limit:.4f}")
    print(f"  Writing:  ${writing.spent:.4f} / ${writing.limit:.4f}")
    print(f"  Polish:   ${pipeline.spent_direct:.4f}")

    print("\n✅ Pipeline complete!")
    print("\nFinal content preview:")
    print("-" * 60)
    print(final[:200] + "..." if len(final) > 200 else final)


def demo_auto_capping():
    """Demonstrate auto-capping when parent budget is exhausted."""
    print("\n\n" + "=" * 60)
    print("🎯 DEMO: Auto-Capping")
    print("=" * 60)

    import openai

    client = openai.OpenAI()

    # Small parent budget
    with budget(max_usd=0.05, name="tight_budget") as parent:
        # First child uses most of the budget
        print("\n1️⃣  First stage (normal)")
        with budget(max_usd=0.03, name="stage1") as s1:
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say hello"}],
                max_tokens=20,
            )
            print(f"   Spent: ${s1.spent:.4f}")
            print(f"   Parent remaining: ${parent.remaining:.4f}")

        # Second child wants $0.03, but only ~$0.02 left
        # It will be AUTO-CAPPED!
        print("\n2️⃣  Second stage (auto-capped)")
        with budget(max_usd=0.03, name="stage2") as s2:
            print("   Requested: $0.03")
            print(f"   Actual limit: ${s2.limit:.4f} (auto-capped!)")
            client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say goodbye"}],
                max_tokens=20,
            )
            print(f"   Spent: ${s2.spent:.4f}")

    print(f"\n📊 Final: ${parent.spent:.4f} / ${parent.limit:.4f}")


if __name__ == "__main__":
    try:
        main()

        # Demo auto-capping
        if os.getenv("OPENAI_API_KEY"):
            demo_auto_capping()

    except BudgetExceededError as e:
        print(f"\n❌ Budget exceeded: ${e.spent:.4f} > ${e.limit:.4f}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
