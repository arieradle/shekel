# Overview

## High-level design

Shekel is an **in-process, zero-config** LLM cost governance library. It does not require API keys, external services, or global initialization. It works by:

1. **Monkey-patching** provider SDKs (OpenAI, Anthropic, LiteLLM, Gemini, HuggingFace) when a budget context is entered
2. **Tracking spend** in a thread- and async-safe way via `ContextVar`
3. **Enforcing limits** (USD, call count, tool count, or temporal windows) before or after each intercepted call
4. **Restoring** original SDK methods when the last budget context exits (ref-counted)

## Entry points

Two entry points exist:

- **Library**: `with budget(max_usd=5.00): run_agent()` — patches apply for the duration of the context.
- **CLI**: `shekel run agent.py --budget 5` — runs the script in a subprocess with a budget context wrapping the execution.

## Component diagram

```mermaid
flowchart TB
    subgraph User["User code / CLI"]
        U1["with budget(max_usd=5): ..."]
        U2["shekel run agent.py --budget 5"]
    end

    subgraph API["shekel.__init__"]
        B["budget() → Budget | TemporalBudget"]
        W["with_budget()"]
        T["tool()"]
    end

    subgraph Core["Core"]
        BUDGET["_budget.py\nBudget / TemporalBudget"]
        PATCH["_patch.py\napply/remove_patches\nADAPTER_REGISTRY"]
        CTX["_context.py\nContextVar\nactive_budget"]
    end

    subgraph Providers["providers/"]
        OAI["OpenAIAdapter"]
        ANT["AnthropicAdapter"]
        LIT["LiteLLMAdapter"]
        GEM["GeminiAdapter"]
        HF["HuggingFaceAdapter"]
    end

    subgraph Support["Support"]
        PRICE["_pricing.py\nprices.json\ncalculate_cost"]
        TOOL["_tool.py\n@tool\nget_active_budget"]
    end

    subgraph Observability["integrations/"]
        LANG["LangfuseAdapter"]
        OTL["_OtelMetricsAdapter"]
        REG["AdapterRegistry"]
    end

    User --> API
    API --> BUDGET
    API --> PATCH
    API --> CTX
    BUDGET <--> PATCH
    PATCH --> Providers
    PATCH --> REG
    BUDGET --> PRICE
    TOOL --> CTX
    REG --> LANG
    REG --> OTL
```

Next: [Core Components](components.md)
