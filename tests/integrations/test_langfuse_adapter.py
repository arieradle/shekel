"""Tests for Langfuse adapter integration."""

import pytest

from shekel.integrations import ObservabilityAdapter


class TestLangfuseAdapterSetup:
    """Test basic Langfuse adapter setup and initialization."""

    def test_langfuse_adapter_exists(self) -> None:
        """LangfuseAdapter class should be importable."""
        from shekel.integrations.langfuse import LangfuseAdapter

        assert LangfuseAdapter is not None
        assert issubclass(LangfuseAdapter, ObservabilityAdapter)

    def test_langfuse_adapter_requires_client(self) -> None:
        """LangfuseAdapter should require a Langfuse client instance."""
        from shekel.integrations.langfuse import LangfuseAdapter

        # Should raise TypeError if no client provided
        with pytest.raises(TypeError):
            LangfuseAdapter()  # type: ignore[call-arg]

    def test_langfuse_adapter_accepts_client(self) -> None:
        """LangfuseAdapter should accept a Langfuse client."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client)

        assert adapter is not None
        assert adapter.client == mock_client

    def test_langfuse_adapter_has_required_methods(self) -> None:
        """LangfuseAdapter should implement all required hook methods."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client)

        # Should have all three methods from ObservabilityAdapter
        assert hasattr(adapter, "on_cost_update")
        assert hasattr(adapter, "on_budget_exceeded")
        assert hasattr(adapter, "on_fallback_activated")
        assert callable(adapter.on_cost_update)
        assert callable(adapter.on_budget_exceeded)
        assert callable(adapter.on_fallback_activated)

    def test_langfuse_adapter_methods_dont_raise(self) -> None:
        """Adapter methods should not raise exceptions (graceful no-ops if needed)."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client)

        # Should not raise even with empty/invalid data
        adapter.on_cost_update({})
        adapter.on_budget_exceeded({})
        adapter.on_fallback_activated({})

    def test_langfuse_adapter_optional_import(self) -> None:
        """LangfuseAdapter should be importable even if langfuse package is not installed."""
        # This test verifies that importing the module doesn't fail
        # even if langfuse is not installed (it should be an optional dependency)
        try:
            from shekel.integrations.langfuse import LangfuseAdapter

            assert LangfuseAdapter is not None
        except ImportError as e:
            # If import fails, it should only be because langfuse is not installed,
            # not because of a syntax or structural error in our code
            assert "langfuse" in str(e).lower() or "no module named" in str(e).lower()

    def test_langfuse_adapter_can_be_registered(self) -> None:
        """LangfuseAdapter should be registerable with AdapterRegistry."""
        from unittest.mock import MagicMock

        from shekel.integrations import AdapterRegistry
        from shekel.integrations.langfuse import LangfuseAdapter

        AdapterRegistry.clear()

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client)

        # Should register without error
        AdapterRegistry.register(adapter)

        # Should be able to emit events
        AdapterRegistry.emit_event("on_cost_update", {"spent": 1.0, "limit": 5.0})


class TestLangfuseAdapterConfiguration:
    """Test Langfuse adapter configuration options."""

    def test_adapter_accepts_optional_trace_name(self) -> None:
        """LangfuseAdapter should accept optional trace_name parameter."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client, trace_name="my-trace")

        assert adapter.trace_name == "my-trace"

    def test_adapter_defaults_trace_name(self) -> None:
        """LangfuseAdapter should have a sensible default trace name."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client)

        # Should have a default trace name
        assert adapter.trace_name is not None
        assert isinstance(adapter.trace_name, str)
        assert len(adapter.trace_name) > 0

    def test_adapter_accepts_tags(self) -> None:
        """LangfuseAdapter should accept optional tags."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        tags = ["production", "api-v2"]
        adapter = LangfuseAdapter(client=mock_client, tags=tags)

        assert adapter.tags == tags

    def test_adapter_defaults_no_tags(self) -> None:
        """LangfuseAdapter should default to no tags if not provided."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client)

        # Should have empty or None tags
        assert adapter.tags is None or adapter.tags == []
