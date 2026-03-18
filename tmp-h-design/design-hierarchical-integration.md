# Design Decision: Hierarchical Budget Enforcement

**Status:** Draft
**Date:** 2026-03-15
**Author:** Elish

---

## Context

Shekel currently enforces budgets as a flat circuit breaker at the LLM call and tool call level. This catches expensive individual calls but is blind to failure modes that only emerge at higher abstraction levels:

- A LangGraph node looping 5,000 times at $0.001/call — no single call trips the breaker
- A rogue CrewAI agent monopolizing crew budget while other agents wait
- An OpenClaw always-on agent accumulating cost from silent heartbeat calls over hours

Each failure mode requires a circuit breaker at a different level. The call-level breaker alone cannot protect against them.

---

## Decision: Layered Circuit Breaker Architecture

Shekel enforces budgets at every abstraction level that can be detected in the running process. Each level catches a distinct class of failure.

### The Four Levels

```
Level 4 — Session/Orchestrator   OpenClaw agents          temporal accumulation
Level 3 — Agent/Task             CrewAI, OpenAI Agents    rogue agent monopolization
Level 2 — Node/Subgraph          LangGraph                loop/retry spirals
Level 1 — LLM/Tool call          all frameworks           single expensive call (today)
```

**Each level is an independent circuit breaker.** A trip at Level 2 (node) does not automatically kill the Level 3 (agent) or Level 4 (session) budget. The parent framework decides whether to absorb the exception, route to a fallback, or propagate upward. Shekel enforces; the framework recovers.

**All detected levels are active simultaneously.** If LangGraph runs inside a CrewAI task inside an OpenClaw session, all three levels instrument and enforce independently, with child budgets rolling up to parents.

---

## Detection Strategy

Shekel probes for available frameworks **once, at budget open** (`__enter__` / `__aenter__`). This is the correct semantic moment: the developer has declared intent to enforce a budget, and frameworks in use are already imported.

Detection order (top-down):

```python
# ShekelRuntime.probe() — called on budget open
1. try: import openclaw      → activate SessionAdapter
2. try: import crewai        → activate CrewAIAdapter (BaseEventListener)
3. try: import langgraph     → activate LangGraphAdapter (add_node patch)
4. try: import openai.agents → activate OpenAIAgentsAdapter (guardrail)
5. always                    → LLM + Tool adapters (today's behavior)
```

Frameworks not installed are silently skipped. No configuration required.

---

## API Design

### Principle: zero new syntax for the common case

The existing `budget()` API is unchanged. Auto-instrumentation is silent. Developers who don't know about hierarchical integration get it for free.

```python
# Nothing changes — shekel auto-instruments all detected levels
with budget(max_usd=5.00):
    graph.invoke(...)
```

**Implicit mode behavior:** no per-component cap. Every detected level gets attribution and spend tracking. The parent budget is the only enforced limit. When the parent is exhausted, whichever component is running at that moment receives the exception.

### Explicit overrides — only when you need per-component caps

```python
with budget(max_usd=5.00) as b:
    b.node("fetch_data", max_usd=0.50)      # LangGraph node cap
    b.node("summarize", max_usd=1.00)       # LangGraph node cap
    b.agent("researcher", max_usd=1.50)     # CrewAI / OpenClaw agent cap
    b.task("write_report", max_usd=0.50)    # CrewAI task cap
    graph.invoke(...)
```

**Method names mirror the framework's own vocabulary.** A LangGraph developer recognizes `.node()`. A CrewAI developer recognizes `.agent()` and `.task()`. No new vocabulary to learn.

**Unregistered components** (nodes/agents/tasks without explicit caps) share the parent's remaining budget uncapped. They are always tracked and attributed.

### Temporal budgets for always-on runtimes

For OpenClaw and any persistent agent runtime, use the existing `TemporalBudget`:

```python
# Rolling-window enforcement — resets every hour
with budget("$5/hr") as b:
    b.agent("my_assistant", max_usd=2.00)
    openclaw_agent.run()
```

Flat caps (`max_usd`) apply to single invocations. Temporal caps (`$N/hr`, `$N/day`) apply to always-on runtimes. Both can coexist in a hierarchy.

---

## Auto-Instrumentation per Level

Each level uses the framework's native extensibility hook. No framework internals are bypassed.

### Level 1 — LLM/Tool calls (today)

**Mechanism:** Monkey-patch provider SDK methods at budget open. Restore on budget close.
**Hook point:** `openai.resources.chat.completions.Completions.create`, `anthropic.messages.Messages.create`, etc.
**Status:** Implemented.

### Level 2 — LangGraph nodes

**Mechanism:** Patch `StateGraph.add_node()` at import time. Every node function is wrapped with a budget gate before it is registered in the graph.

```python
# What shekel does transparently:
original_add_node = StateGraph.add_node

def patched_add_node(self, node_name, fn, **kwargs):
    wrapped = _budget_gate(node_name, fn)
    return original_add_node(self, node_name, wrapped, **kwargs)
```

**Budget gate behavior:**
- Check if active budget has an explicit cap for this node → enforce it
- If no explicit cap → check parent budget remaining → enforce parent
- Record node attribution regardless

**Why this hook:** fires before any node body runs, requires zero modification to user node functions, works for all node types (sync, async, subgraph).

### Level 3 — CrewAI agents and tasks

