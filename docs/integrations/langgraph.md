# LangGraph Integration

Shekel works seamlessly with [LangGraph](https://github.com/langchain-ai/langgraph) to track and enforce budgets on graph-based agent workflows.

## Installation

```bash
pip install shekel[openai] "langgraph>=0.2"
```

## Convenience Helper

Shekel provides a `budgeted_graph()` context manager so you don't need to import `budget` directly:

```python
from shekel.integrations.langgraph import budgeted_graph

app = graph.compile()

with budgeted_graph(max_usd=0.50, name="research-graph") as b:
    result = app.invoke({"question": "What is 2+2?", "answer": ""})
    print(f"Answer: {result['answer']}")
    print(f"Cost: ${b.spent:.4f}")
```

It accepts the same keyword arguments as `budget()` (`name`, `warn_at`, `fallback`, `max_llm_calls`, etc.) and yields the active budget object.

## Basic Integration

You can also use `budget()` directly — they are equivalent:

```python
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict
from shekel import budget
import openai

client = openai.OpenAI()

class State(TypedDict):
    question: str
    answer: str

def call_llm(state: State) -> State:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": state["question"]}],
    )
    return {
        "question": state["question"],
        "answer": response.choices[0].message.content
    }

# Build graph
graph = StateGraph(State)
graph.add_node("llm", call_llm)
graph.set_entry_point("llm")
graph.add_edge("llm", END)
app = graph.compile()

# Execute with budget
with budget(max_usd=0.50) as b:
    result = app.invoke({"question": "What is 2+2?", "answer": ""})
    print(f"Answer: {result['answer']}")
    print(f"Cost: ${b.spent:.4f}")
```

## Multi-Node Graphs

Shekel tracks all LLM calls across all nodes:

```python
class AgentState(TypedDict):
    task: str
    research: str
    analysis: str
    conclusion: str

def research_node(state: AgentState) -> AgentState:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Research: {state['task']}"}],
    )
    return {**state, "research": response.choices[0].message.content}

def analyze_node(state: AgentState) -> AgentState:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Analyze: {state['research']}"}],
    )
    return {**state, "analysis": response.choices[0].message.content}

def conclude_node(state: AgentState) -> AgentState:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Conclude: {state['analysis']}"}],
    )
    return {**state, "conclusion": response.choices[0].message.content}

# Build multi-node graph
graph = StateGraph(AgentState)
graph.add_node("research", research_node)
graph.add_node("analyze", analyze_node)
graph.add_node("conclude", conclude_node)
graph.set_entry_point("research")
graph.add_edge("research", "analyze")
graph.add_edge("analyze", "conclude")
graph.add_edge("conclude", END)
app = graph.compile()

# All nodes tracked under one budget
with budget(max_usd=1.00) as b:
    result = app.invoke({
        "task": "Explain quantum computing",
        "research": "",
        "analysis": "",
        "conclusion": ""
    })
    print(f"Total graph cost: ${b.spent:.4f}")
    print(b.summary())
```

## Retry Loops with Budget Protection

The original use case — prevent runaway costs from retry loops:

```python
from langgraph.graph import StateGraph, END

class RetryState(TypedDict):
    query: str
    result: str
    attempts: int
    max_attempts: int

def try_query(state: RetryState) -> RetryState:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": state["query"]}],
    )
    result = response.choices[0].message.content
    
    # Simulate failure
    if "error" in result.lower() and state["attempts"] < state["max_attempts"]:
        return {
            **state,
            "result": result,
            "attempts": state["attempts"] + 1
        }
    
    return {**state, "result": result}

def should_retry(state: RetryState) -> str:
    if state["attempts"] < state["max_attempts"] and "error" in state["result"].lower():
        return "retry"
    return "done"

# Build graph with conditional retry
graph = StateGraph(RetryState)
graph.add_node("try_query", try_query)
graph.set_entry_point("try_query")
graph.add_conditional_edges(
    "try_query",
    should_retry,
    {"retry": "try_query", "done": END}
)
app = graph.compile()

# Budget prevents infinite retry loops!
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=1.00) as b:
        result = app.invoke({
            "query": "Explain AI",
            "result": "",
            "attempts": 0,
            "max_attempts": 10
        })
        print(f"Success after {result['attempts']} attempts")
        print(f"Cost: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Retry loop stopped by budget at ${e.spent:.4f}")
```

## Fallback Models in Graphs

Use cheaper models when budget is reached:

```python
with budget(max_usd=0.50, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    # Graph starts with gpt-4o
    result = app.invoke(initial_state)

    # Automatically switches to gpt-4o-mini at 80% of $0.50 ($0.40)

    if b.model_switched:
        print(f"Switched to {b.fallback} at ${b.switched_at_usd:.4f}")
```

## Async Graphs

Shekel works with async LangGraph:

```python
import asyncio
from shekel import budget

async def async_node(state: State) -> State:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": state["question"]}],
    )
    return {
        "question": state["question"],
        "answer": response.choices[0].message.content
    }

# Build async graph
graph = StateGraph(State)
graph.add_node("async_llm", async_node)
graph.set_entry_point("async_llm")
graph.add_edge("async_llm", END)
app = graph.compile()

async def run_with_budget():
    async with budget(max_usd=0.50) as b:
        result = await app.ainvoke({"question": "What is Python?", "answer": ""})
        print(f"Answer: {result['answer']}")
        print(f"Cost: ${b.spent:.4f}")

asyncio.run(run_with_budget())
```

## Streaming Graphs

Track costs for streaming graph execution:

```python
with budget(max_usd=1.00) as b:
    for chunk in app.stream({"question": "Explain AI", "answer": ""}):
        print(chunk)
    
    print(f"Streaming execution cost: ${b.spent:.4f}")
```

## Per-User Budget Limits

Enforce budgets per user in a multi-user system:

```python
user_budgets = {}

def get_user_budget(user_id: str) -> budget:
    if user_id not in user_budgets:
        user_budgets[user_id] = budget(max_usd=5.00, name=f"user_{user_id}")
    return user_budgets[user_id]

def handle_user_query(user_id: str, query: str):
    user_budget = get_user_budget(user_id)
    
    with user_budget:
        result = app.invoke({"question": query, "answer": ""})
        return result["answer"]

# Each user has their own budget that accumulates
response1 = handle_user_query("user_123", "What is Python?")
response2 = handle_user_query("user_456", "What is JavaScript?")
response3 = handle_user_query("user_123", "Tell me more")  # Accumulates
```

## LangGraph with Different Providers

Mix OpenAI and Anthropic in the same graph:

```python
import anthropic

openai_client = openai.OpenAI()
anthropic_client = anthropic.Anthropic()

def openai_node(state: State) -> State:
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": state["query"]}],
    )
    return {**state, "openai_result": response.choices[0].message.content}

def anthropic_node(state: State) -> State:
    response = anthropic_client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{"role": "user", "content": state["query"]}],
    )
    return {**state, "anthropic_result": response.content[0].text}

# Build graph with both providers
graph = StateGraph(State)
graph.add_node("openai", openai_node)
graph.add_node("anthropic", anthropic_node)
# ... configure edges ...

# Shekel tracks both providers
with budget(max_usd=1.00) as b:
    result = app.invoke({"query": "Compare AI models"})
    print(f"Combined cost: ${b.spent:.4f}")
```

## Real-World Example

Complete example with error handling, logging, and monitoring:

```python
import logging
from langgraph.graph import StateGraph, END
from shekel import budget, BudgetExceededError

logger = logging.getLogger(__name__)

class WorkflowState(TypedDict):
    input: str
    result: str
    cost: float

def process_with_budget(state: WorkflowState):
    """Process workflow with budget tracking."""
    try:
        with budget(max_usd=2.00, warn_at=0.8, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
            # Build and execute graph
            graph = build_complex_graph()
            result = graph.invoke({"input": state["input"]})
            
            # Log results
            logger.info(
                "Workflow completed",
                extra={
                    "cost": b.spent,
                    "model_switched": b.model_switched,
                    "calls": len(b.summary_data()["calls"])
                }
            )
            
            return {
                "input": state["input"],
                "result": result,
                "cost": b.spent
            }
    
    except BudgetExceededError as e:
        logger.error(f"Budget exceeded: ${e.spent:.4f}")
        return {
            "input": state["input"],
            "result": "Budget exceeded - workflow terminated",
            "cost": e.spent
        }
```

## Tips for LangGraph + Shekel

1. **Wrap at the graph level**, not individual nodes
2. **Reuse budget variables** for multi-turn conversations (they accumulate automatically)
3. **Set fallback models** to prevent graph crashes
4. **Monitor retry loops** with budget caps
5. **Test with low budgets** to catch runaway costs early

## Next Steps

- [CrewAI Integration](crewai.md)
- [OpenAI Integration](openai.md)
- [Budget Enforcement](../usage/budget-enforcement.md)
