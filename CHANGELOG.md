# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

## [0.1.1] - 2026-03-08

### Fixed
- Ruff lint errors: replaced `Optional[X]` with `X | None`, removed unused imports, fixed `Generator` import source

## [0.1.0] - 2024-03-08

### Added
- `budget()` context manager with sync and async support
- `BudgetExceededError` with spend/limit/model/token details
- Monkey-patching for OpenAI `ChatCompletions.create` (sync + async + streaming)
- Monkey-patching for Anthropic `Messages.create` (sync + async + streaming)
- `ContextVar`-based isolation for thread-safe and async-safe budget tracking
- Ref-counted patching (only patches once for nested contexts)
- `warn_at` threshold with optional `on_exceed` callback
- `price_per_1k_tokens` override for custom/unlisted models
- Built-in pricing for 10 models (GPT-4o, GPT-4o-mini, o1, o1-mini, GPT-3.5-turbo, Claude 3.5 Sonnet, Claude 3 Haiku, Claude 3 Opus, Gemini 1.5 Flash, Gemini 1.5 Pro)
- Track-only mode (`budget()` with no `max_usd`)
- LangGraph integration example

[Unreleased]: https://github.com/arieradle/shekel/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/arieradle/shekel/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/arieradle/shekel/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/arieradle/shekel/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/arieradle/shekel/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/arieradle/shekel/releases/tag/v0.1.0
