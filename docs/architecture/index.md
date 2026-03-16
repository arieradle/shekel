# Architecture

This section describes shekel's internal architecture: how budget enforcement works, how providers and observability plug in, and how the CLI runs user code under a budget.

## Contents

- [Overview](overview.md) — High-level design, entry points, and component diagram
- [Core Components](components.md) — Budget lifecycle, patching & providers, pricing, tools, observability, CLI
- [Data Flow](data-flow.md) — Library and CLI call flows with sequence diagrams
- [Module Map](module-map.md) — File and module reference
- [Extensibility](extensibility.md) — New providers, observability backends, temporal backends
- [Concurrency & Safety](concurrency.md) — ContextVar, ref-counting, thread safety

## Related docs

- [How It Works](../how-it-works.md) — Monkey-patching, ContextVar, and ref-counting in more detail
- [Extending Shekel](../extending.md) — Custom providers, pricing, and temporal backends
- [CLI Reference](../cli.md) — All `shekel run` and config options
- [API Reference](../api-reference.md) — Full parameter and method reference
