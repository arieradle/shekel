# PRD: OpenAI Agents SDK Adapter for Shekel

**Version:** 1.1.0
**Status:** Planning
**Author:** Shekel core team
**Date:** 2026-03-19

---

## 1. Problem Statement

### Why this gap matters

The OpenAI Agents SDK (launched March 2025) is now the canonical lightweight orchestration framework for building multi-agent systems on top of OpenAI models. Its `Runner` API—`Runner.run`, `Runner.run_sync`, `Runner.run_streamed`—is the entry point for every agent invocation. As of Shekel 1.0.2, the library has no awareness of this execution boundary.

This creates a real gap for production teams:

- **Spend is tracked globally** but cannot be attributed to individual agents by name. A five-agent pipeline that blows its budget produces a `BudgetExceededError` with no information about which agent caused it.
- **Per-agent caps cannot be enforced.** `b.agent("classifier", max_usd=0.10)` registers a `ComponentBudget` object, but the Agents SDK never consults it—the cap is silently ignored.
- **Handoffs between agents are invisible to the budget system.** When `Runner.run` triggers a handoff to a sub-agent, the sub-agent's cost is aggregated with no attribution.

Shekel already tracks OpenAI API spend through `shekel/providers/openai.py`, so raw token cost is captured. The missing layer is the *agent boundary*: attaching that spend to a named runner invocation.

### Why now

The OpenAI Agents SDK is post-launch (March 2025) and rapidly adopted. LangGraph, CrewAI, and LangChain adapters already ship in Shekel 1.0.x. The Agents SDK is the only major orchestration framework without a shekel adapter, which is a visible omission for OpenAI-native teams.

---

## 2. Target Users and Jobs-to-be-Done

### Primary users

**ML engineers and backend engineers** building multi-agent applications with the OpenAI Agents SDK who need to:
- Stay within API cost budgets per run or per agent
- Generate per-agent cost breakdowns for billing or debugging
- Stop runaway agents before they exhaust a shared budget

### Jobs-to-be-done

| Job | Current pain | With this feature |
|-----|-------------|-------------------|
| Cap spend for a specific agent by name | Cap is registered but never enforced | `b.agent("triage", max_usd=0.50)` raises before the agent spends more |
| See which agent in a pipeline caused a budget overrun | `BudgetExceededError` has no agent context | `AgentBudgetExceededError` names the agent, shows spent vs limit |
| Audit post-run spend per agent | All spend attributed to global `b.spent` | `b.tree()` shows per-agent breakdown |
| Protect a parent budget from a single runaway agent | No agent-level gate exists | Agent gate checks parent remaining budget before each run |
| Use shekel with zero code changes to existing agent code | Not possible | Open a `budget()` context; adapter auto-patches `Runner` at enter |

---

## 3. User Stories

### US-1: Zero-configuration global enforcement

As an engineer running a single-agent pipeline, I want to wrap my `Runner.run` call in a `budget(max_usd=1.00)` context and have it raise `BudgetExceededError` if the agent exceeds that limit — without changing my agent or runner code.

**Acceptance criteria:**
- `Runner.run`, `Runner.run_sync`, and `Runner.run_streamed` are automatically patched inside any `budget()` context.
- When the parent budget is already exhausted at the point `Runner.run` is called, `AgentBudgetExceededError` is raised before any API call is made.
- The original `Runner.run` behavior is unchanged outside a `budget()` context.

### US-2: Per-agent spend cap

As an engineer running a multi-agent pipeline, I want to declare `b.agent("researcher", max_usd=0.30)` and have shekel raise `AgentBudgetExceededError` if that agent's cumulative spend exceeds $0.30, even if the parent budget has remaining funds.

**Acceptance criteria:**
- Spend delta per `Runner.run` invocation is attributed to the matching `ComponentBudget._spent`.
- When `ComponentBudget._spent >= ComponentBudget.max_usd` at the start of the next run for that agent, the error is raised before execution.
- Unregistered agents (no matching `b.agent(...)`) run freely under the parent budget only.

### US-3: Spend attribution visible in b.tree()

As an engineer debugging a cost overrun, I want to call `b.tree()` after a run and see a per-agent spend breakdown so I know which agent consumed which fraction of the budget.

**Acceptance criteria:**
- After a `Runner.run` completes, the spend delta appears in the corresponding `ComponentBudget._spent`.
- `b.tree()` (existing) reflects the updated per-agent spend.
- If no `b.agent(...)` cap is registered for a given agent, no `ComponentBudget` is created — existing behavior is unchanged.

### US-4: Graceful degradation when SDK is not installed

As a developer who does not use the OpenAI Agents SDK, I want shekel to work exactly as before — without import errors or warnings — even after Shekel 1.1.0 ships the new adapter.

**Acceptance criteria:**
- If `openai-agents` is not installed, the adapter silently skips itself (`ImportError` caught in `install_patches`).
- No `ImportError` propagates to the user's code.
- Existing tests continue to pass without `openai-agents` installed.

### US-6: warn_only suppresses the agent gate

As a developer in a staging environment, I want `warn_only=True` to suppress `AgentBudgetExceededError` from the agent gate so that my pipeline never hard-stops even when a cap is exceeded, while still logging the violation for observability.

**Acceptance criteria:**
- When `budget(warn_only=True)` is active and an agent cap is exceeded, a `warnings.warn()` is issued with the agent name, spent, and limit.
- `AgentBudgetExceededError` is **not** raised; the `Runner.run` call proceeds normally.
- `ComponentBudget._spent` is still updated post-run regardless of `warn_only`.
- Behavior is consistent with `warn_only` semantics on `BudgetExceededError` from the core budget.

---

### US-5: Nested budgets inherit agent caps

