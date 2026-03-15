# Tool Budgets

**Cap agent tool calls before they bankrupt you. One line. Works with LangChain, MCP, CrewAI, OpenAI Agents, or plain Python.**

Your agent called `web_search` 847 times last night. You're getting a bill. Tool budgets stop that.

---

## Quick Start

```python
from shekel import budget, ToolBudgetExceededError

# Hard cap — agent can't call more than 50 tools total
with budget(max_tool_calls=50):
    run_my_agent()  # raises ToolBudgetExceededError on the 51st call
```

No changes to your agent code. Works automatically with:

- **LangChain / LangGraph** — any `@tool`-decorated function or `BaseTool` subclass
- **MCP** — any `session.call_tool()` call
- **CrewAI** — any `BaseTool._run()` / `_arun()`
- **OpenAI Agents SDK** — any `FunctionTool`
- **Plain Python** — use the `@tool` decorator once

---

## `max_tool_calls` — Hard cap, pre-dispatch

The limit is checked *before* the tool runs. The 51st call never executes.

```python
try:
    with budget(max_tool_calls=10) as b:
        run_agent()
except ToolBudgetExceededError as e:
    print(f"Blocked {e.tool_name!r} — {e.calls_used} calls used of {e.calls_limit}")
```

---

## `tool_prices` — Cost per tool call

Use `@tool(price=...)` for plain Python functions you control — price is set once on the decorator:

```python
@tool(price=0.005)
def web_search(query: str) -> str: ...

with budget(max_usd=2.00, max_tool_calls=100) as b:
    run_agent()  # price comes from the decorator
```

Use `tool_prices` on `budget()` for **auto-intercepted** tools (LangChain, MCP, CrewAI, OpenAI Agents) where you can't add a decorator:

```python
with budget(
    tool_prices={
        "web_search": 0.01,    # $0.01 per search
        "run_code":   0.05,    # $0.05 per execution
    }
) as b:
    run_agent()

print(f"Tool calls: {b.tool_calls_used}")
print(f"Tool cost:  ${b.tool_spent:.4f}")
```

If both are set for the same tool, `tool_prices` on the budget takes priority (useful for per-run price overrides).

Unknown tools — not in `tool_prices` and no decorator price — still count toward `max_tool_calls` at `$0`. No silent gaps.

---

## Combine both — cap calls *and* USD

```python
with budget(
    max_usd=10.00,           # hard USD cap on everything (LLM + tools)
    max_tool_calls=100,      # hard cap on tool dispatches
    tool_prices={"web_search": 0.01},
    warn_at=0.8,             # callback at 80 tool calls
) as b:
    run_agent()

print(b.summary())
```

---

## `@tool` decorator for plain Python functions

Wrap any function or third-party callable once — shekel tracks it everywhere:

```python
from shekel import tool

@tool                        # free tool — just count calls
def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()

@tool(price=0.005)           # priced tool — count + charge
def web_search(query: str) -> str:
    return requests.get(f"https://api.search.io?q={query}").text

@tool()                      # same as @tool, empty-call form
def summarize(text: str) -> str: ...

# Third-party tools work too
from langchain_community.tools.tavily_search import TavilySearchResults
tavily = tool(TavilySearchResults(), price=0.005)
```

When no budget is active, `@tool` is a transparent pass-through — zero overhead.

---

## Framework Auto-Interception

### LangChain / LangGraph

No changes needed. `BaseTool.invoke` and `ainvoke` are patched automatically on `budget()` entry.

```python
from langchain_core.tools import tool as lc_tool
from langgraph.prebuilt import create_react_agent

@lc_tool
def search(query: str) -> str:
    """Search the web."""
    return brave_search(query)

agent = create_react_agent(llm, tools=[search])

with budget(max_tool_calls=20, tool_prices={"search": 0.01}) as b:
    result = agent.invoke({"messages": [{"role": "user", "content": "Research AI safety"}]})

print(f"Tool calls: {b.tool_calls_used} / 20")
print(f"Tool cost:  ${b.tool_spent:.2f}")
```

### MCP

```python
from shekel import budget

async with budget(max_tool_calls=50) as b:
    result = await session.call_tool("brave_search", {"query": "shekel python"})
    result = await session.call_tool("run_python", {"code": "print('hello')"})

print(f"MCP tool calls: {b.tool_calls_used}")
```

### CrewAI

