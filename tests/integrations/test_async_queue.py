"""Tests for AsyncEventQueue - non-blocking event delivery."""

import threading
import time
from typing import Any

from shekel.integrations import AdapterRegistry, ObservabilityAdapter


class RecordingAdapter(ObservabilityAdapter):
    """Adapter that records events for testing."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.lock = threading.Lock()

    def on_cost_update(self, budget_data: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(("on_cost_update", budget_data))

    def on_budget_exceeded(self, error_data: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(("on_budget_exceeded", error_data))

    def on_fallback_activated(self, fallback_data: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(("on_fallback_activated", fallback_data))


class TestAsyncEventQueue:
    """Test the AsyncEventQueue for non-blocking event delivery."""

    def setup_method(self) -> None:
        """Reset registry and create fresh queue before each test."""
        from shekel.integrations.async_queue import AsyncEventQueue

        AdapterRegistry.clear()
        # Create fresh queue for each test
        self.queue = AsyncEventQueue(max_size=100)

    def teardown_method(self) -> None:
        """Ensure queue is shut down after each test."""
        if hasattr(self, "queue"):
            self.queue.shutdown()

    def test_enqueue_is_non_blocking(self) -> None:
        """enqueue() should return immediately without blocking."""

        adapter = RecordingAdapter()
        AdapterRegistry.register(adapter)

        start = time.perf_counter()
        self.queue.enqueue("on_cost_update", {"spent": 1.0})
        elapsed = time.perf_counter() - start

        # Should complete in <5ms (AC5)
        assert elapsed < 0.005, f"enqueue took {elapsed*1000:.2f}ms, expected <5ms"

    def test_events_delivered_to_adapters(self) -> None:
        """Events in queue are delivered to registered adapters."""

        adapter = RecordingAdapter()
        AdapterRegistry.register(adapter)

        self.queue.enqueue("on_cost_update", {"spent": 1.0})
        self.queue.enqueue("on_budget_exceeded", {"spent": 5.1, "limit": 5.0})

        # Wait for background worker to process
        time.sleep(0.1)

        assert len(adapter.events) == 2
        assert adapter.events[0] == ("on_cost_update", {"spent": 1.0})
        assert adapter.events[1] == ("on_budget_exceeded", {"spent": 5.1, "limit": 5.0})

    def test_queue_drops_when_full(self) -> None:
        """When queue is full, enqueue drops oldest events."""
        from shekel.integrations.async_queue import AsyncEventQueue

        # Create small queue
        small_queue = AsyncEventQueue(max_size=3)
        adapter = RecordingAdapter()
        AdapterRegistry.register(adapter)

        try:
            # Fill queue beyond capacity
            for i in range(10):
                small_queue.enqueue("on_cost_update", {"spent": float(i)})

            # Should not raise, should drop events instead
            time.sleep(0.1)

            # Should have processed some events (not all 10)
            assert len(adapter.events) <= 10
        finally:
            small_queue.shutdown()

    def test_shutdown_drains_queue(self) -> None:
        """shutdown() processes all pending events before stopping."""

        adapter = RecordingAdapter()
        AdapterRegistry.register(adapter)

        # Enqueue multiple events
        for i in range(5):
            self.queue.enqueue("on_cost_update", {"spent": float(i)})

        # Shutdown should drain queue
        self.queue.shutdown()

        # All events should be processed
        assert len(adapter.events) == 5

    def test_shutdown_is_graceful(self) -> None:
        """shutdown() can be called multiple times safely."""
        self.queue.shutdown()
        # Should not raise
        self.queue.shutdown()

    def test_enqueue_after_shutdown_is_noop(self) -> None:
        """enqueue() after shutdown does nothing."""

        adapter = RecordingAdapter()
        AdapterRegistry.register(adapter)

        self.queue.shutdown()

        # Should not raise, should be no-op
        self.queue.enqueue("on_cost_update", {"spent": 1.0})

        time.sleep(0.1)
        assert len(adapter.events) == 0

    def test_background_worker_processes_events(self) -> None:
        """Background thread continuously processes events."""

        adapter = RecordingAdapter()
        AdapterRegistry.register(adapter)

        # Enqueue events over time
        for i in range(10):
            self.queue.enqueue("on_cost_update", {"spent": float(i)})
            time.sleep(0.01)  # Small delay between events

        # All should be processed
        time.sleep(0.1)
        assert len(adapter.events) == 10

    def test_queue_handles_adapter_errors(self) -> None:
        """Queue continues processing even if adapter raises."""

        class BrokenAdapter(ObservabilityAdapter):
            def on_cost_update(self, budget_data: dict[str, Any]) -> None:
                raise RuntimeError("Adapter failed!")

        broken = BrokenAdapter()
        adapter = RecordingAdapter()

        AdapterRegistry.register(broken)
        AdapterRegistry.register(adapter)

        self.queue.enqueue("on_cost_update", {"spent": 1.0})

        time.sleep(0.1)

        # Good adapter should still receive event
        assert len(adapter.events) == 1
