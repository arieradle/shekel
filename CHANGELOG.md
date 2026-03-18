# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-03-18

### Added

- **`ShekelRuntime`** (`shekel/_runtime.py`) — framework detection and adapter wiring scaffold; called automatically at `budget.__enter__()` / `__exit__()` (and async variants)
  - `ShekelRuntime.register(AdapterClass)` — class-level registry for framework adapters; adapters are probed once at budget open and released at budget close
  - `probe()` — activates all registered adapters; silently skips adapters that raise `ImportError` (framework not installed)
  - `release()` — deactivates adapters on budget exit; suppresses cleanup exceptions to avoid masking original errors

- **`ComponentBudget`** (`shekel/_budget.py`) — lightweight dataclass for per-component cap tracking (`name`, `max_usd`, `_spent`)

- **`Budget.node(name, max_usd)`** — register an explicit USD cap for a LangGraph node; returns `self` for chaining

- **`Budget.agent(name, max_usd)`** — register an explicit USD cap for a named agent (CrewAI / OpenClaw); returns `self` for chaining

- **`Budget.task(name, max_usd)`** — register an explicit USD cap for a named task (CrewAI); returns `self` for chaining

- **`Budget.chain(name, max_usd)`** — register an explicit USD cap for a named LangChain chain; returns `self` for chaining; enforced by `LangChainRunnerAdapter`

- **5 new exception subclasses** (`shekel/exceptions.py`), all inheriting from `BudgetExceededError`:
  - `NodeBudgetExceededError(node_name, spent, limit)` — raised when a LangGraph node exceeds its cap
  - `AgentBudgetExceededError(agent_name, spent, limit)` — raised when an agent exceeds its cap
  - `TaskBudgetExceededError(task_name, spent, limit)` — raised when a task exceeds its cap
  - `SessionBudgetExceededError(agent_name, spent, limit, window=None)` — raised when a rolling-window agent session exceeds its budget
  - `ChainBudgetExceededError(chain_name, spent, limit)` — raised when a LangChain chain exceeds its cap
  - `BudgetConfigMismatchError` — raised by `RedisBackend` when a budget name is reused with different limits/windows

- **`budget.tree()` enhancement** — renders registered node/agent/task/chain component budgets below the children block; shows `[node]`, `[agent]`, `[task]`, `[chain]` labels with spent / limit / percentage

- **`LangGraphAdapter`** (`shekel/providers/langgraph.py`) — transparent node-level circuit breaking for LangGraph; zero user code changes required
  - Patches `StateGraph.add_node()` at `budget.__enter__()` so every node — sync and async — gets a pre-execution budget gate
  - Pre-execution gate: raises `NodeBudgetExceededError` before the node body runs if the explicit node cap or parent budget is exhausted
  - Post-execution attribution: spend delta credited to `ComponentBudget._spent` so `budget.tree()` shows per-node costs
  - Reference-counted patch: nested budgets don't double-patch; restored when the last budget context closes
  - Automatically skipped (silent `ImportError`) when `langgraph` is not installed

- **`LangChainRunnerAdapter`** (`shekel/providers/langchain.py`) — transparent chain-level circuit breaking for LangChain; zero user code changes required
  - Patches `Runnable._call_with_config`, `_acall_with_config`, and `RunnableSequence.invoke`/`ainvoke`
  - Pre-execution gate: raises `ChainBudgetExceededError` before the chain body runs if the explicit chain cap or parent budget is exhausted
  - Reference-counted patch: same nesting semantics as `LangGraphAdapter`
  - Automatically skipped when `langchain_core` is not installed

- **Multi-cap temporal budget spec** — `"$5/hr + 100 calls/hr"` string DSL for simultaneous USD + call-count caps with independent rolling windows
  - `_parse_cap_spec()` — parses compound spec strings into a list of `(counter, limit, window_s)` triples
  - `TemporalBudget` supports `usd`, `llm_calls`, `tool_calls`, and `tokens` counters simultaneously
  - All-or-nothing atomicity: if any counter would exceed its limit, no counters are incremented

