"""OpenTelemetry metrics adapter for Shekel budget tracking."""

from __future__ import annotations

from typing import Any

from shekel.integrations.base import ObservabilityAdapter

try:
    from opentelemetry import metrics as _otel_metrics  # noqa: F401

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTEL_AVAILABLE = False  # pragma: no cover

# Provider prefix → OTel gen_ai.system semantic convention value
_PROVIDER_MAP: dict[str, str] = {
    "gpt": "openai",
    "o1": "openai",
    "o2": "openai",
    "o3": "openai",
    "o4": "openai",
    "claude": "anthropic",
    "gemini": "google_ai_studio",
    "llama": "meta",
}


def _infer_gen_ai_system(model: str) -> str:
    """Map a model name to its OTel gen_ai.system value."""
    for prefix, system in _PROVIDER_MAP.items():
        if model.startswith(prefix):
            return system
    return "unknown"


class _OtelMetricsAdapter(ObservabilityAdapter):
    """Observability adapter that emits Shekel budget metrics via OpenTelemetry."""

    def __init__(self, meter: Any, emit_tokens: bool = False) -> None:
        # Tier 2 — per-call, model-tagged
        self._llm_cost = meter.create_counter(
            "shekel.llm.cost_usd",
            unit="USD",
            description="Cost of each LLM call in USD",
        )
        self._llm_calls = meter.create_counter(
            "shekel.llm.calls_total",
            description="Total number of LLM calls",
        )

        # Tier 1 — budget lifecycle
        self._budget_cost = meter.create_up_down_counter(
            "shekel.budget.cost_usd",
            unit="USD",
            description="Cumulative spend per budget (in-flight UpDownCounter)",
        )
        self._budget_exits = meter.create_counter(
            "shekel.budget.exits_total",
            description="Number of budget context exits by status",
        )
        self._budget_util = meter.create_histogram(
            "shekel.budget.utilization",
            description="Budget utilization ratio (0.0–1.0) on exit",
        )
        self._budget_rate = meter.create_histogram(
            "shekel.budget.spend_rate",
            unit="USD/s",
            description="Spend rate in USD per second on budget exit",
        )
        self._budget_fallbacks = meter.create_counter(
            "shekel.budget.fallbacks_total",
            description="Number of fallback model activations",
        )
        self._budget_autocaps = meter.create_counter(
            "shekel.budget.autocaps_total",
            description="Number of child budget auto-cap events",
        )
        self._window_resets = meter.create_counter(
            "shekel.budget.window_resets_total",
            description="Number of TemporalBudget rolling-window resets",
        )

        # Tool metrics (v0.2.8)
        self._tool_calls = meter.create_counter(
            "shekel.tool.calls_total",
            description="Total number of tool calls tracked by Shekel",
        )
        self._tool_cost = meter.create_counter(
            "shekel.tool.cost_usd_total",
            unit="USD",
            description="Total USD cost of tool calls tracked by Shekel",
        )
        self._tool_exceeded = meter.create_counter(
            "shekel.tool.budget_exceeded_total",
            description="Number of tool calls blocked by budget enforcement",
        )
        self._tool_remaining = meter.create_observable_gauge(
            "shekel.tool.calls_remaining",
            description="Remaining tool call budget for the active budget context",
        )

        # Optional token counters
        if emit_tokens:
            self._tokens_in: Any = meter.create_counter(
                "shekel.llm.tokens_input_total",
                description="Total input tokens consumed",
            )
            self._tokens_out: Any = meter.create_counter(
                "shekel.llm.tokens_output_total",
                description="Total output tokens generated",
            )
        else:
            self._tokens_in = None
            self._tokens_out = None

    def on_cost_update(self, data: dict[str, Any]) -> None:
        try:
            model = data.get("model", "") or ""
            attrs = {
                "gen_ai.system": _infer_gen_ai_system(model),
                "gen_ai.request.model": model or "unknown",
                "budget_name": data.get("name") or "unnamed",
            }
            call_cost = float(data.get("call_cost", 0.0) or 0.0)

            self._llm_cost.add(call_cost, attrs)
            self._llm_calls.add(1, attrs)

            # Budget-level UpDownCounter (tracks cumulative spend)
            budget_attrs = {
                "budget_name": data.get("name") or "unnamed",
                "budget_full_name": data.get("full_name") or "",
            }
            self._budget_cost.add(call_cost, budget_attrs)

            if self._tokens_in is not None:
                self._tokens_in.add(int(data.get("input_tokens", 0) or 0), attrs)
            if self._tokens_out is not None:
                self._tokens_out.add(int(data.get("output_tokens", 0) or 0), attrs)
        except Exception:
            pass

    def on_budget_exit(self, data: dict[str, Any]) -> None:
        try:
            budget_name = data.get("budget_name", "unnamed") or "unnamed"
            budget_full_name = data.get("budget_full_name", "") or ""
            b_attrs = {
                "budget_name": budget_name,
                "budget_full_name": budget_full_name,
            }

            # exits_total counter
            self._budget_exits.add(1, {**b_attrs, "status": data.get("status", "completed")})

            # utilization histogram (clamped to [0.0, 1.0])
            util = data.get("utilization")
            if util is not None:
                self._budget_util.record(min(1.0, float(util)), b_attrs)

            # spend_rate histogram
            dur = float(data.get("duration_seconds", 0.0) or 0.0)
            spent = float(data.get("spent_usd", 0.0) or 0.0)
            rate = spent / dur if dur > 0.0 else 0.0
            self._budget_rate.record(rate, {"budget_name": budget_name})

            # fallbacks counter
            if data.get("model_switched") and data.get("to_model"):
                self._budget_fallbacks.add(
                    1,
                    {
                        "budget_name": budget_name,
                        "from_model": data.get("from_model") or "unknown",
                        "to_model": data["to_model"],
                    },
                )
        except Exception:  # noqa: BLE001 — OTel adapter must never crash user code
            pass

    def on_window_reset(self, data: dict[str, Any]) -> None:
        try:
            self._window_resets.add(1, {"budget_name": data.get("budget_name", "unnamed")})
        except Exception:  # noqa: BLE001 — OTel adapter must never crash user code
            pass

    def on_tool_call(self, data: dict[str, Any]) -> None:
        try:
            attrs = {
                "tool_name": data.get("tool_name") or "unknown",
                "budget_name": data.get("budget_name") or "unnamed",
                "framework": data.get("framework") or "unknown",
            }
            self._tool_calls.add(1, attrs)
            cost = float(data.get("cost", 0.0) or 0.0)
            if cost > 0.0:
                self._tool_cost.add(cost, attrs)
        except Exception:  # noqa: BLE001
            pass

    def on_tool_budget_exceeded(self, data: dict[str, Any]) -> None:
        try:
            attrs = {
                "tool_name": data.get("tool_name") or "unknown",
                "budget_name": data.get("budget_name") or "unnamed",
            }
            self._tool_exceeded.add(1, attrs)
        except Exception:  # noqa: BLE001
            pass

    def on_autocap(self, data: dict[str, Any]) -> None:
        try:
            self._budget_autocaps.add(
                1,
                {
                    "child_name": data.get("child_name", "unnamed") or "unnamed",
                    "parent_name": data.get("parent_name", "unnamed") or "unnamed",
                },
            )
        except Exception:
            pass
