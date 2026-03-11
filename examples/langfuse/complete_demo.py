"""
Langfuse Integration Example
============================

This example demonstrates all features of Shekel's Langfuse integration:
1. Real-time cost streaming
2. Nested budget mapping
3. Circuit break events
4. Fallback annotations

Prerequisites:
--------------
1. Install: pip install shekel[langfuse] shekel[openai]
2. Set environment variables:
   - OPENAI_API_KEY=your-openai-key
   - LANGFUSE_PUBLIC_KEY=pk-lf-...
   - LANGFUSE_SECRET_KEY=sk-lf-...
   - LANGFUSE_HOST=https://cloud.langfuse.com (or your self-hosted URL)

After running, check the Langfuse UI to see:
- Trace with real-time cost updates
- Nested spans for budget hierarchy
- Events for budget exceeded and fallback activation
"""

import os
from openai import OpenAI
from langfuse import Langfuse
from shekel import budget, BudgetExceededError
from shekel.integrations import AdapterRegistry
from shekel.integrations.langfuse import LangfuseAdapter


def setup_observability():
    """Initialize Langfuse integration (call once at startup)."""
    lf = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )
    
    adapter = LangfuseAdapter(
        client=lf,
        trace_name="shekel-demo",
        tags=["example", "python"]
    )
    
    AdapterRegistry.register(adapter)
    print("✅ Langfuse integration active")
    return lf


def demo_real_time_cost_streaming(client):
    """Feature #1: Real-time cost streaming to Langfuse."""
    print("\n" + "="*60)
    print("DEMO 1: Real-Time Cost Streaming")
    print("="*60)
    
    with budget(max_usd=1.00, name="cost-streaming-demo") as b:
        print(f"Starting budget: ${b.spent:.4f}")
        
        # Each call updates Langfuse metadata
        for i in range(3):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": f"Say 'Hello {i+1}' in a creative way (be brief)"
                }]
            )
            print(f"  Call {i+1}: ${b.spent:.4f} spent ({b.utilization*100:.1f}% of budget)")
        
        print(f"\n💰 Final cost: ${b.spent:.4f}")
        print(f"📊 Check Langfuse UI → Trace 'shekel-demo' → Metadata")
        print(f"    You'll see: shekel_spent, shekel_utilization, shekel_last_model")


def demo_nested_budget_mapping(client):
    """Feature #2: Nested budgets → span hierarchy in Langfuse."""
    print("\n" + "="*60)
    print("DEMO 2: Nested Budget Mapping")
    print("="*60)
    
    with budget(max_usd=5.00, name="multi-stage-workflow") as workflow:
        print(f"Workflow budget: ${workflow.max_usd:.2f}")
        
        # Stage 1: Research (child budget → child span)
        with budget(max_usd=1.50, name="research") as research:
            print(f"\n🔍 Research stage (budget: ${research.max_usd:.2f})")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": "List 3 interesting facts about Python (be very brief)"
                }]
            )
            print(f"   Research cost: ${research.spent:.4f}")
        
        # Stage 2: Analysis (sibling budget → sibling span)
        with budget(max_usd=2.00, name="analysis") as analysis:
            print(f"\n📊 Analysis stage (budget: ${analysis.max_usd:.2f})")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": "Summarize: Python facts in one sentence"
                }]
            )
            print(f"   Analysis cost: ${analysis.spent:.4f}")
        
        print(f"\n💰 Total workflow cost: ${workflow.spent:.4f}")
        print(f"🌳 Check Langfuse UI → See waterfall view with spans:")
        print(f"    Trace: multi-stage-workflow")
        print(f"      Span: multi-stage-workflow.research")
        print(f"      Span: multi-stage-workflow.analysis")


def demo_circuit_break_events(client):
    """Feature #3: Budget exceeded → WARNING event in Langfuse."""
    print("\n" + "="*60)
    print("DEMO 3: Circuit Break Events")
    print("="*60)
    
    try:
        with budget(max_usd=0.001, name="tiny-budget") as b:
            print(f"Attempting call with tiny budget: ${b.max_usd:.4f}")
            
            # This will exceed the budget
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": "Write a long story about AI" * 10
                }]
            )
    except BudgetExceededError as e:
        print(f"\n⚠️  Budget exceeded!")
        print(f"   Spent: ${e.spent:.4f}")
        print(f"   Limit: ${e.limit:.4f}")
        print(f"   Overage: ${e.spent - e.limit:.4f}")
        print(f"\n📊 Check Langfuse UI → Events → Filter: 'budget_exceeded'")
        print(f"    You'll see: spent, limit, overage, model, tokens")


def demo_fallback_annotations(client):
    """Feature #4: Fallback activation → INFO event + metadata update."""
    print("\n" + "="*60)
    print("DEMO 4: Fallback Annotations")
    print("="*60)
    
    with budget(
        max_usd=0.01,  # Very low to trigger fallback quickly
        fallback="gpt-4o-mini",
        hard_cap=0.50,
        name="fallback-demo"
    ) as b:
        print(f"Primary model: gpt-4o")
        print(f"Fallback model: {b.fallback}")
        print(f"Primary budget: ${b.max_usd:.4f}")
        print(f"Hard cap: ${b.hard_cap:.4f}")
        
        # Make calls until fallback triggers
        for i in range(5):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o" if not b.model_switched else "gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": f"Say hello {i+1}"
                    }]
                )
                
                if b.model_switched and i > 0:
                    print(f"\n🔄 Fallback activated at ${b.switched_at_usd:.4f}!")
                    print(f"   Now using: {b.fallback}")
                    break
                    
                print(f"  Call {i+1}: ${b.spent:.4f} (model: gpt-4o)")
            except BudgetExceededError:
                print(f"\n🛑 Hard cap reached at ${b.spent:.4f}")
                break
        
        print(f"\n💰 Final cost: ${b.spent:.4f}")
        print(f"📊 Check Langfuse UI → Events → Filter: 'fallback_activated'")
        print(f"    You'll see: from_model, to_model, switched_at, costs, savings")
        print(f"📊 Also check Trace Metadata:")
        print(f"    shekel_fallback_active: true")
        print(f"    shekel_fallback_model: gpt-4o-mini")


def main():
    """Run all demos."""
    print("🚀 Shekel + Langfuse Integration Demo")
    print("="*60)
    
    # Initialize
    lf = setup_observability()
    client = OpenAI()
    
    try:
        # Run demos
        demo_real_time_cost_streaming(client)
        demo_nested_budget_mapping(client)
        demo_circuit_break_events(client)
        demo_fallback_annotations(client)
        
        print("\n" + "="*60)
        print("✅ All demos complete!")
        print("="*60)
        print("\n📊 Next steps:")
        print("1. Open Langfuse UI")
        print("2. Find trace: 'shekel-demo'")
        print("3. Explore:")
        print("   - Metadata (real-time cost tracking)")
        print("   - Spans (nested budget hierarchy)")
        print("   - Events (budget_exceeded, fallback_activated)")
        print("\n💡 Pro tip: Filter events by level (WARNING, INFO) for easy debugging")
        
    finally:
        # Ensure all events are sent before exit
        print("\n🔄 Flushing Langfuse events...")
        lf.flush()
        print("✅ Done!")


if __name__ == "__main__":
    main()
