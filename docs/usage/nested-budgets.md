# Nested Budgets

Independent spend caps per workflow stage, with automatic rollup — a child stage can never exceed its own cap or what the parent has left.

## Overview

Nested budgets let you enforce independent spend limits at every stage of a multi-step workflow, with automatic rollup to a parent cap. You get both control and visibility:

- **Control costs per stage** — Cap each phase independently
- **Track attribution** — See exactly where money was spent
- **Enforce hierarchy** — Parent budgets contain child budgets
- **Auto-cap safely** — Children can't exceed parent's remaining budget

## Quick Example

```python
from shekel import budget

with budget(max_usd=10.00, name="workflow") as workflow:
    # Research stage: $2 budget
    with budget(max_usd=2.00, name="research"):
        research_results = run_research_agent()
    
    # Analysis stage: $5 budget
    with budget(max_usd=5.00, name="analysis"):
        insights = run_analysis_agent()
    
    # Parent can spend directly too
    generate_final_report()

print(f"Total cost: ${workflow.spent:.2f}")
```

## Core Concepts

### 1. Automatic Spend Propagation

When a child budget exits, its spend automatically propagates to the parent:

```python
with budget(max_usd=10.00, name="parent") as parent:
    with budget(max_usd=2.00, name="child") as child:
        work()  # Spends $1.50
    # child exits → parent.spent += $1.50

print(parent.spent)  # $1.50
print(parent.spent_by_children)  # $1.50
print(parent.spent_direct)  # $0.00
```

### 2. Auto-Capping

Children are automatically capped to the parent's remaining budget:

```python
with budget(max_usd=10.00, name="parent") as parent:
    parent_work()  # Spends $7.00
    
    # Child wants $5, but only $3 left
    with budget(max_usd=5.00, name="child") as child:
        print(child.limit)  # $3.00 (auto-capped!)
        work()
```

**Why this matters:** Prevents children from exceeding parent's limit, even if their requested budget is higher.

### 3. Parent Locking

Parents cannot spend while a child is active:

```python
with budget(max_usd=10.00, name="parent") as parent:
    with budget(max_usd=2.00, name="child"):
        work()
        
        # This would raise RuntimeError:
        # parent_work()  # ❌ Cannot spend on parent while child active
    
    # Child exited, parent can spend again
    parent_work()  # ✅ OK
```

**Why this matters:** Ensures sequential execution and clear cost attribution.

### 4. Named Budgets

Names are **required** when nesting budgets:

```python
# ✅ Correct
with budget(max_usd=10, name="parent"):
    with budget(max_usd=5, name="child"):
        work()

# ❌ Raises ValueError
with budget(max_usd=10):  # Missing name!
    with budget(max_usd=5):
        work()
```

**Why this matters:** Names are essential for debugging, logging, and cost attribution in complex workflows.

## Advanced Features

### Hierarchical Names

Use `full_name` to get the complete path:

```python
with budget(max_usd=20, name="pipeline") as root:
    with budget(max_usd=10, name="processing") as proc:
        with budget(max_usd=5, name="validation") as val:
            print(val.full_name)  # "pipeline.processing.validation"
```

### Cost Attribution

Track where money was spent:

```python
with budget(max_usd=20.00, name="workflow") as w:
    with budget(max_usd=5.00, name="stage1"):
        work1()  # $3.00
    
    with budget(max_usd=8.00, name="stage2"):
        work2()  # $6.00
    
    work_parent()  # $2.00

print(f"Total: ${w.spent:.2f}")                 # $11.00
print(f"Direct: ${w.spent_direct:.2f}")         # $2.00
print(f"Children: ${w.spent_by_children:.2f}")  # $9.00
```

### Budget Tree Visualization

Use `tree()` to visualize the hierarchy:

```python
with budget(max_usd=50.00, name="pipeline") as p:
    with budget(max_usd=10.00, name="ingestion") as i:
        ingest()
    
    with budget(max_usd=20.00, name="processing") as proc:
        with budget(max_usd=8.00, name="validation") as v:
            validate()
        
        with budget(max_usd=12.00, name="transform") as t:
            transform()
    
    generate()

print(p.tree())
# pipeline: $35.50 / $50.00 (direct: $2.00)
#   ingestion: $8.50 / $10.00 (direct: $8.50)
#   processing: $25.00 / $20.00 (direct: $0.00)
#     validation: $12.00 / $8.00 (direct: $12.00)
#     transform: $13.00 / $12.00 (direct: $13.00)
```

### Track-Only Children

Create unlimited child budgets for tracking:

```python
with budget(max_usd=20.00, name="workflow") as w:
    # Track exploration without limits
    with budget(max_usd=None, name="exploration"):
        explore_options()  # No limit!
    
    # But finalization is capped
    with budget(max_usd=5.00, name="finalization"):
        finalize()

print(f"Exploration cost: ${w.children[0].spent:.2f}")
```

## Real-World Examples

### Multi-Agent System

```python
def research_agent(topic: str, budget_usd: float = 10.0):
    """Research agent with per-stage budgets."""
    
    with budget(max_usd=budget_usd, name="research_agent") as agent:
        # Stage 1: Web search
        with budget(max_usd=2.00, name="web_search"):
            results = search_web(topic)
        
        # Stage 2: Content analysis
        with budget(max_usd=5.00, name="analysis"):
            insights = analyze(results)
        
        # Stage 3: Report generation
        with budget(max_usd=3.00, name="report"):
            report = generate_report(insights)
    
    print(agent.tree())
    return report
```

