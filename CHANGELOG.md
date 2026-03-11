# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/arieradle/shekel/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/arieradle/shekel/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/arieradle/shekel/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/arieradle/shekel/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/arieradle/shekel/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/arieradle/shekel/releases/tag/v0.2.0
