"""Tool Budget Demo — shekel v0.2.8

Demonstrates:
  A) @tool decorator — plain Python functions (sync + async)
  B) max_tool_calls — hard cap, raises ToolBudgetExceededError pre-dispatch
  C) tool_prices — budget-level price override (for auto-intercepted tools)
  D) Combined LLM + tool budget
  E) ToolBudgetExceededError — full error fields
  F) budget.summary() — LLM spend + tool breakdown

Run:
    python examples/tool_budget_demo.py
"""

from __future__ import annotations

import asyncio

from shekel import budget, tool
from shekel.exceptions import ToolBudgetExceededError

# ---------------------------------------------------------------------------
# Declare tools once — price set on the decorator, no need to repeat it
# ---------------------------------------------------------------------------


@tool
def read_file(path: str) -> str:
    """Free tool — counts toward max_tool_calls, costs $0."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


@tool(price=0.005)
def web_search(query: str) -> str:
    """Priced tool — $0.005 per call."""
    # Simulated; replace with real API call
    return f"[search results for: {query!r}]"


@tool(price=0.02)
def run_code(code: str) -> str:
    """Expensive tool — $0.02 per execution."""
    # Simulated
    return f"[output of: {code[:40]!r}]"


@tool(price=0.005)
async def async_search(query: str) -> str:
    """Async priced tool."""
    await asyncio.sleep(0)  # simulate I/O
    return f"[async results for: {query!r}]"


# ---------------------------------------------------------------------------
# A) @tool decorator basics — price comes from decorator, not budget
# ---------------------------------------------------------------------------


def demo_decorator() -> None:
    print("=== A) @tool decorator ===")

    with budget(max_tool_calls=5) as b:
        web_search("shekel python library")  # $0.005 from decorator
        read_file("/tmp/notes.txt")  # $0.000 — no price on decorator
        run_code("print('hello')")  # $0.020 from decorator

    print(f"Tool calls:  {b.tool_calls_used}")
    print(f"Tool spend:  ${b.tool_spent:.4f}")
    print()


# ---------------------------------------------------------------------------
# B) max_tool_calls — hard cap, pre-dispatch
# ---------------------------------------------------------------------------


def demo_cap() -> None:
    print("=== B) max_tool_calls cap ===")
    b = None
    try:
        with budget(max_tool_calls=3) as b:
            web_search("query 1")
            web_search("query 2")
            web_search("query 3")
            web_search("query 4")  # ← blocked here, never executes
    except ToolBudgetExceededError as e:
        print(f"Blocked '{e.tool_name}' — {e.calls_used}/{e.calls_limit} calls used")
    if b is not None:
        print(f"Calls recorded: {b.tool_calls_used}")
    print()


# ---------------------------------------------------------------------------
# C) tool_prices — budget-level override
#    Use this for auto-intercepted tools (LangChain, MCP, CrewAI, OpenAI
#    Agents) where you can't put a @tool decorator. It also overrides the
#    decorator price when set.
# ---------------------------------------------------------------------------


def demo_prices() -> None:
    print("=== C) tool_prices (budget-level override) ===")
    with budget(
        tool_prices={
            "web_search": 0.01,  # overrides @tool(price=0.005) for this budget
            "run_code": 0.05,  # overrides @tool(price=0.02) for this budget
        }
    ) as b:
        web_search("quantum computing")
        web_search("LLM safety")
        run_code("summarize(papers)")
        read_file("notes.txt")  # not in tool_prices, no decorator price → $0

    print(f"Tool calls:  {b.tool_calls_used}")
    print(f"Tool spend:  ${b.tool_spent:.4f}")
    print(f"Remaining:   {b.tool_calls_remaining}")  # None — no max_tool_calls set
    print()


# ---------------------------------------------------------------------------
# D) Combined budget — USD cap + tool call cap
# ---------------------------------------------------------------------------


def demo_combined() -> None:
    print("=== D) Combined max_usd + max_tool_calls ===")
    with budget(
        max_tool_calls=10,
        warn_at=0.8,
        name="research-run",
    ) as b:
        for i in range(8):
            web_search(f"topic {i}")  # $0.005 each from decorator
        run_code("analyze()")  # $0.020 from decorator

    print(f"Tool calls:     {b.tool_calls_used} / 10")
    print(f"Tool remaining: {b.tool_calls_remaining}")
    print(f"Tool spend:     ${b.tool_spent:.4f}")
    print()


# ---------------------------------------------------------------------------
# E) ToolBudgetExceededError — full fields
# ---------------------------------------------------------------------------


def demo_error_fields() -> None:
    print("=== E) ToolBudgetExceededError fields ===")
    try:
        with budget(max_tool_calls=2, max_usd=1.00):
            web_search("first")  # $0.005 from decorator
            web_search("second")  # $0.005 from decorator
            web_search("third")  # blocked — 2/2 calls used
    except ToolBudgetExceededError as e:
        print(f"  tool_name:   {e.tool_name}")
        print(f"  calls_used:  {e.calls_used}")
        print(f"  calls_limit: {e.calls_limit}")
        print(f"  usd_spent:   ${e.usd_spent:.4f}")
        print(f"  usd_limit:   ${e.usd_limit}")
        print(f"  framework:   {e.framework}")
    print()


# ---------------------------------------------------------------------------
# F) budget.summary() with tool breakdown
# ---------------------------------------------------------------------------


def demo_summary() -> None:
    print("=== F) budget.summary() ===")
    with budget(
        max_tool_calls=20,
        name="research-agent",
    ) as b:
        for _ in range(5):
            web_search("AI safety research")  # $0.005 each from decorator
        run_code("summarize(papers)")  # $0.020 from decorator
        read_file("notes.txt")  # $0.000

    print(b.summary())


# ---------------------------------------------------------------------------
# G) Async tools
# ---------------------------------------------------------------------------


async def demo_async() -> None:
    print("=== G) Async tools ===")
    with budget(max_tool_calls=5) as b:
        await async_search("async query 1")  # $0.005 from decorator
        await async_search("async query 2")  # $0.005 from decorator

    print(f"Tool calls: {b.tool_calls_used}")
    print(f"Tool spend: ${b.tool_spent:.4f}")
    print()


# ---------------------------------------------------------------------------
# H) Nested budgets — tool counts roll up
# ---------------------------------------------------------------------------


def demo_nested() -> None:
    print("=== H) Nested budgets — tool rollup ===")
    with budget(max_tool_calls=100, name="workflow") as workflow:
        with budget(max_tool_calls=10, name="research") as research:
            web_search("topic A")
            web_search("topic B")
            read_file("data.txt")

        with budget(max_tool_calls=10, name="analysis") as analysis:
            run_code("analyze()")

    print(f"Research tools: {research.tool_calls_used}")  # 3
    print(f"Analysis tools: {analysis.tool_calls_used}")  # 1
    print(f"Total tools:    {workflow.tool_calls_used}")  # 4
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo_decorator()
    demo_cap()
    demo_prices()
    demo_combined()
    demo_error_fields()
    demo_summary()
    asyncio.run(demo_async())
    demo_nested()
    print("Done!")
