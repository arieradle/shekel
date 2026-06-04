---
title: AutoGen Budget Control – Per-Agent Circuit Breaking
description: "Enforce LLM spend limits on AutoGen agents. Per-agent USD caps, global conversation budget, and tree-view cost breakdown. Zero changes to your agent code required."
tags:
  - autogen
  - microsoft
  - agent-frameworks
  - circuit-breaker
  - budget-enforcement
---

# AutoGen Integration

AutoGen agents can run multi-turn conversations indefinitely — and rack up serious API costs in the process. Shekel adds the circuit-breaker: a hard dollar cap that fires `BudgetExceededError` the moment cumulative spend crosses your limit. Works with `ConversableAgent`, `AssistantAgent`, `UserProxyAgent`, and `GroupChat` with zero changes to your agent code.

## Installation

```bash
pip install shekel[autogen]
```

## Basic Integration

Wrap any AutoGen conversation in a `budget()` context:

```python
from autogen import AssistantAgent, UserProxyAgent
from shekel import budget

assistant = AssistantAgent(
    "assistant",
    llm_config={"config_list": [{"model": "gpt-4o-mini", "api_key": "..."}]},
)
user_proxy = UserProxyAgent("user_proxy", human_input_mode="NEVER", max_consecutive_auto_reply=2)

with budget(max_usd=0.50) as b:
    user_proxy.initiate_chat(assistant, message="Write a Python function to sort a list.")

print(b.summary())
```

If the conversation exceeds `$0.50`, shekel raises `BudgetExceededError` before the next agent turn begins.

## Per-Agent Caps

Limit individual agents independently with `b.agent()`:

```python
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager
from shekel import budget
from shekel.exceptions import AgentBudgetExceededError

planner = AssistantAgent("planner", llm_config={...})
coder   = AssistantAgent("coder",   llm_config={...})
reviewer = AssistantAgent("reviewer", llm_config={...})

with budget(max_usd=5.00) as b:
    b.agent("planner",  max_usd=0.50)
    b.agent("coder",    max_usd=2.00)
    b.agent("reviewer", max_usd=1.00)

    groupchat = GroupChat(agents=[planner, coder, reviewer], messages=[], max_round=10)
    manager = GroupChatManager(groupchat=groupchat, llm_config={...})
    planner.initiate_chat(manager, message="Build a REST API")
```

When an agent hits its individual cap, `AgentBudgetExceededError` is raised — other agents can continue unaffected. The per-agent cap and the global `max_usd` enforce independently.

## Exception Handling

```python
from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

try:
    with budget(max_usd=1.00) as b:
        b.agent("assistant", max_usd=0.30)
        user_proxy.initiate_chat(assistant, message="...")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' hit its cap: ${e.spent:.4f} / ${e.limit:.2f}")
except BudgetExceededError as e:
    print(f"Global budget exhausted: ${e.spent:.4f} / ${e.limit:.2f}")
```

`AgentBudgetExceededError` is a subclass of `BudgetExceededError`, so a single `except BudgetExceededError` catches both.

## Spend Summary

```python
with budget(max_usd=5.00, name="my_agent") as b:
    b.agent("assistant", max_usd=2.00)
    b.agent("critic",    max_usd=1.00)
    # ... run conversation ...

print(b.summary())
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# shekel spend summary — my_agent
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Total: $1.2450 / $5.00 (25%)
# ...

print(b.tree())
# my_agent: $1.2450 / $5.00 (24.9%)
#   [agent] assistant: $0.9800 / $2.00 (49.0%)
#   [agent] critic:    $0.2650 / $1.00 (26.5%)
```

## How It Works

Shekel patches `ConversableAgent.generate_reply` (sync) and `a_generate_reply` (async) at budget open, and restores them at budget exit. The underlying OpenAI / Anthropic SDK calls are already intercepted by shekel's provider patches — the AutoGen adapter adds per-agent attribution on top:

1. **Pre-gate**: before each agent turn, check the per-agent cap and global budget. Raise immediately if either is already exhausted.
2. **Call original**: the original `generate_reply` runs; the OpenAI/Anthropic patch records the spend.
3. **Post-attribute**: the spend delta from this turn is added to the agent's `ComponentBudget._spent`.

This means spend is always double-tracked: in the global budget total and in the per-agent breakdown.

## AutoGen Version Support

Tested with `pyautogen>=0.2`. Shekel detects AutoGen at runtime — if it is not installed, the adapter is silently skipped.
