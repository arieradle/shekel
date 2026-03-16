# Module Map

| Path | Purpose |
|------|--------|
| `shekel/__init__.py` | Public API: `budget`, `Budget`, `TemporalBudget`, `with_budget`, `tool`, exceptions. |
| `shekel/_budget.py` | Budget class, nested/session logic, recording, limits, fallback. |
| `shekel/_temporal.py` | TemporalBudget, spec parsing, InMemoryBackend, TemporalBudgetBackend protocol. |
| `shekel/_context.py` | ContextVar for active budget. |
| `shekel/_patch.py` | Ref-counted patching, install/restore, fallback validation, shared wrapper flow, observability emit. |
| `shekel/_pricing.py` | `calculate_cost`, `prices.json`, tokencost fallback. |
| `shekel/prices.json` | Bundled model pricing. |
| `shekel/_tool.py` | `@tool` and tool wrapper. |
| `shekel/_decorator.py` | `@with_budget`. |
| `shekel/_cli.py` | Click CLI: estimate, models, run. |
| `shekel/_run_config.py` | TOML budget file parsing. |
| `shekel/_run_utils.py` | Running user script under budget. |
| `shekel/exceptions.py` | BudgetExceededError, ToolBudgetExceededError. |
| `shekel/providers/base.py` | ProviderAdapter, ProviderRegistry. |
| `shekel/providers/openai.py`, `anthropic.py`, etc. | Per-provider adapters. |
| `shekel/integrations/base.py` | ObservabilityAdapter. |
| `shekel/integrations/registry.py` | AdapterRegistry for observability. |
| `shekel/integrations/langfuse.py`, `otel_metrics.py` | Langfuse and OTel adapters. |
| `shekel/otel.py` | ShekelMeter (OTel registration). |
