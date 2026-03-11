"""Tests for Langfuse Feature #4: Fallback Annotations."""

import pytest


class TestFallbackAnnotations:
    """Test that fallback activation creates events and updates metadata."""

    def test_fallback_creates_event(self) -> None:
        """When fallback is activated, create an event in Langfuse."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        # Should have created trace
        assert mock_client.trace.call_count >= 1

        # Should have created event
        mock_trace.event.assert_called_once()
        event_args = mock_trace.event.call_args[1]
        assert event_args["name"] == "fallback_activated"

    def test_fallback_event_level_is_info(self) -> None:
        """Fallback events should have INFO level (not WARNING - it's intentional)."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        event_args = mock_trace.event.call_args[1]
        assert event_args["level"] == "INFO"

    def test_fallback_event_includes_model_transition(self) -> None:
        """Event should clearly show which models were involved."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_fallback_activated(
            {
                "from_model": "claude-3-opus",
                "to_model": "claude-3-haiku",
                "switched_at": 10.00,
                "cost_primary": 10.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        event_args = mock_trace.event.call_args[1]
        metadata = event_args["metadata"]

        assert metadata["from_model"] == "claude-3-opus"
        assert metadata["to_model"] == "claude-3-haiku"

    def test_fallback_updates_trace_metadata(self) -> None:
        """Fallback should also update trace metadata for visibility."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        # Should have updated trace metadata
        mock_trace.update.assert_called()
        update_args = mock_trace.update.call_args[1]
        metadata = update_args["metadata"]

        assert metadata["shekel_fallback_active"] is True
        assert metadata["shekel_fallback_model"] == "gpt-4o-mini"

    def test_fallback_includes_cost_breakdown(self) -> None:
        """Event should include cost spent on each model."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 1.50,
                "savings": 0.00,  # Savings calculated later
            }
        )

        event_args = mock_trace.event.call_args[1]
        metadata = event_args["metadata"]

        assert metadata["cost_primary"] == 5.00
        assert metadata["cost_fallback"] == 1.50
        assert metadata["switched_at"] == 5.00

    def test_nested_budget_fallback_creates_span_event(self) -> None:
        """Fallback in nested budget should create event on span."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)

        # First, create nested budget
        adapter.on_cost_update(
            {
                "spent": 1.00,
                "limit": 2.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o",
                "call_cost": 1.00,
            }
        )

        # Then activate fallback in nested budget
        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 2.00,
                "cost_primary": 2.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        # Should create event on span
        mock_span.event.assert_called_once()
        event_args = mock_span.event.call_args[1]
        assert event_args["name"] == "fallback_activated"

    def test_fallback_savings_tracked_in_metadata(self) -> None:
        """If savings are calculated, include in metadata."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 1.50,
                "savings": 3.50,  # Estimated savings
            }
        )

        event_args = mock_trace.event.call_args[1]
        metadata = event_args["metadata"]
        assert metadata["savings"] == 3.50

    def test_fallback_with_langfuse_error_does_not_raise(self) -> None:
        """If Langfuse fails, should not break Shekel."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.event.side_effect = Exception("Langfuse API error")

        adapter = LangfuseAdapter(client=mock_client)

        # Should not raise
        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

    def test_multiple_fallback_activations_create_multiple_events(self) -> None:
        """If fallback is activated multiple times, track each."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        # First fallback
        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        # Second fallback (different budget)
        adapter.on_fallback_activated(
            {
                "from_model": "claude-3-opus",
                "to_model": "claude-3-haiku",
                "switched_at": 10.00,
                "cost_primary": 10.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        # Should have created two events
        assert mock_trace.event.call_count == 2

    def test_fallback_metadata_persists_across_cost_updates(self) -> None:
        """After fallback, subsequent cost updates should maintain fallback info."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        # Activate fallback
        adapter.on_fallback_activated(
            {
                "from_model": "gpt-4o",
                "to_model": "gpt-4o-mini",
                "switched_at": 5.00,
                "cost_primary": 5.00,
                "cost_fallback": 0.00,
                "savings": 0.00,
            }
        )

        # Cost update after fallback
        adapter.on_cost_update(
            {
                "spent": 6.00,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",  # Now using fallback
                "call_cost": 1.00,
            }
        )

        # Latest update should still show fallback is active
        last_update = mock_trace.update.call_args_list[-1]
        metadata = last_update[1]["metadata"]
        assert metadata["shekel_fallback_active"] is True
