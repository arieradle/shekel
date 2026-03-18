# Extensibility

- **New LLM provider**: Implement `ProviderAdapter` in a new module, register with `ADAPTER_REGISTRY`. See [Extending Shekel](../extending.md).
- **New observability backend**: Implement `ObservabilityAdapter` and `AdapterRegistry.register(adapter)`. Same events as Langfuse/OTel.
- **Temporal backends**: Implement `TemporalBudgetBackend` (e.g. Redis, Postgres) and pass to `TemporalBudget(..., backend=...)` for shared, durable windows across processes.
