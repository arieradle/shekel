# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/arieradle/shekel/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/arieradle/shekel/releases/tag/v0.1.0
