"""Observability integrations for Shekel.

This package provides adapters for integrating Shekel with observability platforms
like Langfuse, DataDog, Arize, etc.
"""

from shekel.integrations.async_queue import AsyncEventQueue
from shekel.integrations.base import ObservabilityAdapter
from shekel.integrations.registry import AdapterRegistry

__all__ = ["ObservabilityAdapter", "AdapterRegistry", "AsyncEventQueue"]

# Optional Langfuse adapter (only if langfuse is installed)
try:
    from shekel.integrations.langfuse import LangfuseAdapter  # noqa: F401

    __all__.append("LangfuseAdapter")
except ImportError:  # pragma: no cover
    # langfuse is an optional dependency
    pass  # pragma: no cover

# Optional OTel metrics adapter (only if opentelemetry-api is installed)
try:
    from shekel.integrations.otel_metrics import _OtelMetricsAdapter  # noqa: F401

    __all__.append("_OtelMetricsAdapter")
except ImportError:  # pragma: no cover
    # opentelemetry-api is an optional dependency
    pass  # pragma: no cover
