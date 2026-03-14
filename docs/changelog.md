# Changelog

All notable changes to this project are documented here. For detailed information, see [CHANGELOG.md](https://github.com/arieradle/shekel/blob/main/CHANGELOG.md) on GitHub.

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
