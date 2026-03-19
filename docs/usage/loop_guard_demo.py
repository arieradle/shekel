"""
loop_guard_demo.py — runnable example for the Loop Guard feature.

Demonstrates:
- A tool that gets stuck in a loop (same result repeatedly)
- loop_guard=True detecting and raising AgentLoopError
- warn_only=True variant (observes without blocking)
- b.loop_guard_counts after a run

No real API key needed — tool calls are simulated directly.
"""

from __future__ import annotations

from shekel import budget, tool
from shekel.exceptions import AgentLoopError, BudgetExceededError

# ---------------------------------------------------------------------------
# A tool that always returns the same stale result — a loop magnet
# ---------------------------------------------------------------------------

CALL_COUNT = 0


@tool
def fetch_news(query: str) -> str:  # noqa: ARG001
    """Fetch latest news. Always returns stale data — simulates a stuck feed."""
    global CALL_COUNT
    CALL_COUNT += 1
    return "No new results found. Try again later."


@tool
def write_report(content: str) -> str:
    """Write the final report once we have enough data."""
    return f"Report written: {content[:60]}"


def simulate_looping_agent(b: budget) -> None:  # type: ignore[name-defined]
    """Simulate an agent that loops on fetch_news hoping for fresh data."""
    for i in range(20):
        result = fetch_news("AI news")
        if "No new" not in result:
            write_report(result)
            break
        # Agent keeps trying — this is the loop
        _ = i  # iteration variable used for loop control only


# ---------------------------------------------------------------------------
# Demo 1: Loop guard fires and raises AgentLoopError
# ---------------------------------------------------------------------------


def demo_loop_detected() -> None:
    global CALL_COUNT
    CALL_COUNT = 0

    print("=== Demo 1: Loop guard detects repeated fetch_news calls ===")

    try:
        with budget(
            loop_guard=True,
            loop_guard_max_calls=5,
            loop_guard_window_seconds=60.0,
        ) as b:
            simulate_looping_agent(b)
            print("This line should not be reached — loop guard should have fired")

    except AgentLoopError as e:
        print(f"Caught AgentLoopError:")
        print(f"  tool_name:      {e.tool_name}")
        print(f"  call_count:     {e.call_count}")
        print(f"  window_seconds: {e.window_seconds}")
        print(f"  usd_spent:      ${e.usd_spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded (unexpected): {e}")

    print(f"fetch_news was called {CALL_COUNT} times total")
    print()


# ---------------------------------------------------------------------------
# Demo 2: warn_only=True — observes loop without blocking
# ---------------------------------------------------------------------------


def demo_warn_only() -> None:
    global CALL_COUNT
    CALL_COUNT = 0

    print("=== Demo 2: warn_only=True — loop is observed but not blocked ===")

    with budget(
        loop_guard=True,
        loop_guard_max_calls=5,
        loop_guard_window_seconds=60.0,
        warn_only=True,
    ) as b:
        simulate_looping_agent(b)

    print(f"Agent ran to completion. fetch_news called {CALL_COUNT} times.")
    print("Loop was detected but warn_only=True suppressed the exception.")
    print()

    print("loop_guard_counts after run:")
    for tool_name, count in b.loop_guard_counts.items():
        status = " *** LOOP DETECTED ***" if count >= 5 else ""
        print(f"  {tool_name}: {count} calls{status}")
    print()


# ---------------------------------------------------------------------------
# Demo 3: Inspect b.loop_guard_counts after a normal (non-looping) run
# ---------------------------------------------------------------------------


def demo_inspect_counts() -> None:
    global CALL_COUNT
    CALL_COUNT = 0

    print("=== Demo 3: Inspecting loop_guard_counts after a normal run ===")

    @tool
    def search_web(query: str) -> str:  # noqa: ARG001
        return "Result A"

    @tool
    def read_file(path: str) -> str:  # noqa: ARG001
        return "File contents..."

    with budget(loop_guard=True, loop_guard_max_calls=10) as b:
        # Normal agent: a few calls to each tool, no loop
        for _ in range(3):
            search_web("query")
        for _ in range(2):
            read_file("data.txt")

    print("Tool call counts recorded by loop guard:")
    for tool_name, count in b.loop_guard_counts.items():
        print(f"  {tool_name}: {count} calls")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    demo_loop_detected()
    demo_warn_only()
    demo_inspect_counts()
    print("=== All demos complete ===")


if __name__ == "__main__":
    main()
