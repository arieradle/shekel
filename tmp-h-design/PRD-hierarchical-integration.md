# PRD: Hierarchical Budget Enforcement for Shekel

**Status:** Draft
**Date:** 2026-03-15
**Author:** Elish
**Version:** 1.0

---

## 1. Problem Statement

Shekel today is a circuit breaker at the LLM call and tool call level. It stops individual expensive calls. It cannot stop:

- A LangGraph node that loops 5,000 times at $0.001/call — no single call trips the breaker, but the run costs $5
- A rogue CrewAI agent monopolizing crew budget while other agents sit idle
- An OpenClaw always-on agent silently accumulating $3,600/month from heartbeat calls

These are real, documented failures. Developers are losing hundreds to thousands of dollars to patterns that a call-level circuit breaker is architecturally incapable of catching.

The market response — Langfuse, LangSmith, Helicone, Portkey — is **observability** (show you what happened). Shekel's position is **enforcement** (stop it before it happens). No tool in the market today provides in-process, per-component, multi-level budget enforcement without a proxy server.

---

## 2. Goals

1. Extend shekel's circuit breaker from Level 1 (LLM/tool calls) to all four abstraction levels present in the running process
2. Maintain 100% backward compatibility — existing `budget()` usage must not change
3. Zero configuration for the common case — auto-detect and auto-instrument all available frameworks
4. Progressive disclosure — explicit per-component caps available when needed, not required
5. Keep the install story: `pip install shekel`, one line of code

## 3. Non-Goals

