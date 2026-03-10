"""Thread-safe registry for managing observability adapters."""

import logging
import threading
from typing import Any

from shekel.integrations.base import ObservabilityAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Thread-safe registry for observability adapters.

    The registry manages a collection of adapters and broadcasts events
    to all registered adapters. If an adapter raises an exception, it's
    logged and other adapters continue to receive events.

    This is a singleton-style class with class methods only.

    Example:
        # Register adapters
        AdapterRegistry.register(LangfuseAdapter())
        AdapterRegistry.register(DataDogAdapter())

        # Emit events to all adapters
        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.23})
    """

    _adapters: list[ObservabilityAdapter] = []
    _lock = threading.Lock()

    @classmethod
    def register(cls, adapter: ObservabilityAdapter) -> None:
        """Register an adapter to receive events.

        Args:
            adapter: ObservabilityAdapter instance to register
        """
        with cls._lock:
            cls._adapters.append(adapter)

    @classmethod
    def emit_event(cls, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all registered adapters.

        If an adapter raises an exception, it's logged and other adapters
        continue to receive the event.

        Args:
            event_type: Name of the adapter method to call
                       (e.g., "on_cost_update", "on_budget_exceeded")
            data: Event data to pass to the adapter method
        """
        # Get snapshot of adapters under lock
        with cls._lock:
            adapters = cls._adapters.copy()

        # Call adapters outside lock to avoid blocking
        for adapter in adapters:
            try:
                method = getattr(adapter, event_type, None)
                if method and callable(method):
                    method(data)
            except Exception as e:
                logger.warning(
                    f"Adapter {adapter.__class__.__name__} failed on {event_type}: {e}",
                    exc_info=True,
                )

    @classmethod
    def clear(cls) -> None:
        """Remove all registered adapters.

        Useful for testing or resetting state.
        """
        with cls._lock:
            cls._adapters.clear()
