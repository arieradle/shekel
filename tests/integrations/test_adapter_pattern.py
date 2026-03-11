"""Tests for the ObservabilityAdapter base interface."""

from shekel.integrations.base import ObservabilityAdapter


class TestObservabilityAdapterInterface:
    """Test the base adapter interface."""

    def test_adapter_has_required_methods(self) -> None:
        """Base adapter must have all required hook methods."""
        adapter = ObservabilityAdapter()

        assert hasattr(adapter, "on_cost_update")
        assert hasattr(adapter, "on_budget_exceeded")
        assert hasattr(adapter, "on_fallback_activated")

    def test_adapter_methods_are_callable(self) -> None:
        """All adapter methods must be callable."""
        adapter = ObservabilityAdapter()

        assert callable(adapter.on_cost_update)
        assert callable(adapter.on_budget_exceeded)
        assert callable(adapter.on_fallback_activated)

    def test_on_cost_update_accepts_dict(self) -> None:
        """on_cost_update must accept budget_data dict."""
        adapter = ObservabilityAdapter()

        # Should not raise
        adapter.on_cost_update({"spent": 1.23, "limit": 5.00})

    def test_on_budget_exceeded_accepts_dict(self) -> None:
        """on_budget_exceeded must accept error_data dict."""
        adapter = ObservabilityAdapter()

        # Should not raise
        adapter.on_budget_exceeded({"spent": 5.10, "limit": 5.00})

    def test_on_fallback_activated_accepts_dict(self) -> None:
        """on_fallback_activated must accept fallback_data dict."""
        adapter = ObservabilityAdapter()

        # Should not raise
        adapter.on_fallback_activated({"from_model": "gpt-4o", "to_model": "gpt-4o-mini"})

    def test_adapter_methods_return_none(self) -> None:
        """Adapter methods should return None (no-op by default)."""
        adapter = ObservabilityAdapter()

        result1 = adapter.on_cost_update({})
        result2 = adapter.on_budget_exceeded({})
        result3 = adapter.on_fallback_activated({})

        assert result1 is None
        assert result2 is None
        assert result3 is None


# Mock adapter for testing registry
class MockAdapter(ObservabilityAdapter):
    """Mock adapter that tracks method calls."""

    def __init__(self) -> None:
        self.cost_updates: list[dict] = []
        self.budget_exceeded_events: list[dict] = []
        self.fallback_events: list[dict] = []

    def on_cost_update(self, budget_data: dict) -> None:
        self.cost_updates.append(budget_data)

    def on_budget_exceeded(self, error_data: dict) -> None:
        self.budget_exceeded_events.append(error_data)

    def on_fallback_activated(self, fallback_data: dict) -> None:
        self.fallback_events.append(fallback_data)


class TestAdapterRegistry:
    """Test the AdapterRegistry for managing multiple adapters."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        from shekel.integrations import AdapterRegistry

        AdapterRegistry.clear()

    def test_register_single_adapter(self) -> None:
        """Registry can register a single adapter."""
        from shekel.integrations import AdapterRegistry

        adapter = MockAdapter()
        AdapterRegistry.register(adapter)

        # Verify adapter is registered (check internal state or emit test)
        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})
        assert len(adapter.cost_updates) == 1

    def test_register_multiple_adapters(self) -> None:
        """Registry can register multiple adapters."""
        from shekel.integrations import AdapterRegistry

        adapter1 = MockAdapter()
        adapter2 = MockAdapter()

        AdapterRegistry.register(adapter1)
        AdapterRegistry.register(adapter2)

        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})

        assert len(adapter1.cost_updates) == 1
        assert len(adapter2.cost_updates) == 1

    def test_emit_event_broadcasts_to_all_adapters(self) -> None:
        """emit_event sends to all registered adapters."""
        from shekel.integrations import AdapterRegistry

        adapter1 = MockAdapter()
        adapter2 = MockAdapter()
        adapter3 = MockAdapter()

        AdapterRegistry.register(adapter1)
        AdapterRegistry.register(adapter2)
        AdapterRegistry.register(adapter3)

        data = {"spent": 2.5, "limit": 5.0}
        AdapterRegistry.emit_event("on_cost_update", data)

        assert adapter1.cost_updates == [data]
        assert adapter2.cost_updates == [data]
        assert adapter3.cost_updates == [data]

    def test_emit_event_handles_all_event_types(self) -> None:
        """emit_event works for all adapter methods."""
        from shekel.integrations import AdapterRegistry

        adapter = MockAdapter()
        AdapterRegistry.register(adapter)

        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})
        AdapterRegistry.emit_event("on_budget_exceeded", {"spent": 5.1, "limit": 5.0})
        AdapterRegistry.emit_event("on_fallback_activated", {"from_model": "gpt-4o"})

        assert len(adapter.cost_updates) == 1
        assert len(adapter.budget_exceeded_events) == 1
        assert len(adapter.fallback_events) == 1

    def test_adapter_error_does_not_break_others(self) -> None:
        """If one adapter raises, others still receive events."""
        from shekel.integrations import AdapterRegistry

        class BrokenAdapter(ObservabilityAdapter):
            def on_cost_update(self, budget_data: dict) -> None:
                raise RuntimeError("Adapter failed!")

        adapter1 = MockAdapter()
        broken = BrokenAdapter()
        adapter2 = MockAdapter()

        AdapterRegistry.register(adapter1)
        AdapterRegistry.register(broken)
        AdapterRegistry.register(adapter2)

        # Should not raise, should continue to adapter2
        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})

        assert len(adapter1.cost_updates) == 1
        assert len(adapter2.cost_updates) == 1

    def test_clear_removes_all_adapters(self) -> None:
        """clear() removes all registered adapters."""
        from shekel.integrations import AdapterRegistry

        adapter = MockAdapter()
        AdapterRegistry.register(adapter)

        AdapterRegistry.clear()

        # After clear, emit should not reach adapter
        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})
        assert len(adapter.cost_updates) == 0

    def test_registry_is_thread_safe(self) -> None:
        """Registry operations are thread-safe."""
        import threading

        from shekel.integrations import AdapterRegistry

        adapters = [MockAdapter() for _ in range(10)]

        def register_adapter(adapter: MockAdapter) -> None:
            AdapterRegistry.register(adapter)

        threads = [threading.Thread(target=register_adapter, args=(a,)) for a in adapters]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All adapters should receive the event
        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})

        for adapter in adapters:
            assert len(adapter.cost_updates) == 1

    def test_unregister_removes_adapter(self) -> None:
        """unregister() removes a specific adapter from the registry."""
        from shekel.integrations import AdapterRegistry

        adapter = MockAdapter()
        AdapterRegistry.register(adapter)
        result = AdapterRegistry.unregister(adapter)
        assert result is True

        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})
        assert len(adapter.cost_updates) == 0

    def test_unregister_returns_false_if_not_registered(self) -> None:
        """unregister() returns False when the adapter was never registered."""
        from shekel.integrations import AdapterRegistry

        adapter = MockAdapter()
        result = AdapterRegistry.unregister(adapter)
        assert result is False

    def test_unregister_only_removes_specific_instance(self) -> None:
        """unregister() removes only the specified adapter, leaving others intact."""
        from shekel.integrations import AdapterRegistry

        a1 = MockAdapter()
        a2 = MockAdapter()
        AdapterRegistry.register(a1)
        AdapterRegistry.register(a2)
        AdapterRegistry.unregister(a1)

        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0})
        assert len(a1.cost_updates) == 0  # removed
        assert len(a2.cost_updates) == 1  # still registered
