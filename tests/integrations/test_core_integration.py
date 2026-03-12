"""Tests for integration between adapter system and core Shekel functionality."""

import pytest

from shekel import budget
from shekel.exceptions import BudgetExceededError
from shekel.integrations import AdapterRegistry, AsyncEventQueue, ObservabilityAdapter


class CollectingAdapter(ObservabilityAdapter):
    """Test adapter that collects all events."""

    def __init__(self) -> None:
        self.cost_updates: list[dict] = []
        self.budget_exceeded_events: list[dict] = []
        self.fallback_events: list[dict] = []

    def on_cost_update(self, budget_data: dict) -> None:
        self.cost_updates.append(budget_data.copy())

    def on_budget_exceeded(self, error_data: dict) -> None:
        self.budget_exceeded_events.append(error_data.copy())

    def on_fallback_activated(self, fallback_data: dict) -> None:
        self.fallback_events.append(fallback_data.copy())


class TestCoreIntegration:
    """Test that core Shekel code emits events to adapters."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        AdapterRegistry.clear()

    def test_cost_update_emitted_after_llm_call(self) -> None:
        """_record() should emit on_cost_update event after each LLM call."""

        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        with budget(max_usd=5.00, name="test"):
            # Simulate LLM call by directly calling _record
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        # Should have received cost update event
        assert len(adapter.cost_updates) >= 1
        last_update = adapter.cost_updates[-1]

        # Verify event contains required fields
        assert "spent" in last_update
        assert "limit" in last_update
        assert "name" in last_update or "full_name" in last_update
        assert last_update["spent"] > 0

    def test_budget_exceeded_event_emitted(self) -> None:
        """BudgetExceededError should emit on_budget_exceeded event."""

        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        try:
            with budget(max_usd=0.001, name="tiny_budget"):
                from shekel._patch import _record

                # Spend more than limit
                _record(input_tokens=10000, output_tokens=5000, model="gpt-4o")
        except BudgetExceededError:
            pass  # Expected

        # Should have received budget exceeded event
        assert len(adapter.budget_exceeded_events) >= 1
        event = adapter.budget_exceeded_events[0]

        # Verify event contains required fields
        assert "budget_name" in event or "name" in event
        assert "spent" in event
        assert "limit" in event
        assert event["spent"] > event["limit"]

    def test_fallback_event_emitted_on_activation(self) -> None:
        """Fallback activation should emit on_fallback_activated event."""
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        with budget(
            max_usd=0.001,
            fallback={"at": 0.8, "max_usd": 10.0, "model": "gpt-4o-mini"},
            name="fallback_test",
        ):
            from shekel._patch import _record

            # First call exceeds limit, triggers fallback
            _record(input_tokens=1000, output_tokens=500, model="gpt-4o")

            # Continue with fallback
            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        # Should have received fallback event
        assert len(adapter.fallback_events) >= 1
        event = adapter.fallback_events[0]

        # Verify event contains required fields
        assert "from_model" in event or "to_model" in event
        assert "switched_at" in event or "cost_primary" in event

    def test_events_not_emitted_when_no_adapters_registered(self) -> None:
        """Events should be no-op when no adapters are registered (no errors)."""
        # No adapters registered
        AdapterRegistry.clear()

        # Should not raise
        with budget(max_usd=5.00):
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

    def test_nested_budgets_emit_with_full_name(self) -> None:
        """Nested budgets should emit events with hierarchical names."""
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        with budget(max_usd=10.00, name="parent"):
            with budget(max_usd=3.00, name="child"):
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        # Should have received cost updates
        assert len(adapter.cost_updates) >= 1
        last_update = adapter.cost_updates[-1]

        # Should contain hierarchical name
        assert "full_name" in last_update or "name" in last_update
        # Name should be "parent.child" or similar
        name = last_update.get("full_name") or last_update.get("name", "")
        assert "child" in name.lower()

    def test_adapter_errors_do_not_break_llm_calls(self) -> None:
        """If adapter raises exception, LLM call should still complete."""

        class BrokenAdapter(ObservabilityAdapter):
            def on_cost_update(self, budget_data: dict) -> None:
                raise RuntimeError("Adapter is broken!")

        broken = BrokenAdapter()
        AdapterRegistry.register(broken)

        # Should not raise (adapter error is caught)
        with budget(max_usd=5.00) as b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        # Budget should have tracked the spend
        assert b.spent > 0


class TestAsyncQueueIntegration:
    """Test that events flow through async queue properly."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        AdapterRegistry.clear()

    def test_events_delivered_asynchronously(self) -> None:
        """Events should be delivered through async queue without blocking."""
        import time

        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        # Create async queue (would be global in real usage)
        queue = AsyncEventQueue(max_size=100)

        try:
            # Enqueue event
            queue.enqueue(
                "on_cost_update",
                {"spent": 1.23, "limit": 5.00, "name": "test", "full_name": "test"},
            )

            # Wait for async delivery
            time.sleep(0.1)

            # Should have been delivered
            assert len(adapter.cost_updates) == 1
            assert adapter.cost_updates[0]["spent"] == 1.23
        finally:
            queue.shutdown()


class TestBudgetExceededEventLimit:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_exceeded_event_reports_effective_limit(self) -> None:
        """on_budget_exceeded event should report effective_limit, not max_usd."""
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        with budget(max_usd=10.00, name="parent") as parent:
            parent._spent = 7.00  # child will be capped to $3

            try:
                with budget(max_usd=5.00, name="child") as child:
                    assert child.limit == 3.00
                    child._record_spend(4.00, "gpt-4o", {"input": 100, "output": 50})
            except BudgetExceededError:
                pass

        assert len(adapter.budget_exceeded_events) >= 1
        event = adapter.budget_exceeded_events[0]
        assert event["limit"] == 3.00, f"Expected limit=3.00 in event, got {event['limit']}"
        assert event["overage"] == pytest.approx(1.00)

    def test_exceeded_event_uncapped_reports_max_usd(self) -> None:
        """For non-capped budgets, event limit equals max_usd."""
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        try:
            with budget(max_usd=5.00, name="root") as b:
                b._record_spend(6.00, "gpt-4o", {"input": 100, "output": 50})
        except BudgetExceededError:
            pass

        assert len(adapter.budget_exceeded_events) >= 1
        event = adapter.budget_exceeded_events[0]
        assert event["limit"] == 5.00


class TestEmitEventExceptionSwallowing:
    """Test that adapter system failures do not break budget enforcement."""

    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_emit_fallback_event_tolerates_registry_failure(self) -> None:
        """Budget fallback activates even if the adapter registry raises."""
        from unittest.mock import patch

        with patch.object(AdapterRegistry, "emit_event", side_effect=RuntimeError("registry down")):
            # Should not raise — exception is swallowed by _emit_fallback_event
            with budget(
                max_usd=0.001,
                fallback={"at": 0.8, "max_usd": 10.0, "model": "gpt-4o-mini"},
                name="test",
            ):
                from shekel._patch import _record

                _record(input_tokens=1000, output_tokens=500, model="gpt-4o")
                assert True  # reached here means enforcement continued

    def test_emit_budget_exceeded_event_tolerates_registry_failure(self) -> None:
        """BudgetExceededError is still raised even if the adapter registry raises."""
        from unittest.mock import patch

        with patch.object(AdapterRegistry, "emit_event", side_effect=RuntimeError("registry down")):
            with pytest.raises(BudgetExceededError):
                with budget(max_usd=0.001, name="tiny"):
                    from shekel._patch import _record

                    _record(input_tokens=10000, output_tokens=5000, model="gpt-4o")