As an engineer using nested budgets, I want a child budget's agent cap to be respected, and the parent's remaining budget to also act as a ceiling, consistent with how LangGraph and CrewAI adapters behave.

**Acceptance criteria:**
- When a child budget registers `b.agent("analyst", max_usd=0.20)` but the parent has only $0.05 remaining, the effective ceiling is $0.05.
- When the parent budget is exhausted, `AgentBudgetExceededError` is raised even if the agent's own cap is not yet reached.
- The adapter walks the parent chain (matching `_find_agent_cap` in `crewai.py`) to find the relevant `ComponentBudget`.

---

## 4. Success Metrics

All metrics are measurable within 60 days of release.

| Metric | Target | Measurement method |
|--------|--------|--------------------|
| Adapter is registered at import time | Zero regressions in existing test suite | CI: `pytest --cov=shekel` green |
| Per-agent spend attribution accuracy | Delta off by less than $0.0001 vs raw `b.spent` | Unit test: mock Runner, assert `ComponentBudget._spent == b.spent` |
| `AgentBudgetExceededError` raised correctly | 100% of pre-cap scenarios caught | Unit tests: cap-exceeded before run, mid-run not possible (pre-check only) |
| Silent skip when SDK absent | Zero `ImportError` propagation | Unit test: remove `agents` from `sys.modules`, assert no error on `budget().__enter__()` |
| No double-patch with nested budgets | `Runner.run` is patched exactly once for N nested budgets | Unit test: two nested budgets, assert `_patch_refcount == 2` and single wrapper |
| Patch is fully removed on `budget.__exit__()` | `Runner.run` is the original after context exits | Unit test: enter and exit, assert `Runner.run is original` |

---

## 5. In-Scope / Out-of-Scope

### In-scope (v1.1.0)

- Patching `Runner.run` (async classmethod)
- Patching `Runner.run_sync` (sync classmethod)
- Patching `Runner.run_streamed` (streaming classmethod — wrap generator, attribute spend after iteration)
- Pre-execution gate: check agent cap and parent budget before each runner call
- Post-execution spend attribution: compute delta and apply to `ComponentBudget._spent`
- Ref-counted patch install/remove (same pattern as `LangGraphAdapter`, `LangChainRunnerAdapter`)
- Silent skip when `openai-agents` not installed
- Registration via `ShekelRuntime.register(OpenAIAgentsRunnerAdapter)` in `_runtime.py`
- Reuse of `AgentBudgetExceededError` (already exists, semantics match)
- Test file: `tests/test_openai_agents_wrappers.py`

### Out-of-scope (v1.1.0)

- Patching `FunctionTool.on_invoke_tool` (already handled by the existing `OpenAIAgentsAdapter` for tool budgets)
- Tracing or logging individual handoff hops within a single `Runner.run` call
- Streaming token-level spend attribution (streaming spend is attributed as a delta after the stream is fully consumed)
- Integration with OpenAI Agents SDK's built-in tracing pipeline
- Support for Agents SDK versions prior to March 2025 launch
- Custom `on_agent_warn` callbacks (may be added in 1.2.0)

---

## 6. High-Level API Design

The adapter is **zero-configuration from the user's perspective**. The developer opens a budget context as usual; the adapter activates automatically.

### Track-only (no cap)

```python
from agents import Runner, Agent
from shekel import budget

agent = Agent(name="researcher", instructions="You are a research assistant.")

with budget() as b:
    result = await Runner.run(agent, "Summarize quantum computing.")

print(f"Researcher spent: ${b.spent:.4f}")
```

### Per-agent cap

```python
with budget(max_usd=2.00) as b:
    b.agent("researcher", max_usd=0.50)
    b.agent("writer", max_usd=1.00)

    research = await Runner.run(researcher_agent, "Research quantum computing.")
    draft = await Runner.run(writer_agent, "Write a summary.")
```

If `researcher_agent.name == "researcher"` and that agent's `ComponentBudget._spent >= 0.50`, the second `Runner.run("researcher")` raises `AgentBudgetExceededError` before the API call.

### Catching the error

```python
from shekel import AgentBudgetExceededError

try:
    result = await Runner.run(agent, "input")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' exceeded cap: ${e.spent:.4f} / ${e.limit:.2f}")
```

### Sync usage

```python
with budget(max_usd=1.00) as b:
    b.agent("classifier", max_usd=0.20)
    result = Runner.run_sync(classifier_agent, "Classify this ticket.")
```

---

## 7. Edge Cases the Product Must Handle

| Edge case | Required behavior |
|-----------|------------------|
| `agent.name` is `None` or empty string | Run freely under parent budget only; no `ComponentBudget` lookup attempted |
| Agent name registered in `b.agent(...)` but `agent.name` does not match | No cap applied for that runner call; run freely |
| `Runner.run` called outside any `budget()` context | Original behavior — no interception |
| Nested budgets: agent cap on child, global cap on parent | Gate checks child cap first, then walks up to parent; whichever fires first raises |
| Agent raises an exception during execution | Spend already tracked by `openai.py` provider wrapper; delta is still attributed before the exception propagates (catch, attribute, re-raise pattern) |
| `Runner.run_streamed` — stream not fully consumed | Spend delta attributed after the generator is exhausted; partial consumption yields partial attribution |
| Two concurrent `budget()` contexts (different asyncio tasks) | Each task's `get_active_budget()` returns its own context var value; no cross-contamination |
| `openai-agents` installed but `Runner` class moved or renamed in a future version | `AttributeError` caught in `install_patches`; adapter silently skips |
| Budget re-entered (session budget, multiple with-blocks) | Ref count resets correctly per `budget.__enter__` / `__exit__` cycle |
| `warn_only=True` budget | Gate raises no error but `b.spent` still updated; existing `warn_only` behavior is unchanged — adapter does not bypass this |
