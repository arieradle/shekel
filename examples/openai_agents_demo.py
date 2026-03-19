"""
openai_agents_demo.py — runnable example for the OpenAI Agents SDK integration.

Demonstrates:
- Two agents (researcher + writer) each with a per-agent cap
- b.agent() registration
- Runner.run mock calls
- b.tree() spend breakdown
- Catching AgentBudgetExceededError

No real API key needed — the runner and spend are mocked.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from shekel import budget
from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

# ---------------------------------------------------------------------------
# Minimal mock objects so the demo runs without the openai-agents package
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class FakeRunResult:
    final_output: str


class FakeAgent:
    def __init__(self, name: str, instructions: str) -> None:
        self.name = name
        self.instructions = instructions


class FakeRunner:
    """Simulates Runner.run by recording a small spend in the active budget."""

    @staticmethod
    async def run(agent: FakeAgent, prompt: str, **kwargs: Any) -> FakeRunResult:  # noqa: ARG004
        # Simulate LLM spend: $0.60 for researcher, $0.40 for writer
        spend_map = {"researcher": 0.60, "writer": 0.40}
        spend = spend_map.get(agent.name, 0.10)
        _record_mock_spend(spend)
        return FakeRunResult(final_output=f"[{agent.name}] result for: {prompt[:40]}")


def _record_mock_spend(usd: float) -> None:
    """Push a fake LLM cost event into the active shekel budget."""
    from shekel._budget import _get_active_budget  # type: ignore[import]

    b = _get_active_budget()
    if b is not None:
        b._record_cost(usd, model="gpt-4o-mini", input_tokens=100, output_tokens=200)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Demo 1: Zero-config global cap
# ---------------------------------------------------------------------------


async def demo_global_cap() -> None:
    print("=== Demo 1: Zero-config global cap ===")

    researcher = FakeAgent(name="researcher", instructions="Find key facts about the topic.")
    writer = FakeAgent(name="writer", instructions="Write a concise summary.")

    try:
        with budget(max_usd=5.00) as b:
            research_result = await FakeRunner.run(researcher, "Research quantum computing")
            write_result = await FakeRunner.run(writer, research_result.final_output)
        print(f"Done. Spent: ${b.spent:.4f}")
        print(f"Research: {research_result.final_output}")
        print(f"Write: {write_result.final_output}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    print()


# ---------------------------------------------------------------------------
# Demo 2: Per-agent caps with b.agent()
# ---------------------------------------------------------------------------


async def demo_per_agent_caps() -> None:
    print("=== Demo 2: Per-agent caps ===")

    researcher = FakeAgent(name="researcher", instructions="Find key facts.")
    writer = FakeAgent(name="writer", instructions="Write a concise summary.")

    try:
        with budget(max_usd=5.00, name="agents") as b:
            b.agent(researcher.name, max_usd=2.00)
            b.agent(writer.name, max_usd=1.00)

            research_result = await FakeRunner.run(researcher, "Research AI safety")
            await FakeRunner.run(writer, research_result.final_output)

        print(f"Done. Spent: ${b.spent:.4f}")
        print()
        print(b.tree())

    except AgentBudgetExceededError as e:
        print(f"Agent '{e.agent_name}' exceeded cap: ${e.spent:.4f} / ${e.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: {e}")

    print()


# ---------------------------------------------------------------------------
# Demo 3: Agent cap exceeded — researcher busts its $0.30 limit
# ---------------------------------------------------------------------------


async def demo_agent_cap_exceeded() -> None:
    print("=== Demo 3: Agent cap exceeded ===")

    researcher = FakeAgent(name="researcher", instructions="Find key facts.")

    try:
        with budget(max_usd=5.00, name="agents-tight") as b:
            b.agent(researcher.name, max_usd=0.30)  # researcher costs $0.60 → will exceed

            await FakeRunner.run(researcher, "Research AI safety")
            print("This line should not be reached")

    except AgentBudgetExceededError as e:
        print("Caught AgentBudgetExceededError:")
        print(f"  agent_name: {e.agent_name}")
        print(f"  spent:      ${e.spent:.4f}")
        print(f"  limit:      ${e.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: {e}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    await demo_global_cap()
    await demo_per_agent_caps()
    await demo_agent_cap_exceeded()

    print("=== All demos complete ===")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