- **`RedisBackend`** (`shekel/backends/redis.py`) — synchronous Redis-backed rolling-window budget backend for distributed enforcement
  - Atomic all-or-nothing Lua script (single round-trip per call)
  - Lazy connection with connection pool reuse
  - Circuit breaker: stops calling Redis after N consecutive errors (configurable threshold + cooldown)
  - Fail-closed (default) or fail-open (`on_unavailable="open"`) on backend unavailability
  - `BudgetConfigMismatchError` when a budget name is reused with different limits/windows
  - `on_backend_unavailable` adapter event

- **`AsyncRedisBackend`** (`shekel/backends/redis.py`) — async version of `RedisBackend` for FastAPI, async LangGraph, and other async contexts; same semantics, all public methods are coroutines

- **`on_backend_unavailable` adapter event** (`shekel/integrations/base.py`) — fires before raising `BudgetExceededError` (fail-closed) or allowing through (fail-open); payload: `budget_name`, `error`

### Fixed

- **Nested budget node/chain cap enforcement** — node caps registered on an outer `budget()` context are now correctly enforced inside inner nested budget contexts; `_find_node_cap()` and `_find_chain_cap()` walk the parent chain to locate the cap

### Technical

- **245 new TDD tests**: 45 in `tests/test_runtime.py`, 41 in `tests/test_langchain_wrappers.py`, 36 in `tests/test_langgraph_wrappers.py`, 81 in `tests/test_distributed_budgets.py` (unit) + 419-line Docker integration suite in `tests/integrations/test_redis_docker.py`
- `shekel/__version__` bumped to `0.3.1`
- `Budget.chain`, `ChainBudgetExceededError`, `BudgetConfigMismatchError`, `RedisBackend`, `AsyncRedisBackend` all exported in `shekel.__all__`

## [0.2.9] - 2026-03-15

### Added

- **🖥️ `shekel run` CLI command** (`shekel/_cli.py`) — Run any Python agent script with budget enforcement from the command line; zero code changes required
  - `shekel run agent.py --budget 5` — hard USD cap; exits 1 on budget exceeded (CI-friendly)
  - `--budget N` / `AGENT_BUDGET_USD=N` — env-var fallback enables Docker/CI operator control without rebuilding images
  - `--warn-at F` — warn fraction 0.0–1.0 (e.g. `0.8` = warn at 80% of budget)
  - `--max-llm-calls N` / `--max-tool-calls N` — count-based caps
  - `--warn-only` — log warning, never exit 1; soft guardrail for dev environments
  - `--dry-run` — track costs only, no enforcement; implies `--warn-only`
  - `--output json` — machine-readable spend line (`{"spent":…,"limit":…,"calls":…,"status":…}`) for log pipelines
  - `--budget-file shekel.toml` — load limits from a TOML config file; CLI flags override file values
  - `--fallback-model` / `--fallback-at` — model fallback via CLI
  - Exit codes: `0` ok, `1` budget exceeded, `2` config error

- **`Budget(warn_only=True)`** (`shekel/_budget.py`) — new parameter; suppresses `BudgetExceededError` / `ToolBudgetExceededError` raises while still firing `on_warn` callbacks and tracking spend

- **`shekel._run_utils`** — provider detection (`detect_patched_providers`) and spend summary formatting (`format_spend_summary`) used by the `run` command

- **`shekel._run_config`** — `load_budget_file(path)` parses `shekel.toml` TOML budget config files; supports `max_usd`, `warn_at`, `max_llm_calls`, `max_tool_calls`

- **GitHub Actions composite action** (`.github/actions/enforce/action.yml`) — wrap any Python script in a budget-enforced GHA step; maps all `shekel run` flags to action inputs

