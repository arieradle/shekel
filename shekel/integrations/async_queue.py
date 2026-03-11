"""Non-blocking async event queue for observability adapters."""

import logging
import queue
import threading
from typing import Any

from shekel.integrations.registry import AdapterRegistry

logger = logging.getLogger(__name__)


class AsyncEventQueue:
    """Non-blocking event queue with background worker thread.

    Events are enqueued without blocking and processed asynchronously
    by a background thread that delivers them to registered adapters.

    This prevents slow observability platforms from blocking LLM API calls.

    Example:
        queue = AsyncEventQueue(max_size=1000)
        queue.enqueue("on_cost_update", {"spent": 1.23})
        queue.shutdown()  # Drain queue before exit
    """

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize async event queue.

        Args:
            max_size: Maximum queue size. When full, oldest events are dropped.
        """
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=max_size)
        self._shutdown_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._process_events, daemon=True)
        self._worker_thread.start()

    def enqueue(self, event_type: str, data: dict[str, Any]) -> None:
        """Enqueue an event for async delivery to adapters.

        This method is non-blocking and returns immediately. If the queue
        is full, the event is silently dropped (oldest-out behavior).

        Args:
            event_type: Adapter method name (e.g., "on_cost_update")
            data: Event data to pass to adapters
        """
        if self._shutdown_event.is_set():
            # Queue is shut down, don't accept new events
            return

        try:
            self._queue.put_nowait((event_type, data))
        except queue.Full:
            logger.warning(
                f"AsyncEventQueue is full ({self._queue.maxsize} events). "
                f"Dropping event: {event_type}"
            )

    def shutdown(self, timeout: float = 5.0) -> None:
        """Shutdown the queue and drain pending events.

        Blocks until all pending events are processed or timeout expires.

        Args:
            timeout: Maximum time to wait for queue to drain (seconds)
        """
        if self._shutdown_event.is_set():
            # Already shut down
            return

        # Signal shutdown
        self._shutdown_event.set()

        # Wait for worker thread to finish
        self._worker_thread.join(timeout=timeout)

        if self._worker_thread.is_alive():
            logger.warning(
                f"AsyncEventQueue worker thread did not finish within {timeout}s. "
                f"{self._queue.qsize()} events may be lost."
            )

    def _process_events(self) -> None:
        """Background worker that processes events from the queue.

        Runs continuously until shutdown is signaled, then drains the queue.
        """
        while not self._shutdown_event.is_set() or not self._queue.empty():
            try:
                # Get event with timeout to check shutdown periodically
                event_type, data = self._queue.get(timeout=0.1)

                # Deliver to all registered adapters
                AdapterRegistry.emit_event(event_type, data)

                self._queue.task_done()

            except queue.Empty:
                # No events available, continue looping
                continue
            except Exception as e:
                # Unexpected error in worker thread
                logger.error(f"AsyncEventQueue worker error: {e}", exc_info=True)
