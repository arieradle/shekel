---
title: Data Flow – How an LLM Call Passes Through Shekel
description: "Step-by-step data flow through shekel: from LLM API call interception through token extraction, cost calculation, budget check, and spend recording."
tags:
  - architecture
  - internals
  - llm-guardrails
  - cost-tracking
---

# Data Flow

## Library: one LLM call under a budget

1. User enters `with budget(max_usd=5.00):`.
2. `Budget.__enter__`: set `_active_budget` to this budget, call `apply_patches()` (refcount 1 → install all adapters).
3. User calls `client.chat.completions.create(...)` (or another patched method).
4. Patched wrapper runs: resolve provider, apply fallback model if active, call original; get response or stream.
5. If streaming: adapter's `wrap_stream` consumes the stream and yields chunks; at end, token counts are returned and used for cost.
6. Token extraction (adapter) → `calculate_cost` (pricing) → `budget._record_*` (update spent, check limits).
7. If over limit: raise `BudgetExceededError` (or `ToolBudgetExceededError` for tools). Optionally emit observability events.
8. On `with` exit: `remove_patches()` (refcount 0 → restore originals), clear `_active_budget`, emit exit events.

### Sequence diagram (library)

```mermaid
sequenceDiagram
    participant User
    participant Budget
    participant Patch
    participant Context
    participant Adapter
    participant Pricing
    participant Observability

    User->>Budget: with budget(max_usd=5):
    Budget->>Context: set_active_budget(self)
    Budget->>Patch: apply_patches()
    Patch->>Adapter: install_all()
    Note over Budget: refcount = 1

    User->>Patch: client.chat.completions.create(...)
    Patch->>Context: get_active_budget()
    Context-->>Patch: budget
    Patch->>Adapter: (fallback rewrite if needed)
    Patch->>Adapter: original(...)
    Adapter-->>Patch: response / stream
    Patch->>Adapter: extract_tokens / wrap_stream
    Adapter-->>Patch: input_tok, output_tok, model
    Patch->>Pricing: calculate_cost(...)
    Pricing-->>Patch: cost_usd
    Patch->>Budget: _record_* (spent, limits)
    Budget->>Observability: emit_event(on_cost_update, ...)
    alt over limit
        Budget-->>User: BudgetExceededError
    else ok
        Patch-->>User: response
    end

    User->>Budget: exit with-block
    Budget->>Patch: remove_patches()
    Note over Patch: refcount = 0 → restore originals
    Budget->>Context: clear active_budget
    Budget->>Observability: emit_event(on_budget_exit, ...)
```

## CLI: shekel run

1. User runs `shekel run agent.py --budget 5`.
2. CLI parses flags and optional `--budget-file` / env into budget kwargs.
3. Run layer (e.g. `_run_utils`) creates a `Budget` with those kwargs and enters it.
4. User script is executed (same process or subprocess depending on implementation); any patched SDK calls are tracked and enforced.
5. On script end, budget context exits; CLI reports spend and exit code (e.g. 1 if budget exceeded).

### Sequence diagram (CLI)

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant RunConfig
    participant RunUtils
    participant Budget
    participant Script

    User->>CLI: shekel run agent.py --budget 5
    CLI->>RunConfig: load_budget_file() / env
    RunConfig-->>CLI: budget kwargs
    CLI->>RunUtils: run with kwargs
    RunUtils->>Budget: budget(**kwargs).__enter__()
    RunUtils->>Script: execute agent.py
    loop Script runs
        Script->>Budget: (patched LLM calls)
        Budget->>Budget: record spend, check limits
    end
    Script-->>RunUtils: script exit
    RunUtils->>Budget: __exit__()
    RunUtils->>CLI: exit code, spend summary
    CLI->>User: exit 0 | 1, output
```