**Mechanism:** Instantiate `ShekelEventListener(BaseEventListener)` and register it on `crewai_event_bus` at budget open. Deregister on budget close.

**Events subscribed:**

| Event | Action |
|---|---|
| `TaskStartedEvent` | Check task budget cap → circuit-break before task runs if exceeded |
| `AgentExecutionStartedEvent` | Check agent budget cap → circuit-break before agent runs |
| `LLMCallCompletedEvent` | Accumulate spend against agent + task child budgets |
| `TaskFailedEvent` | Record failure attribution |

**Why this hook:** CrewAI's intended extensibility mechanism. Shekel becomes a first-class crew citizen, not a monkey-patch. Pre-task event fires before any LLM call is made — clean circuit break with zero wasted spend.

### Level 3 — OpenAI Agents SDK

**Mechanism:** Register a `ShekelBudgetGuardrail` as an input guardrail on `Runner` at budget open.

**Guardrail behavior:** Before each agent turn, check remaining budget. If exhausted, raise `InputGuardrailTripwireTriggered` with budget context. The SDK's native exception handling propagates it to the caller.

**Why this hook:** Repurposes the content-policy guardrail system as a cost-policy guardrail. No monkey-patching required.

### Level 4 — OpenClaw sessions

**Mechanism:** Hook into `openclaw-sdk` agent lifecycle at budget open via the SDK's agent event callbacks.

**Budget type:** `TemporalBudget` (rolling window) — not flat cap. OpenClaw is an always-on runtime; per-session rolling budgets are the correct primitive.

**Circuit break behavior:** When session budget is exhausted, the agent enters a suspended state. It does not kill the Gateway process. Other agents on the same Gateway continue unaffected.

---

## Exception Hierarchy

Consistent with shekel's existing pattern (`BudgetExceededError`, `ToolBudgetExceededError`):

```python
BudgetExceededError               # base — catch-all, today's exception
├── NodeBudgetExceededError       # LangGraph node exceeded its cap
├── AgentBudgetExceededError      # agent exceeded its cap (CrewAI, OpenClaw)
├── TaskBudgetExceededError       # task exceeded its cap (CrewAI)
└── SessionBudgetExceededError    # session exceeded rolling-window cap (OpenClaw)
```

**Catch-all pattern** — works with all existing code, no changes needed:
```python
try:
    graph.invoke(...)
except BudgetExceededError as e:
    print(f"Budget exceeded: {e.spent:.4f} / {e.limit:.4f} USD")
```

**Level-specific handling** — opt-in for recovery logic:
```python
try:
    crew.kickoff()
except TaskBudgetExceededError as e:
    print(f"Task '{e.task_name}' exceeded its ${e.limit:.2f} cap")
    # retry with cheaper model, skip task, etc.
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' exceeded its ${e.limit:.2f} cap")
except BudgetExceededError:
    # crew-level budget exhausted
    raise
```

All level-specific exceptions carry the same core fields as `BudgetExceededError` (`spent`, `limit`) plus a level-specific identifier (`node_name`, `agent_name`, `task_name`).

---

## Propagation Contract

**Shekel's responsibility:** throw the right exception at the right level.
**Framework's responsibility:** decide whether to absorb, route, or escalate.

```
NodeBudgetExceededError thrown
    → LangGraph catches it (conditional edge / error node) OR
    → propagates to AgentBudgetExceededError context (if inside CrewAI task) OR
    → propagates to top-level budget() context
```

Shekel does not implement recovery logic. Recovery is the framework's domain — LangGraph has conditional edges, CrewAI has task callbacks, OpenAI Agents SDK has guardrail handlers.

---

## Roadmap

| Phase | Deliverable |
|---|---|
| v0.3 | `ShekelRuntime` — explicit detection + adapter wiring class. Two-tier implicit/explicit API. |
| v0.4 | LangGraph Level 2 — `add_node()` patch, `NodeBudgetExceededError`, `.node()` explicit API |
| v0.5 | CrewAI Level 3 — `BaseEventListener`, `AgentBudgetExceededError`, `TaskBudgetExceededError`, `.agent()` / `.task()` API |
| v0.6 | Loop detection — rate-of-change circuit breaker (velocity-based, not just threshold) |
| v0.7 | Tiered thresholds — N enforcement tiers (warn / fallback / disable tools / hard stop) |
| v0.8 | OpenClaw Level 4 — `openclaw-sdk` adapter, `SessionBudgetExceededError`, `TemporalBudget` per agent |
| v1.0 | Showback mode, budget tags, system-wide `ulimit`-style defaults |
| Post-1.0 | Cross-process budget spans, sampling mode, priority-aware preemption |

---

## Open Questions

These require further investigation before implementation:

- **Q1:** Does Lobster (OpenClaw's YAML workflow engine) expose Python hooks for task start/end, or is all orchestration opaque to the SDK?
- **Q2:** In LangGraph, does `add_node()` patching handle async node functions and subgraph nodes correctly in all versions?
- **Q3:** When a CrewAI crew runs tasks in parallel, does `BaseEventListener` fire on the correct thread/async context for `contextvars` budget lookup?
- **Q4:** Can `ShekelBudgetGuardrail` (OpenAI Agents SDK) access the ContextVar budget from a guardrail callback, or does the SDK run guardrails in a separate context?
- **Q5:** What is the correct state value for a LangGraph node that is circuit-broken mid-execution — empty dict, sentinel, or should shekel inject a configurable default?
