# Extensibility

- **New LLM provider**: Implement `ProviderAdapter` in a new module, register with `ADAPTER_REGISTRY`. See [Extending Shekel](https://arieradle.github.io/shekel/1.1.0/extending/index.md).
- **New observability backend**: Implement `ObservabilityAdapter` and `AdapterRegistry.register(adapter)`. Same events as Langfuse/OTel.
- **Temporal backends**: Implement `TemporalBudgetBackend` (e.g. Redis, Postgres) and pass to `TemporalBudget(..., backend=...)` for shared, durable windows across processes.
