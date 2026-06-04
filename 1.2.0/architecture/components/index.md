# Core Components

## 1. Budget and context lifecycle

| Module            | Responsibility                                                                                                                                                                                                                                                                     |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `shekel.__init__` | Exposes `budget()`, `with_budget`, `tool`, `Budget`, `TemporalBudget`, exceptions. `budget(spec="$5/hr", name="x")` returns a `TemporalBudget`; otherwise returns a `Budget`.                                                                                                      |
| `_budget.py`      | `Budget` class: context manager, USD/call/tool limits, warn_at, fallback, nested parent/child, session (accumulating) mode. On `__enter__`: push to context, call `_patch.apply_patches()`. On `__exit__`: call `_patch.remove_patches()`, pop context, emit observability events. |
| `_temporal.py`    | `TemporalBudget`: rolling-window budgets via spec string (e.g. `"$5/hr"`) or `window_seconds`. Uses `TemporalBudgetBackend` (default: `InMemoryBackend`). `__enter__` checks/resets window; each LLM call goes through backend `check_and_add`.                                    |
| `_context.py`     | `ContextVar` for the active budget. Ensures concurrent threads/tasks each have their own budget; no global shared state.                                                                                                                                                           |

## 2. Patching and providers

| Module                                                                             | Responsibility                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_patch.py`                                                                        | Ref-counted install/restore. `apply_patches()` increments refcount and on first entry calls `ADAPTER_REGISTRY.install_all()`. `remove_patches()` decrements and on last exit calls `ADAPTER_REGISTRY.remove_all()`. Provides shared wrapper logic: get active budget, apply fallback model rewrite, call adapter `extract_tokens` / `wrap_stream`, call `_pricing.calculate_cost`, record on budget, emit observability. |
| `providers/base.py`                                                                | `ProviderAdapter` ABC: `name`, `install_patches()`, `remove_patches()`, `extract_tokens()`, `detect_streaming()`, `wrap_stream()`. `ProviderRegistry` (singleton `ADAPTER_REGISTRY`): `register()`, `install_all()`, `remove_all()`.                                                                                                                                                                                     |
| `providers/openai.py`, `anthropic.py`, `litellm.py`, `gemini.py`, `huggingface.py` | Implement `ProviderAdapter` for each SDK. Patch the relevant completion/create methods; in the wrapper delegate to `_patch` helpers for token extraction, cost calculation, and budget recording.                                                                                                                                                                                                                        |

Nested `with budget():` blocks only patch once (refcount). All registered adapters are patched together; optional adapters (LiteLLM, Gemini, HuggingFace) register only if their dependencies are installed.

## 3. Pricing

| Module               | Responsibility                                                                                                                                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_pricing.py`        | Three-tier cost: (1) explicit `price_per_1k_tokens` override from budget, (2) bundled `prices.json` (exact + prefix match for versioned models), (3) optional `tokencost` for 400+ models. Unknown models: warn and return 0.0. |
| `shekel/prices.json` | Bundled per-model `input_per_1k` and `output_per_1k` in USD.                                                                                                                                                                    |

## 4. Tool budgets

| Module     | Responsibility                                                                                                                                                                                                                                                                                                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_tool.py` | `@tool(price=...)` decorator and `tool()` wrapper for callables. On invocation: `get_active_budget()`; if present, check tool limits, run function, then `_record_tool_call`. Framework-specific tool interception (LangChain, MCP, CrewAI, OpenAI Agents) is implemented inside the respective provider or integration layers so that agent tool dispatches are counted and capped. |

## 5. Observability

| Module                         | Responsibility                                                                                                                                                                                                   |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `integrations/base.py`         | `ObservabilityAdapter` interface: `on_cost_update`, `on_budget_exceeded`, `on_fallback_activated`, `on_budget_exit`, `on_autocap`, `on_window_reset`, `on_tool_call`, `on_tool_budget_exceeded`, `on_tool_warn`. |
| `integrations/registry.py`     | `AdapterRegistry`: register adapters, `emit_event(event_type, data)` to all. Exceptions in one adapter are logged; others still receive events.                                                                  |
| `integrations/langfuse.py`     | Langfuse adapter: updates spans with cost, budget hierarchy, circuit-break events.                                                                                                                               |
| `integrations/otel_metrics.py` | OpenTelemetry adapter: emits counters/gauges for cost, utilization, spend rate, fallback, tool calls, etc.                                                                                                       |
| `otel.py`                      | `ShekelMeter`: creates and registers the OTel metrics adapter; no-op if `opentelemetry-api` is not installed.                                                                                                    |

Budget and temporal code paths call `AdapterRegistry.emit_event(...)` at the appropriate points so Langfuse and OTel see the same events.

## 6. CLI

| Module           | Responsibility                                                                                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_cli.py`        | Click entrypoint `shekel`. Commands: `estimate`, `models`, `run`. `run` loads config from `--budget-file` (TOML) and env (`AGENT_BUDGET_USD`, etc.), builds budget kwargs, then delegates to run logic. |
| `_run_config.py` | Parses TOML budget file (`[budget]` section) into budget kwargs (e.g. `max_usd`, `warn_at`, `max_llm_calls`, `max_tool_calls`).                                                                         |
| `_run_utils.py`  | Executes the user script (e.g. `runpy.run_path` or subprocess) inside a budget context built from CLI/config. Handles exit codes and optional JSON output for spend summary.                            |

**Flow**: CLI → run_config + run_utils → budget() context → same library path (patch → providers → pricing → observability).