- **Docker entrypoint docs** (`docs/docker.md`) — patterns for using `shekel run` as a container entrypoint; env-var budget control, TOML mount, JSON logging, shell script wrapper, GHA usage

- **85 new tests** across `test_cli_run.py`, `test_cli_run_output.py`, `test_cli_run_config.py`, `test_budget_warn_only.py`, `tests/performance/test_run_overhead.py` (TDD)

- **Performance**: `shekel run` on a no-op script completes in < 100 ms wall clock (benchmark median ~230 µs)

## [0.2.8] - 2026-03-15

### Added
- **⏱️ Temporal Budgets** (`shekel/_temporal.py`) — Rolling-window LLM spend enforcement; designed as a spec/state-separated precursor to future Redis-backed distributed budgets
  - `TemporalBudget` — subclass of `Budget` that enforces a spend limit per rolling time window (e.g. `$5/hr`)
  - `InMemoryBackend` — simple in-process backend (not thread-safe; documented); implements the `TemporalBudgetBackend` protocol for community extensibility
  - `TemporalBudgetBackend` Protocol — public, `@runtime_checkable`; implement to back `TemporalBudget` with Redis, Postgres, etc.
  - `_parse_spec()` — lenient string DSL parser: `"$5/hr"`, `"$10/30min"`, `"$1/60s"`, `"$5 per 1hr"` all work; calendar units (`day`, `week`, `month`) rejected with a clear error

- **`budget()` factory function** (`shekel/__init__.py`) — replaces `Budget as budget` class alias; `@overload`-typed for IDE support
  - `budget("$5/hr", name="api")` → `TemporalBudget`
  - `budget(max_usd=5.0, window_seconds=3600, name="api")` → `TemporalBudget`
  - `budget(max_usd=10.0)` → `Budget` (fully backward-compatible)

- **`BudgetExceededError` enrichment** (`shekel/exceptions.py`):
  - `retry_after: float | None` — seconds until current window resets (set by `TemporalBudget`; `None` for regular `Budget`)
  - `window_spent: float | None` — accumulated spend in the current window when the error was raised

- **`on_window_reset` adapter event** (`shekel/integrations/base.py`) — fires lazily on `TemporalBudget.__enter__` when the previous window has expired; payload: `budget_name`, `window_seconds`, `previous_spent`

- **`shekel.budget.window_resets_total`** OTel counter (`shekel/integrations/otel_metrics.py`) — incremented on each `on_window_reset` event; tagged with `budget_name`

- **`name=` required for `TemporalBudget`** — raises `ValueError` if omitted or empty; prevents ambiguous metric labels

- **Temporal-in-temporal nesting guard** — `TemporalBudget.__enter__` walks the active budget ancestor chain (up to 5 levels) and raises `ValueError` if any ancestor is also a `TemporalBudget`; regular `Budget` nesting inside a `TemporalBudget` (and vice versa) is allowed

- **Lazy window reset** — no background threads; window expiry is checked at `__enter__` time and `_record_spend` time

- **42 new tests** in `tests/test_temporal_budgets.py` (TDD, Groups A–H)

- **Development guidelines** updated (`CLAUDE.md`) — TDD required for all new development; 100% code coverage required before PR