- Observability / cost dashboards (that's Langfuse, LangSmith)
- Proxy-based enforcement (that's LiteLLM, Portkey)
- Recovery logic — shekel throws, frameworks recover
- Supporting frameworks not yet released or documented
- Modifying any upstream framework (no PRs to LangGraph, CrewAI, etc.)

---

## 4. Users

**Primary: Python developers building LLM-powered agents**
- Use LangGraph, CrewAI, OpenAI Agents SDK, or OpenClaw
- Already know `with budget(max_usd=5): ...`
- Pain: unexpected bills from agent loops, rogue agents, always-on accumulation

**Secondary: Teams deploying agents in production**
- Want org-level policy ("no single run exceeds $10")
- Want per-feature cost attribution for internal billing
- Want to adopt gradually: showback before chargeback

---

## 5. User Stories

### Phase 1 Foundation — ShekelRuntime (v0.3.1)

**US-01:** As a developer, when I open a `budget()` context, shekel automatically detects which frameworks I have installed and instruments them — I don't need to configure anything.

**US-02:** As a developer, I can declare explicit per-node, per-agent, or per-task caps with `b.node()`, `b.agent()`, `b.task()` — using vocabulary I already know from the framework I'm using.

**US-03:** As a developer, `budget.tree()` shows me a spend breakdown by detected level (session → agent → node → call) so I can see which component is driving cost.

### Phase 2 — LangGraph Layer (v0.4)

**US-04:** As a LangGraph developer, when a node exceeds its cap, I get a `NodeBudgetExceededError` — not a generic `BudgetExceededError` — so I know exactly which node tripped and can handle it specifically.

**US-05:** As a LangGraph developer, I can set per-node caps:
```python
with budget(max_usd=5.00) as b:
    b.node("fetch_data", max_usd=0.50)
    graph.invoke(...)
```

**US-06:** As a LangGraph developer, without any explicit node caps, the parent budget still enforces the total — and `budget.tree()` shows me per-node attribution so I can decide later which nodes to cap explicitly.

**US-07:** As a LangGraph developer, a looping node that fires hundreds of times is circuit-broken before it exhausts the parent budget — no single call is expensive, but the loop is caught.

### Phase 3 — CrewAI Layer (v0.5)

**US-08:** As a CrewAI developer, individual agent caps prevent one agent from consuming the entire crew budget:
```python
with budget(max_usd=10.00) as b:
    b.agent("researcher", max_usd=3.00)
    b.agent("writer", max_usd=2.00)
    crew.kickoff()
```

**US-09:** As a CrewAI developer, a task that exceeds its cap is circuit-broken *before* it starts (pre-task check on `TaskStartedEvent`) — zero wasted spend.

**US-10:** As a CrewAI developer, I get `AgentBudgetExceededError` or `TaskBudgetExceededError` — not a generic error — so my error handling can make intelligent decisions (retry with cheaper model, skip task, abort crew).

### Phase 4 — Loop Detection (v0.6)

**US-11:** As a developer, if my agent's spend rate spikes to 3× its rolling baseline within a short window, shekel circuit-breaks before the absolute limit is hit — catching runaway loops early.

**US-12:** As a developer, I can configure the velocity threshold:
```python
with budget(max_usd=10.00, loop_detection_multiplier=3.0, loop_detection_window=60):
    graph.invoke(...)
```

### Phase 5 — Tiered Thresholds (v0.7)

**US-13:** As a developer, I can configure N enforcement tiers instead of just warn + hard stop:
```python
with budget(max_usd=5.00, tiers=[
    (0.50, "warn"),
    (0.75, "fallback:gpt-4o-mini"),
    (0.90, "disable_tools"),
    (1.00, "stop"),
]):
    graph.invoke(...)
```

### Phase 6 — OpenClaw Layer (v0.8)

**US-14:** As an OpenClaw developer, I can enforce a rolling-window budget per agent session:
```python
with budget("$5/day") as b:
    b.agent("my_assistant", max_usd=2.00)
    openclaw_agent.run()
```

**US-15:** As an OpenClaw developer, when an agent session budget is exhausted it is suspended — not killed. Other agents on the same Gateway continue running.

### Phase 7 — DX Layer (v1.0)

**US-16:** As a developer adopting shekel, I can start in showback mode — full tracking and attribution, zero enforcement — then flip to chargeback when I'm confident:
```python
with budget(max_usd=5.00, mode="showback"):  # never raises
    graph.invoke(...)
```

**US-17:** As a team lead, I can tag spend for cost attribution:
```python
@tool(price=0.01, tags=["search", "feature-x"])
def web_search(query: str) -> str: ...

budget.summary(group_by="tags")  # cost by feature
```

---

## 6. Functional Requirements

### FR-01: ShekelRuntime (v0.3.1)
- Probe for installed frameworks once at `budget.__enter__()`
- Detection is silent — no logs, no warnings if a framework is not installed
- `Budget` gains `.node(name, max_usd)`, `.agent(name, max_usd)`, `.task(name, max_usd)` methods
- Child budgets created by these methods roll up to the parent
- `budget.tree()` renders the full hierarchy

### FR-02: LangGraph adapter (v0.4)
- Patch `StateGraph.add_node()` when `langgraph` is detected
- Every registered node function is wrapped with a pre-execution budget gate
- Gate checks: explicit node cap (if set) → parent budget remaining → record attribution
- `NodeBudgetExceededError` raised with fields: `node_name`, `spent`, `limit`
- Async node functions wrapped with async budget gate
- Patch is reference-counted: applied on first budget open, restored when last budget closes

### FR-03: CrewAI adapter (v0.5)
- Register `ShekelEventListener(BaseEventListener)` on `crewai_event_bus` at budget open
- Deregister at budget close
- Subscribe to: `TaskStartedEvent`, `AgentExecutionStartedEvent`, `LLMCallCompletedEvent`, `TaskFailedEvent`
- Pre-task check raises `TaskBudgetExceededError` before task body executes
- Pre-agent check raises `AgentBudgetExceededError` before agent executes
- `AgentBudgetExceededError` fields: `agent_name`, `spent`, `limit`
- `TaskBudgetExceededError` fields: `task_name`, `spent`, `limit`

### FR-04: Loop detection (v0.6)
- Track spend rate as rolling average over configurable window (default: 60s)
- Circuit-break if instantaneous rate exceeds `loop_detection_multiplier × baseline` (default: 3×)
- Configurable via `budget(loop_detection_multiplier=3.0, loop_detection_window=60)`
- Default: disabled (opt-in)

### FR-05: Tiered thresholds (v0.7)
- `tiers` parameter accepts list of `(fraction, action)` tuples
- Actions: `"warn"`, `"fallback:<model>"`, `"disable_tools"`, `"stop"`
- Applied at all active levels (parent and children)
- Backward compatible: existing `warn_at` + `fallback` still work

### FR-06: OpenClaw adapter (v0.8)
- Detect `openclaw` package at budget open
- Hook into `openclaw-sdk` agent lifecycle events
- Use `TemporalBudget` as the default budget type for OpenClaw contexts
- Session circuit-break suspends agent, does not kill Gateway
- `SessionBudgetExceededError` fields: `agent_name`, `spent`, `limit`, `window`

### FR-07: DX layer (v1.0)
- `mode="showback"` — track everything, raise nothing
- `mode="chargeback"` — default, existing behavior
- `tags` parameter on `@tool` decorator
- `budget.summary(group_by="tags")` output

---

## 7. Non-Functional Requirements

- **100% backward compatibility** — all existing tests must pass unchanged
- **100% code coverage** on all new code (project standard)
- **Zero required configuration** for implicit mode
- **Optional dependencies** — `langgraph`, `crewai`, `openclaw-sdk` are all optional; absence is silent
- **Thread and async safe** — `contextvars.ContextVar` used for budget propagation (already the pattern)
- **Performance** — budget gate overhead < 1ms per node/agent/task check

---

## 8. Exception Hierarchy

Extending the existing pattern:

```python
BudgetExceededError               # existing base — unchanged
├── NodeBudgetExceededError       # new: LangGraph node
├── AgentBudgetExceededError      # new: agent (CrewAI, OpenClaw)
├── TaskBudgetExceededError       # new: task (CrewAI)
└── SessionBudgetExceededError    # new: session (OpenClaw)

ToolBudgetExceededError           # existing — unchanged
```

All new exceptions inherit `BudgetExceededError`. Existing `except BudgetExceededError` catches everything.

---

## 9. Success Metrics

- LangGraph users can set per-node caps with one line of code
- CrewAI users can isolate rogue agent spend without stopping the crew
- `budget.tree()` shows per-level spend attribution out of the box
- Zero breaking changes — all v0.2.x tests pass on v0.3.1+
- Competitor gap: AgentBudget (30 stars) has no hierarchy or per-task enforcement — shekel ships both