### LangGraph Integration

```python
from langgraph.graph import StateGraph
from shekel import budget

def create_workflow():
    """LangGraph workflow with nested budgets."""
    
    workflow = StateGraph(AgentState)
    
    # Wrap entire workflow
    with budget(max_usd=20.00, name="langgraph_workflow") as main:
        # Research node
        def research_node(state):
            with budget(max_usd=5.00, name="research"):
                return {"research": run_research(state)}
        
        # Analysis node
        def analysis_node(state):
            with budget(max_usd=10.00, name="analysis"):
                return {"analysis": run_analysis(state)}
        
        workflow.add_node("research", research_node)
        workflow.add_node("analysis", analysis_node)
        workflow.add_edge("research", "analysis")
        
        app = workflow.compile()
        result = app.invoke({"query": "..."})
    
    print(f"Total cost: ${main.spent:.2f}")
    print(main.tree())
```

### CrewAI Per-Agent Budgets

```python
from crewai import Crew, Agent
from shekel import budget

def run_crew():
    """CrewAI with per-agent budgets."""
    
    with budget(max_usd=15.00, name="crew") as crew_budget:
        # Researcher agent
        with budget(max_usd=5.00, name="researcher"):
            researcher = Agent(
                role="Research Analyst",
                goal="Find relevant information"
            )
            researcher.execute_task(research_task)
        
        # Writer agent
        with budget(max_usd=8.00, name="writer"):
            writer = Agent(
                role="Content Writer",
                goal="Write comprehensive report"
            )
            writer.execute_task(writing_task)
    
    print(crew_budget.tree())
```

## Best Practices

### 1. Always Name Nested Budgets

```python
# ❌ Bad: No names
with budget(max_usd=10):
    with budget(max_usd=5):
        work()

# ✅ Good: Clear names
with budget(max_usd=10, name="workflow"):
    with budget(max_usd=5, name="processing"):
        work()
```

### 2. Budget for Each Major Stage

```python
with budget(max_usd=20, name="pipeline") as p:
    with budget(max_usd=5, name="ingestion"):
        ingest()
    
    with budget(max_usd=10, name="processing"):
        process()
    
    with budget(max_usd=5, name="output"):
        output()
```

### 3. Use `tree()` for Debugging

```python
try:
    with budget(max_usd=10, name="workflow") as w:
        run_workflow()
except BudgetExceededError:
    print("Budget exceeded! Cost breakdown:")
    print(w.tree())
```

### 4. Check Auto-Capping

```python
with budget(max_usd=10, name="parent") as parent:
    expensive_operation()  # Might use most of budget
    
    with budget(max_usd=5, name="child") as child:
        if child.limit < 5.00:
            print(f"⚠️  Child was auto-capped to ${child.limit:.2f}")
            # Maybe use a cheaper model?
```

## Limitations

### Maximum Nesting Depth

Maximum depth is **5 levels** (root at depth 0):

```python
with budget(max_usd=100, name="L0"):      # Depth 0 ✅
    with budget(max_usd=50, name="L1"):   # Depth 1 ✅
        with budget(max_usd=25, name="L2"):  # Depth 2 ✅
            with budget(max_usd=12, name="L3"):  # Depth 3 ✅
                with budget(max_usd=6, name="L4"):  # Depth 4 ✅
                    work()  # ✅ OK
                    
                    # Depth 5 would raise ValueError
                    # with budget(max_usd=3, name="L5"):  # ❌
```

### Async Nesting

Nested budgets work identically in async contexts — same naming rules, same depth limit, same spend propagation:

```python
async with budget(max_usd=10, name="parent") as parent:
    async with budget(max_usd=5, name="child") as child:
        await work()

# child.spent is propagated to parent on exit
```

Each `asyncio` task gets its own isolated budget context automatically, so concurrent tasks cannot interfere with each other's budgets.

### Unique Sibling Names

Children under the same parent must have unique names:

```python
with budget(max_usd=10, name="parent"):
    with budget(max_usd=3, name="stage1"):  # ✅
        work()
    
    with budget(max_usd=3, name="stage1"):  # ❌ Duplicate!
        work()
```

## Migration Notes

### Accumulating Budgets

Budget variables always accumulate across uses. Create a new `budget()` instance if you need a fresh budget:

```python
# Accumulates across uses
b = budget(max_usd=10.00)
with b: work1()  # Spends $2
with b: work2()  # Spends $2 more — b.spent == $4

# Fresh budget each time
with budget(max_usd=10.00): work1()  # $2 (separate budget)
with budget(max_usd=10.00): work2()  # $2 (separate budget)
```

## API Reference

See [API Reference](../api-reference.md#nested-budget-properties) for complete details:

- `budget.parent` — Parent budget reference
- `budget.children` — List of child budgets
- `budget.active_child` — Currently active child
- `budget.full_name` — Hierarchical path name
- `budget.spent_direct` — Direct spend (excluding children)
- `budget.spent_by_children` — Sum of child spend
- `budget.tree()` — Visual hierarchy

## Examples

See [`examples/`](https://github.com/arieradle/shekel/tree/main/examples) for runnable demos:

- `nested_research_agent.py` — Multi-stage research workflow
- `nested_content_pipeline.py` — Real OpenAI API integration
