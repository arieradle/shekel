# OpenTelemetry Metrics Integration

Shekel exposes LLM cost and budget lifecycle data via OpenTelemetry metrics. This fills the gap left by the OTel GenAI semantic conventions, which define no cost or budget instruments.

## Installation

```bash
pip install shekel[otel]
# For development/testing also install the SDK:
pip install opentelemetry-sdk
```

## Zero-config example

```python
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader

from shekel import budget
from shekel.otel import ShekelMeter

# Wire up a MeterProvider (any OTel-compatible backend works)
provider = MeterProvider(
    metric_readers=[PeriodicExportingMetricReader(ConsoleMetricExporter())]
)

meter = ShekelMeter(meter_provider=provider)

with budget(max_usd=1.00, name="workflow") as b:
    response = openai_client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "Hello"}]
    )

meter.unregister()  # optional — removes the adapter from the registry
```

## Full `ShekelMeter` API

```python
class ShekelMeter:
    is_noop: bool  # True when opentelemetry-api is not installed

    def __init__(
        self,
        meter_provider=None,   # uses get_meter_provider() if None
        emit_tokens: bool = False,  # enable token counters (opt-in)
    ) -> None: ...

    def unregister(self) -> None: ...  # removes adapter from AdapterRegistry
```

`ShekelMeter` is a **silent no-op** when `opentelemetry-api` is not installed — `is_noop` will be `True` and no errors are raised.

## Metric reference

### Tier 2 — Per-call metrics (`shekel.llm.*`)

| Metric                           | Instrument | Unit | Description            |
| -------------------------------- | ---------- | ---- | ---------------------- |
| `shekel.llm.cost_usd`            | Counter    | USD  | Cost of each LLM call  |
| `shekel.llm.calls_total`         | Counter    | —    | Total LLM call count   |
| `shekel.llm.tokens_input_total`  | Counter    | —    | Input tokens (opt-in)  |
| `shekel.llm.tokens_output_total` | Counter    | —    | Output tokens (opt-in) |

**Attributes** on all `shekel.llm.*` instruments:

| Attribute              | Values                                                       | Notes                             |
| ---------------------- | ------------------------------------------------------------ | --------------------------------- |
| `gen_ai.system`        | `openai`, `anthropic`, `google_ai_studio`, `meta`, `unknown` | Inferred from model name prefix   |
| `gen_ai.request.model` | e.g. `gpt-4o`, `claude-3-haiku-20240307`                     | Actual model used (post-fallback) |
| `budget_name`          | e.g. `workflow`, `unnamed`                                   | From `budget(name=...)`           |

### Tier 1 — Budget lifecycle metrics (`shekel.budget.*`)

| Metric                          | Instrument    | Unit  | Description                       |
| ------------------------------- | ------------- | ----- | --------------------------------- |
| `shekel.budget.exits_total`     | Counter       | —     | Budget context exits by status    |
| `shekel.budget.cost_usd`        | UpDownCounter | USD   | Cumulative spend per budget       |
| `shekel.budget.utilization`     | Histogram     | —     | Utilization ratio 0.0–1.0 on exit |
| `shekel.budget.spend_rate`      | Histogram     | USD/s | Spend rate on exit                |
| `shekel.budget.fallbacks_total` | Counter       | —     | Fallback model activations        |
| `shekel.budget.autocaps_total`  | Counter       | —     | Child budget auto-cap events      |

**Attributes on `shekel.budget.exits_total`**:

| Attribute          | Values                                                  |
| ------------------ | ------------------------------------------------------- |
| `budget_name`      | Budget name                                             |
| `budget_full_name` | Full hierarchical path (e.g. `workflow.research.calls`) |
| `status`           | `completed`, `exceeded`, `warned`                       |

**Attributes on `shekel.budget.fallbacks_total`**:

| Attribute     | Values                          |
| ------------- | ------------------------------- |
| `budget_name` | Budget name                     |
| `from_model`  | Primary model that was replaced |
| `to_model`    | Fallback model activated        |

**Attributes on `shekel.budget.autocaps_total`**:

| Attribute     | Values             |
| ------------- | ------------------ |
| `child_name`  | Child budget name  |
| `parent_name` | Parent budget name |

## Token counters (opt-in)

Token metrics are disabled by default to keep cardinality low. Enable them:

```python
meter = ShekelMeter(emit_tokens=True)
```

This activates `shekel.llm.tokens_input_total` and `shekel.llm.tokens_output_total`.

## PromQL examples

**Budget breach rate (exceeded exits / total exits)**:

```promql
rate(shekel_budget_exits_total{status="exceeded"}[5m])
/ rate(shekel_budget_exits_total[5m])
```

**95th percentile budget utilization**:

```promql
histogram_quantile(0.95, rate(shekel_budget_utilization_bucket[10m]))
```

**Cost by model over last hour**:

```promql
sum by (gen_ai_request_model) (
  increase(shekel_llm_cost_usd_total[1h])
)
```

**Fallback activation rate**:

```promql
rate(shekel_budget_fallbacks_total[5m])
```

**Average spend rate per budget**:

```promql
histogram_quantile(0.5, rate(shekel_budget_spend_rate_bucket[10m]))
```

## Cardinality guidance

- **Do not** add `user_id`, `session_id`, or `request_id` as custom attributes — this would cause cardinality explosion in time-series databases.
- `budget_full_name` is a hierarchical string (e.g. `workflow.research.api_calls`). Keep nesting depth ≤ 3 for manageable label cardinality.
- Use `budget_name` (leaf name) in dashboards that aggregate across runs.
- `gen_ai.request.model` cardinality is bounded by the number of distinct models your application uses — typically 2–5.

## Grafana dashboard hints

1. **Cost over time**: use `shekel_llm_cost_usd_total` with `rate()` grouped by `gen_ai_request_model`
1. **Budget utilization gauge**: use `shekel_budget_utilization` with `histogram_quantile(0.99, ...)`
1. **Fallback alerts**: alert on `shekel_budget_fallbacks_total` crossing a threshold
1. **Auto-cap visibility**: `shekel_budget_autocaps_total` shows when nested budgets are being constrained by parents
