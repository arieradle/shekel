# Changelog

All notable changes to this project are documented here. For detailed information, see [CHANGELOG.md](https://github.com/arieradle/shekel/blob/main/CHANGELOG.md) on GitHub.

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
- Async nesting detection (raises clear error — deferred to future version)
- Zero/negative budget validation at `__init__`
- Spend propagation on all exceptions (money spent is money spent)

### Changes

!!! warning "BREAKING CHANGES"

    **Budget Variables Now Always Accumulate**

    - Previously: `budget(max_usd=10)` reset on each entry (unless `persistent=True`)
    - Now: Same budget variable = same accumulated state (matches Python's expected behavior)
    - Migration: Create new `Budget()` instances instead of relying on reset behavior

    **Names Required When Nesting**

    - Both parent and child must have `name` parameter when creating nested contexts
    - Validation happens at child `__enter__` with clear error messages

!!! deprecated "Deprecated"

    **persistent Parameter**

    - Shows `DeprecationWarning` when `persistent=True` is explicitly used
    - Parameter kept for backwards compatibility but no longer has effect
    - Will be removed in v0.3.0

### Fixed
- ContextVar token management now uses proper `.reset()` instead of manual `.set(None)`
- Patch reference counting no longer leaks when validation errors occur before patching
- Sibling budgets must have unique names under the same parent
