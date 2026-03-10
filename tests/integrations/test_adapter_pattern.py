"""Tests for the ObservabilityAdapter base interface."""

import pytest

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