- **🔧 Tool Budgets** — Cap agent tool call count and cost; stop runaway tool loops before they start
  - `max_tool_calls: int | None` — hard cap on total tool dispatches, checked *before* each tool runs
  - `tool_prices: dict[str, float] | None` — per-tool USD cost; unknown tools count at `$0` toward cap
  - `@tool` / `tool()` decorator (`shekel/_tool.py`) — wrap any sync/async function or callable; transparent pass-through when no budget is active
  - `ToolBudgetExceededError` (`shekel/exceptions.py`) — raised pre-dispatch; fields: `tool_name`, `calls_used`, `calls_limit`, `usd_spent`, `usd_limit`, `framework`
  - Auto-interception adapters (zero config): LangChain `BaseTool.invoke/ainvoke`, MCP `ClientSession.call_tool`, CrewAI `BaseTool._run/_arun`, OpenAI Agents SDK `FunctionTool.on_invoke_tool`
  - New `Budget` properties: `tool_calls_used`, `tool_calls_remaining`, `tool_spent`
  - `summary()` extended — tool spend section with per-tool breakdown by framework
  - Three new adapter events: `on_tool_call`, `on_tool_budget_exceeded`, `on_tool_warn`
  - Four new OTel instruments: `shekel.tool.calls_total`, `shekel.tool.cost_usd_total`, `shekel.tool.budget_exceeded_total`, `shekel.tool.calls_remaining`
  - 111 new unit tests in `tests/test_tool_budgets.py` (TDD, Groups A–T)
  - `pyproject.toml` version synced to `0.2.8`

### Technical
- `TemporalBudget._record_spend()` overrides `Budget._record_spend()` to call `backend.check_and_add()` before propagating cost to parent; raises `BudgetExceededError` with `retry_after` and `window_spent` if the window limit is exceeded
- Window reset detection happens at both `__enter__` (for `on_window_reset` event) and `_record_spend` (for correct `window_spent` payload when window expires mid-context)
- `shekel.__version__` bumped to `0.2.8`
- `TemporalBudget` exported in `shekel.__all__`
- `tool` and `ToolBudgetExceededError` exported in `shekel.__all__`

## [0.2.7] - 2026-03-14

### Added
- **📡 OpenTelemetry Metrics Integration** (`shekel/otel.py`, `shekel/integrations/otel_metrics.py`) — First-class OTel metrics surface for budget and LLM cost data, filling the gap left by the OTel GenAI semantic conventions which define no cost or budget instruments
  - `ShekelMeter` — Zero-config public entry point; silent no-op when `opentelemetry-api` is absent
  - Install via `pip install shekel[otel]`

- **Tier 2 per-call instruments** (`shekel.llm.*`) with `gen_ai.system`, `gen_ai.request.model`, and `budget_name` attributes:
  - `shekel.llm.cost_usd` (Counter) — cost of each LLM call
  - `shekel.llm.calls_total` (Counter) — total call count
  - `shekel.llm.tokens_input_total` / `shekel.llm.tokens_output_total` (Counters, opt-in via `emit_tokens=True`)

- **Tier 1 budget lifecycle instruments** (`shekel.budget.*`):
  - `shekel.budget.exits_total` (Counter) — budget context exits with `status=completed|exceeded|warned`
  - `shekel.budget.cost_usd` (UpDownCounter) — cumulative spend per budget
  - `shekel.budget.utilization` (Histogram, 0.0–1.0, clamped on exit)
  - `shekel.budget.spend_rate` (Histogram, USD/s, zero-division safe)
  - `shekel.budget.fallbacks_total` (Counter) — fallback activations with `from_model`/`to_model`
  - `shekel.budget.autocaps_total` (Counter) — child budget auto-cap events

- **Two new `ObservabilityAdapter` events** (`shekel/integrations/base.py`):
  - `on_budget_exit(exit_data)` — fired when any budget context exits (before parent spend propagation); payload includes `status`, `spent_usd`, `utilization`, `duration_seconds`, `calls_made`, `model_switched`, `from_model`, `to_model`
  - `on_autocap(autocap_data)` — fired when a child budget's limit is silently reduced by parent remaining; payload includes `child_name`, `parent_name`, `original_limit`, `effective_limit`

- **`_patch.py` token payload** — `on_cost_update` event now includes `input_tokens` and `output_tokens` fields, enabling per-call token accounting in custom adapters

- **Documentation**: `docs/integrations/otel.md` — attribute reference, PromQL query examples, cardinality guidance, Grafana hints

