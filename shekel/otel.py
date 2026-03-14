"""Public entry point for Shekel OpenTelemetry metrics integration.

Zero-config, silent no-op when opentelemetry-api is not installed.

Usage::

    from shekel.otel import ShekelMeter

    meter = ShekelMeter()          # uses global MeterProvider
    # or
    meter = ShekelMeter(meter_provider=my_provider, emit_tokens=True)

    # Unregister when done
    meter.unregister()
"""

from __future__ import annotations

from typing import Any

from shekel import __version__

try:
    from opentelemetry import metrics as _otel_metrics

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


class ShekelMeter:
    """Zero-config OTel metrics entry point. Silent no-op when opentelemetry-api absent."""

    is_noop: bool

    def __init__(self, meter_provider: Any = None, emit_tokens: bool = False) -> None:
        if not _OTEL_AVAILABLE:
            self.is_noop = True
            return

        self.is_noop = False

        if meter_provider is None:
            meter_provider = _otel_metrics.get_meter_provider()

        meter = meter_provider.get_meter("shekel", version=__version__)

        from shekel.integrations import AdapterRegistry
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        self._adapter = _OtelMetricsAdapter(meter, emit_tokens=emit_tokens)
        AdapterRegistry.register(self._adapter)

    def unregister(self) -> None:
        """Remove this meter's adapter from the registry."""
        if not self.is_noop:
            from shekel.integrations import AdapterRegistry

            AdapterRegistry.unregister(self._adapter)