```python
from crewai import Crew
from crewai_tools import SerperDevTool
from shekel import budget

search_tool = SerperDevTool()

with budget(max_tool_calls=30, tool_prices={"SerperDevTool": 0.001}) as b:
    crew = Crew(agents=[researcher], tasks=[task])
    crew.kickoff()

print(f"Tool calls: {b.tool_calls_used}")
```

### OpenAI Agents SDK

```python
from agents import Runner
from shekel import budget

with budget(max_tool_calls=25) as b:
    result = await Runner.run(agent, "Research quantum computing")

print(f"Tool calls: {b.tool_calls_used}")
```

---

## `ToolBudgetExceededError`

```python
from shekel import budget, ToolBudgetExceededError

try:
    with budget(max_tool_calls=5):
        run_agent()
except ToolBudgetExceededError as e:
    print(f"Tool:        {e.tool_name}")
    print(f"Calls used:  {e.calls_used} / {e.calls_limit}")
    print(f"USD spent:   ${e.usd_spent:.4f}")
    print(f"Framework:   {e.framework}")  # "langchain", "mcp", "crewai", "openai-agents", "manual"
```

---

## `warn_at` for tool calls

Fire a callback when approaching the tool call limit:

```python
def on_warn(spent, limit):
    print(f"Approaching tool limit — {b.tool_calls_used} / {b._effective_tool_call_limit} used")

with budget(max_tool_calls=50, warn_at=0.8, on_warn=on_warn) as b:
    run_agent()  # on_warn fires at 40 tool calls (80% of 50)
```

---

## Nested budgets + tool budgets

Tool call counts propagate to parent budgets automatically:

```python
with budget(max_tool_calls=100, name="workflow") as workflow:
    with budget(max_tool_calls=30, name="research") as research:
        search_papers()   # 15 tool calls

    with budget(max_tool_calls=50, name="analysis") as analysis:
        analyze_data()    # 8 tool calls

print(f"Research tools: {research.tool_calls_used}")   # 15
print(f"Analysis tools: {analysis.tool_calls_used}")   # 8
print(f"Total tools:    {workflow.tool_calls_used}")   # 23
```

Auto-capping also applies: if the parent has 30 tool calls remaining and a child requests 50, the child is capped to 30.

---

## `budget.summary()` with tool breakdown

```python
with budget(
    max_usd=5.00,
    max_tool_calls=50,
    tool_prices={"web_search": 0.01, "run_code": 0.03},
    name="agent",
) as b:
    run_agent()

print(b.summary())
```

```
┌─ Shekel Budget Summary ──────────────────────────────────────┐
│ Total: $0.8500  Limit: $5.00  Status: OK
├──────────────────────────────────────────────────────────────┤
│  LLM spend:   $0.62  (12 calls)
│  Tool spend:  $0.23  (38 / 50 tool calls)
│    web_search  $0.10  (10 calls)  [langchain]
│    run_code    $0.09  ( 3 calls)  [mcp]
│    read_file   $0.04  (15 calls)  [manual]
└──────────────────────────────────────────────────────────────┘
```

---

## API Reference

### `budget()` — new parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_tool_calls` | `int \| None` | `None` | Hard cap on total tool dispatches. |
| `tool_prices` | `dict \| None` | `None` | Per-tool USD cost: `{"tool_name": 0.01}`. |

### `@tool` decorator

```python
from shekel import tool

@tool                           # count only
def fn(): ...

@tool(price=0.005)              # count + charge per call
def fn(): ...

wrapped = tool(obj, price=0.01) # wrap any callable
```

Works with sync and async functions. Pass-through when no budget is active.

### New Budget properties

| Property | Type | Description |
|----------|------|-------------|
| `tool_calls_used` | `int` | Total tool dispatches made. |
| `tool_calls_remaining` | `int \| None` | Calls left before `max_tool_calls`. |
| `tool_spent` | `float` | Total USD spent on tools. |

### `ToolBudgetExceededError`

| Attribute | Type | Description |
|-----------|------|-------------|
| `tool_name` | `str` | Name of the blocked tool. |
| `calls_used` | `int` | Total calls when blocked. |
| `calls_limit` | `int \| None` | The `max_tool_calls` limit. |
| `usd_spent` | `float` | Total tool USD at blocking. |
| `usd_limit` | `float \| None` | The `max_usd` budget limit. |
| `framework` | `str` | `"langchain"`, `"mcp"`, `"crewai"`, `"openai-agents"`, or `"manual"`. |