- **32 new tests** in `tests/test_otel_metrics.py` (TDD, Groups A–I)

- **Full async support for Gemini, HuggingFace, and nested budgets** (PR #19)
  - `async with budget(...):` now supports full nesting — `__aenter__`/`__aexit__` mirrors the sync implementation with the same auto-capping and spend propagation logic; ContextVar provides per-task isolation automatically
  - Gemini async: `_gemini_async_wrapper`, `_gemini_async_stream_wrapper`, `_wrap_gemini_stream_async` added to `_patch.py`; `AsyncModels` patched in `shekel/providers/gemini.py`
  - HuggingFace async: `_huggingface_async_wrapper`, `_wrap_huggingface_stream_async` added; `AsyncInferenceClient` patched in `shekel/providers/huggingface.py`
  - 13 new async unit tests for Gemini (7) and HuggingFace (6)
  - Expanded integration test suites: async streaming + `async with budget()` tests for OpenAI and Anthropic; new `tests/integrations/test_litellm_integration.py` with mock suite and real-API classes

### Technical
- `Budget.__enter__`/`__aenter__` now record `_enter_time = time.monotonic()` for duration measurement
- `Budget.__exit__`/`__aexit__` emit `on_budget_exit` before propagating spend to parent (so `spent_usd` reflects only the current budget's spend)
- `on_autocap` fires only when child's `effective_limit < max_usd` (genuine cap, not when child fits within parent)
- `pyproject.toml`: new `otel` extra (`opentelemetry-api>=1.0.0`), OTel packages added to dev deps, `mypy` `ignore_missing_imports` override for `opentelemetry.*`

## [0.2.6] - 2026-03-12

### Added
- **Google Gemini Provider Adapter** (`shekel/providers/gemini.py`) — Native support for the `google-genai` SDK
  - Patches `google.genai.models.Models.generate_content` (non-streaming) and `generate_content_stream` (streaming) as two separate methods
  - Token extraction from `response.usage_metadata.prompt_token_count` / `candidates_token_count`
  - Model name captured from `model` kwarg before the call (not available in Gemini response objects)
  - New pricing entries: `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-2.5-pro`
  - Install via `pip install shekel[gemini]`
- **HuggingFace Provider Adapter** (`shekel/providers/huggingface.py`) — Support for `huggingface_hub.InferenceClient`
  - Patches `InferenceClient.chat_completion` (the underlying method for `.chat.completions.create`)
  - OpenAI-compatible token extraction (`usage.prompt_tokens` / `usage.completion_tokens`)
  - Graceful handling when models don't return usage in streaming responses
  - Install via `pip install shekel[huggingface]`
- **Integration tests** for both new adapters with real API calls (skip gracefully on quota errors)
- **OpenAI integration test suite** — 20 tests covering sync, async, streaming, budget enforcement, callbacks, fallback, multi-turn conversation, and mock lifecycle
- **Anthropic integration test suite** — 18 tests covering sync, async, streaming, budget enforcement, callbacks, multi-turn conversation, and mock lifecycle
- **Examples**: `examples/gemini_demo.py`, `examples/huggingface_demo.py`
- **Documentation**: `docs/integrations/gemini.md`, `docs/integrations/huggingface.md`

## [0.2.5] - 2026-03-11

### Added
- **🔧 Extensible Provider Architecture** — Open design for community-contributed provider support
  - `ProviderAdapter` — Standard interface that all LLM providers implement (8 abstract methods)
  - `ProviderRegistry` — Central registry managing provider lifecycle, patching, and token extraction
  - Zero-touch provider onboarding: implement interface → register → automatic integration
  - Enables community to add Cohere, Replicate, vLLM, Mistral, and other providers without core changes
  - `shekel/providers/base.py` — Base classes for extensibility
- **✅ Validated with Real-World Integration Tests** — Proof the architecture works end-to-end
  - 25+ integration tests for Groq API (custom pricing, nested budgets, streaming, concurrent calls, rate limiting)
  - 30+ integration tests for Google Gemini API (multi-turn conversations, streaming, JSON mode, function calling)
  - Both suites use real API keys in CI pipeline to validate architecture
  - Provider adapters for Groq and Gemini included as reference implementations
- **⚙️ Production-Grade Reliability**
  - Exponential backoff retry logic — Gracefully handles rate limiting and transient failures
  - 100+ integration test scenarios — Comprehensive validation across multiple provider implementations
  - Concurrent test stability — Reduced flakiness when testing multiple providers in parallel
  - CI improvements — Integration and performance tests run in parallel with improved error isolation

### Technical
- New `shekel/providers/base.py`: `ProviderAdapter` ABC and `ProviderRegistry` singleton
- New provider implementations: `shekel/providers/groq.py` and `shekel/providers/gemini.py` (for testing/reference)
- All 300+ tests passing with 55+ new provider integration tests
- Zero performance impact on core budget tracking
- Graceful handling of provider-specific quirks (rate limits, response formats, token counting)

## [0.2.4] - 2026-03-11

### Added
- **🔭 Langfuse Integration** — Full LLM observability with zero configuration
  - **Feature #1: Real-Time Cost Streaming**
    - Automatic metadata updates after each LLM call
    - Track: `shekel_spent`, `shekel_limit`, `shekel_utilization`, `shekel_last_model`
    - Works with track-only mode (no limit)
    - Supports custom trace names and tags
  - **Feature #2: Nested Budget Mapping**
    - Nested budgets automatically create span hierarchy in Langfuse
    - Parent budget → trace, child budgets → child spans
    - Perfect waterfall view for multi-stage workflows
    - Each span has its own budget metadata
  - **Feature #3: Circuit Break Events**
    - WARNING events created when budget limits exceeded
    - Event metadata: spent, limit, overage, model, tokens, parent_remaining
    - Nested budget violations create events on child spans
    - Easy filtering and alerting in Langfuse UI
  - **Feature #4: Fallback Annotations**
    - INFO events created when fallback model activates
    - Event metadata: from_model, to_model, switched_at, costs, savings
    - Trace/span metadata updated to show fallback is active
    - Fallback info persists across subsequent cost updates
- **Adapter Pattern Architecture**
  - `ObservabilityAdapter` base class for integrations
  - `AdapterRegistry` for managing multiple adapters
    - Thread-safe registration and event broadcasting
    - Error isolation (one adapter failure doesn't break others)
  - `AsyncEventQueue` for non-blocking event delivery
    - Background worker thread processes events asynchronously
    - Queue drops old events if full (no blocking)
    - Graceful shutdown with timeout
- **Optional Dependency Management**
  - New `shekel[langfuse]` extra for Langfuse integration
  - Graceful import handling (works even if langfuse not installed)
- **Documentation**
  - Comprehensive Langfuse integration guide (`docs/langfuse-integration.md`)
  - Complete demo examples (`examples/langfuse/`)
  - Updated README with Langfuse quick start

### Technical
- Core event emission in `_patch.py::_record()` and `_budget.py::_check_limit()`
- Type-safe implementation with guards for Python 3.9+ compatibility
- All 267 tests passing (65 new integration tests), 95%+ coverage
- Zero performance impact: <1ms overhead per LLM call

## [0.2.3] - 2026-03-11

### Added
- **🌳 Nested Budgets** — Hierarchical budget tracking for multi-stage AI workflows
  - Automatic spend propagation from child to parent on context exit
  - Auto-capping: child budgets capped to parent's remaining budget
  - Parent locking: parent cannot spend while child is active (sequential execution)
  - Named budgets: names required when nesting for clear cost attribution
  - Track-only children: `max_usd=None` for unlimited child tracking
- **Rich Introspection API**:
  - `budget.full_name` — Hierarchical path (e.g., `"workflow.research.validation"`)
  - `budget.spent_direct` — Direct spend by this budget (excluding children)
  - `budget.spent_by_children` — Sum of all child spend
  - `budget.parent` — Reference to parent budget (`None` for root)
  - `budget.children` — List of child budgets
  - `budget.active_child` — Currently active child budget
  - `budget.tree()` — Visual hierarchy of budget tree with spend breakdown
- **Safety Rails**:
  - Maximum nesting depth of 5 levels enforced
  - Async nesting detection (raises clear error — deferred to future version)
  - Zero/negative budget validation at `__init__`
  - Spend propagation on all exceptions (money spent is money spent)
- **Enhanced Properties**:
  - `budget.limit` now returns effective limit (auto-capped if nested)
  - `budget.remaining` based on effective limit for nested budgets

### Changed
- **⚠️ BREAKING**: Budget variables now always accumulate across multiple `with` blocks
  - Previously: `budget(max_usd=10)` reset on each entry (unless `persistent=True`)
  - Now: Same budget variable = same accumulated state (matches Python's expected behavior)
  - Migration: Create new `Budget()` instances instead of relying on reset behavior
- **⚠️ BREAKING**: Names required when nesting budgets
  - Both parent and child must have `name` parameter when creating nested contexts
  - Validation happens at child `__enter__` with clear error messages
- **⚠️ DEPRECATED**: `persistent` parameter
  - Shows `DeprecationWarning` when `persistent=True` is explicitly used
  - Parameter kept for backwards compatibility but no longer has effect
  - Will be removed in v0.3.0

### Fixed
- ContextVar token management now uses proper `.reset()` instead of manual `.set(None)`
- Patch reference counting no longer leaks when validation errors occur before patching
- Sibling budgets must have unique names under the same parent

## [0.2.2] - 2026-03-09

### Added
- Prefix-based model name resolution — versioned model names like `gpt-4o-2024-08-06` now automatically resolve to the correct bundled pricing entry (`gpt-4o`); longest prefix wins
- CLI: `shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500`
- CLI: `shekel models [--provider openai|anthropic|google]`
- `shekel[cli]` optional dependency (`click>=8.0.0`)

## [0.2.1] - 2026-03-09

### Added
- `py.typed` marker (PEP 561) — IDEs and type checkers now pick up shekel's inline type annotations automatically

## [0.2.0] - 2026-03-09

### Added
- `@with_budget` decorator — wraps sync and async functions with a fresh budget per call
- Model fallback — `fallback="gpt-4o-mini"` switches to a cheaper model instead of raising when the limit is hit
- `hard_cap` parameter — absolute ceiling on fallback spending (default: `max_usd * 2`)
- `on_fallback` callback — fired when the fallback model is activated, receives `(spent, limit, fallback_model)`
- `model_switched`, `switched_at_usd`, `fallback_spent` properties on `budget`
- Persistent/session budgets — `persistent=True` accumulates spend across multiple `with` blocks
- `budget.reset()` method to clear persistent state
- `budget.summary()` and `budget.summary_data()` for formatted spend reports broken down by model
- Three-tier pricing: explicit override → bundled prices.json → tokencost (400+ models)
- `shekel[all-models]` optional dependency (includes `tokencost`)
- Unknown model now warns and returns $0 instead of raising `UnknownModelError`

### Changed
- `UnknownModelError` is kept for backwards compatibility but no longer raised internally

[Unreleased]: https://github.com/arieradle/shekel/compare/v0.2.8...HEAD
[0.2.8]: https://github.com/arieradle/shekel/compare/v0.2.7...v0.2.8
[0.2.7]: https://github.com/arieradle/shekel/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/arieradle/shekel/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/arieradle/shekel/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/arieradle/shekel/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/arieradle/shekel/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/arieradle/shekel/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/arieradle/shekel/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/arieradle/shekel/releases/tag/v0.2.0
