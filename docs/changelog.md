# Changelog

All notable changes to this project are documented here. For detailed information, see [CHANGELOG.md](https://github.com/arieradle/shekel/blob/main/CHANGELOG.md) on GitHub.

## [0.2.9] {#029}

### 🖥️ CLI Budget Enforcement — `shekel run`

Run any Python agent with a hard USD cap from the command line — zero code changes required.

```bash
shekel run agent.py --budget 5          # hard cap at $5
shekel run agent.py --budget 5 --warn-at 0.8   # warn at 80%
AGENT_BUDGET_USD=5 shekel run agent.py  # env var (Docker / CI)
```

- `shekel run SCRIPT [OPTIONS]` — wraps any Python script in-process; shekel's monkey-patches are already active when the script runs
- `--budget N` / `AGENT_BUDGET_USD=N` — USD cap; env var enables Docker/CI operator control without code changes
- `--warn-at F` — warn fraction 0.0–1.0 (e.g. `0.8` = warn at 80%)
- `--max-llm-calls N` / `--max-tool-calls N` — count-based caps
- `--warn-only` — log warning, never exit 1; soft guardrail for dev environments
- `--dry-run` — track costs only, no enforcement; implies `--warn-only`
- `--output json` — machine-readable spend line for log pipelines
- `--budget-file shekel.toml` — load limits from a TOML config file
- `Budget(warn_only=True)` — new parameter suppresses raises, fires warn callback instead
- GitHub Actions composite action: `.github/actions/enforce/action.yml`
- New docs: [CLI reference](cli.md) · [Docker & Containers](docker.md)
- Exit code 1 on budget exceeded — works as a CI pipeline gate with zero pipeline config

[Full CHANGELOG →](https://github.com/arieradle/shekel/blob/main/CHANGELOG.md#029)

---

## [0.2.8] {#028}

### 🔧 Tool Budgets

Cap agent tool call count and cost — stop runaway tool loops before they bankrupt you.

- `max_tool_calls` — hard cap on total dispatches, checked *before* each tool runs
- `tool_prices` — per-tool USD cost; unknown tools count at `$0` toward the cap
- `@tool` / `tool()` decorator — one line for any sync/async function or callable
- `ToolBudgetExceededError` — `tool_name`, `calls_used`, `calls_limit`, `usd_spent`, `framework`
- Auto-interception: LangChain `BaseTool`, MCP `ClientSession.call_tool`, CrewAI `BaseTool`, OpenAI Agents SDK `FunctionTool` — zero config
- `summary()` extended with tool spend breakdown by tool name and framework
- Four new OTel instruments: `shekel.tool.calls_total`, `shekel.tool.cost_usd_total`, `shekel.tool.budget_exceeded_total`, `shekel.tool.calls_remaining`
- 111 new unit tests (TDD)

### ⏱️ Temporal Budgets

Rolling-window LLM spend limits — enforce `$5/hr` per API tier, user, or agent.

- `budget("$5/hr", name="api-tier")` — string DSL
- `TemporalBudgetBackend` Protocol — bring your own Redis/Postgres backend
- `BudgetExceededError` enriched with `retry_after` and `window_spent`
- `on_window_reset` adapter event + `shekel.budget.window_resets_total` OTel counter

[Full CHANGELOG →](https://github.com/arieradle/shekel/blob/main/CHANGELOG.md#028)

---

## [0.2.7] {#027}

### 📡 OpenTelemetry Metrics Integration

Shekel now exposes LLM cost and budget lifecycle data via OpenTelemetry — filling the gap the OTel GenAI semantic conventions leave around cost and budget metrics.

**`ShekelMeter`** (`shekel/otel.py`) — Zero-config public entry point

```python
from shekel.otel import ShekelMeter

meter = ShekelMeter()          # uses global MeterProvider
# or
meter = ShekelMeter(meter_provider=my_provider, emit_tokens=True)
meter.unregister()             # remove from registry when done
```

Silent no-op when `opentelemetry-api` is not installed (`meter.is_noop is True`).

**8 new instruments:**

| Instrument | Type | Description |
|---|---|---|
| `shekel.llm.cost_usd` | Counter | Cost per LLM call |
| `shekel.llm.calls_total` | Counter | Call count per model |
| `shekel.llm.tokens_input_total` | Counter | Input tokens (opt-in) |
| `shekel.llm.tokens_output_total` | Counter | Output tokens (opt-in) |
| `shekel.budget.exits_total` | Counter | Budget exits by `status` |
| `shekel.budget.cost_usd` | UpDownCounter | Cumulative spend per budget |
| `shekel.budget.utilization` | Histogram | 0.0–1.0 on exit |
| `shekel.budget.spend_rate` | Histogram | USD/s on exit |
| `shekel.budget.fallbacks_total` | Counter | Fallback activations |
| `shekel.budget.autocaps_total` | Counter | Auto-cap events |

**Two new `ObservabilityAdapter` events:**

- `on_budget_exit(data)` — fires on every budget context exit (before parent propagation); `data` includes `status`, `spent_usd`, `utilization`, `duration_seconds`, `calls_made`, `model_switched`, `from_model`, `to_model`
- `on_autocap(data)` — fires when a child budget is silently reduced by the parent's remaining; `data` includes `child_name`, `parent_name`, `original_limit`, `effective_limit`

**Token payload in `on_cost_update`** — the event now includes `input_tokens` and `output_tokens` fields.

Install: `pip install shekel[otel]`

See [OTel Integration Guide](integrations/otel.md) for PromQL examples, cardinality guidance, and Grafana hints.

### Full Async Support for Gemini, HuggingFace, and Nested Budgets

`async with budget(...):` now supports the same full nesting logic as sync contexts — auto-capping, spend propagation, and per-task isolation via ContextVar all work identically.

**Gemini async** — `_gemini_async_wrapper` and `_gemini_async_stream_wrapper` added; `AsyncModels` patched automatically alongside sync `Models`.

**HuggingFace async** — `_huggingface_async_wrapper` and `_wrap_huggingface_stream_async` added; `AsyncInferenceClient` patched automatically.

```python
# Now works — full nesting with async context managers
async with budget(max_usd=10.00, name="workflow"):
    async with budget(max_usd=2.00, name="research"):
        result = await client.models.generate_content_async(...)
```

13 new async unit tests added for Gemini and HuggingFace. Integration test suites expanded with async streaming and `async with budget()` scenarios for OpenAI and Anthropic.

## [0.2.6] {#026}

### New Features

**`max_llm_calls` — limit budgets by call count**

- `budget(max_llm_calls=50)` raises `BudgetExceededError` after 50 LLM API calls
- Can be combined with `max_usd`: `budget(max_usd=1.00, max_llm_calls=20)`
- Works with fallback: `budget(max_usd=1.00, max_llm_calls=20, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})`

**LiteLLM provider adapter**

- Install with `pip install shekel[litellm]`
- Patches `litellm.completion` and `litellm.acompletion` (sync + async, including streaming)
- Enforces budgets and circuit-breaks across all 100+ providers LiteLLM supports (Gemini, Cohere, Ollama, Azure, Bedrock, Mistral, and more)
- Model names with provider prefix (e.g. `gemini/gemini-1.5-flash`) pass through to the pricing engine

## [0.2.5] - 2026-03-11

### 🔧 Extensible Provider Architecture

Shekel now has a pluggable architecture for adding new LLM provider support without modifying core code.

**ProviderAdapter** — Standard interface for any LLM provider
- 8 abstract methods: patching, token extraction, streaming, validation
- All providers (OpenAI, Anthropic, custom) implement this interface
- Clear contract for what shekel needs from a provider

**ProviderRegistry** — Central hub for provider management
- Thread-safe registration and lifecycle management
- Automatic patch installation and removal
- Provider discovery by name for fallback validation
- Decoupled from core code — no core changes needed for new providers

**Add your own provider in 3 steps:**
1. Implement `ProviderAdapter` interface
2. Register with `ADAPTER_REGISTRY.register(YourAdapter())`
3. Works everywhere automatically

**Community can now add:** Cohere, Replicate, vLLM, Mistral, Bedrock, Vertex AI, and others

### ✅ Validated with Real Integration Tests

The architecture is battle-tested with comprehensive end-to-end validation:

**Groq API** — 25+ integration tests
- Custom pricing and budget enforcement
- Nested budgets and cost attribution
- Streaming responses and concurrent calls
- Rate limiting and error handling
- Real API keys in CI

**Google Gemini API** — 30+ integration tests
- Multi-turn conversations and streaming
- JSON mode and function calling
- Token counting accuracy
- Budget enforcement and fallback
- Real API keys in CI

These test suites serve as **reference implementations** showing how to build a provider adapter.

### ⚙️ Production-Grade Reliability

- **Exponential backoff retry logic** — Gracefully handles rate limiting and transient failures
- **100+ integration test scenarios** — Comprehensive validation of architecture under load
- **Concurrent test stability** — Reduced flakiness when multiple providers are tested simultaneously
- **CI improvements** — Integration and performance tests run in parallel

### ✅ Quality Improvements

- **100+ integration test scenarios** — Comprehensive real API coverage
- **mkdocs integrity checks** — Prevent broken documentation links in CI
- **Better provider abstraction** — Easier to add new LLM provider support in the future

## [0.2.4] - 2026-03-11

### ✨ Langfuse Integration (New!)

Full LLM observability with zero configuration. See [Langfuse Integration Guide](integrations/langfuse.md) for complete documentation.

#### Feature #1: Real-Time Cost Streaming
- Automatic metadata updates after each LLM call
- Track: `shekel_spent`, `shekel_limit`, `shekel_utilization`, `shekel_last_model`
- Works with track-only mode (no limit)
- Supports custom trace names and tags

#### Feature #2: Nested Budget Mapping
- Nested budgets automatically create span hierarchy in Langfuse
- Parent budget → trace, child budgets → child spans
- Perfect waterfall view for multi-stage workflows
- Each span has its own budget metadata

#### Feature #3: Circuit Break Events
- WARNING events created when budget limits exceeded
- Event metadata: spent, limit, overage, model, tokens, parent_remaining
- Nested budget violations create events on child spans
- Easy filtering and alerting in Langfuse UI

#### Feature #4: Fallback Annotations
- INFO events created when fallback model activates
- Event metadata: from_model, to_model, switched_at, costs, savings
- Trace/span metadata updated to show fallback is active
- Fallback info persists across subsequent cost updates

### 🏗️ Adapter Pattern Architecture

- `ObservabilityAdapter` base class for integrations
- `AdapterRegistry` for managing multiple adapters
  - Thread-safe registration and event broadcasting
  - Error isolation (one adapter failure doesn't break others)
- `AsyncEventQueue` for non-blocking event delivery
  - Background worker thread processes events asynchronously
  - Queue drops old events if full (no blocking)
  - Graceful shutdown with timeout

### 📦 Optional Dependency Management
- New `shekel[langfuse]` extra for Langfuse integration
- Graceful import handling (works even if langfuse not installed)

### Technical Details
- Core event emission in `_patch.py::_record()` and `_budget.py::_check_limit()`
- Type-safe implementation with guards for Python 3.9+ compatibility
- All 267 tests passing (65 new integration tests), 95%+ coverage
- Zero performance impact: <1ms overhead per LLM call

## [0.2.3] - 2026-03-11

### 🌳 Nested Budgets (v0.2.3)

Hierarchical budget tracking for multi-stage AI workflows:

- Automatic spend propagation from child to parent on context exit
- Auto-capping: child budgets capped to parent's remaining budget
- Parent locking: parent cannot spend while child is active (sequential execution)
- Named budgets: names required when nesting for clear cost attribution
- Track-only children: `max_usd=None` for unlimited child tracking

### 📊 Rich Introspection API

- `budget.full_name` — Hierarchical path (e.g., `"workflow.research.validation"`)
- `budget.spent_direct` — Direct spend by this budget (excluding children)
- `budget.spent_by_children` — Sum of all child spend
- `budget.parent` — Reference to parent budget (`None` for root)
- `budget.children` — List of child budgets
- `budget.active_child` — Currently active child budget
- `budget.tree()` — Visual hierarchy of budget tree with spend breakdown

### 🛡️ Safety Rails

- Maximum nesting depth of 5 levels enforced
- Async nesting support (nested `async with budget()` contexts with same rules as sync)
- Zero/negative budget validation at `__init__`
- Spend propagation on all exceptions (money spent is money spent)

### Changes

- Budget variables always accumulate across uses — same variable, same accumulated state
- Both parent and child must have a `name` when creating nested contexts

### Fixed
- ContextVar token management now uses proper `.reset()` instead of manual `.set(None)`
- Patch reference counting no longer leaks when validation errors occur before patching
- Sibling budgets must have unique names under the same parent
