# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/arieradle/shekel/compare/v0.2.7...HEAD
[0.2.7]: https://github.com/arieradle/shekel/compare/v0.2.6...v0.2.7
[0.2.6]: https://github.com/arieradle/shekel/compare/v0.2.5...v0.2.6
[0.2.5]: https://github.com/arieradle/shekel/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/arieradle/shekel/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/arieradle/shekel/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/arieradle/shekel/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/arieradle/shekel/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/arieradle/shekel/releases/tag/v0.2.0
