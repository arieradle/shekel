"""Tests for Langfuse Feature #1: Real-Time Cost Streaming."""

import pytest


class TestRealTimeCostStreaming:
    """Test that cost updates are streamed to Langfuse after each LLM call."""

    def test_cost_update_creates_trace_if_not_exists(self) -> None:
        """First cost update should create a new trace in Langfuse."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        adapter = LangfuseAdapter(client=mock_client, trace_name="test-trace")

        # Simulate first cost update
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Should have created a trace
        mock_client.trace.assert_called_once()
        call_args = mock_client.trace.call_args
        assert call_args[1]["name"] == "test-trace"

    def test_cost_update_adds_metadata_to_trace(self) -> None:
        """Cost updates should add/update metadata on the trace."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Should have updated metadata
        mock_trace.update.assert_called()
        update_args = mock_trace.update.call_args[1]

        # Verify metadata contains cost info
        assert "metadata" in update_args
        metadata = update_args["metadata"]
        assert "shekel_spent" in metadata
        assert metadata["shekel_spent"] == 0.05

    def test_cost_update_tracks_budget_utilization(self) -> None:
        """Metadata should include budget utilization percentage."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_cost_update(
            {
                "spent": 2.50,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o",
                "call_cost": 2.50,
            }
        )

        update_args = mock_trace.update.call_args[1]
        metadata = update_args["metadata"]

        # Should track utilization (2.50 / 5.00 = 50%)
        assert "shekel_utilization" in metadata
        assert metadata["shekel_utilization"] == 0.5

    def test_cost_update_handles_no_limit_track_only(self) -> None:
        """Should handle track-only mode (no limit set)."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_cost_update(
            {
                "spent": 1.23,
                "limit": None,  # Track-only mode
                "name": "tracking",
                "full_name": "tracking",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 1.23,
            }
        )

        # Should still record cost, but no utilization
        update_args = mock_trace.update.call_args[1]
        metadata = update_args["metadata"]

        assert "shekel_spent" in metadata
        assert metadata["shekel_spent"] == 1.23
        # Utilization should be None or not present
        assert metadata.get("shekel_utilization") is None

    def test_nested_budgets_use_hierarchical_names(self) -> None:
        """Nested budgets should use hierarchical names in Langfuse."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 1.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Should have created a span with hierarchical name
        mock_trace.span.assert_called_once()
        span_args = mock_trace.span.call_args[1]
        assert span_args["name"] == "parent.child"

        # Should have updated span metadata
        mock_span.update.assert_called()
        update_args = mock_span.update.call_args[1]
        metadata = update_args["metadata"]

        # Should include hierarchical name
        assert "shekel_budget_name" in metadata
        assert metadata["shekel_budget_name"] == "parent.child"

    def test_cost_update_includes_model_info(self) -> None:
        """Metadata should include the model used."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_cost_update(
            {
                "spent": 0.50,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o",
                "call_cost": 0.50,
            }
        )

        update_args = mock_trace.update.call_args[1]
        metadata = update_args["metadata"]

        assert "shekel_last_model" in metadata
        assert metadata["shekel_last_model"] == "gpt-4o"

    def test_multiple_cost_updates_accumulate(self) -> None:
        """Multiple cost updates should accumulate in the same trace."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        # First update
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Second update (accumulated)
        adapter.on_cost_update(
            {
                "spent": 0.10,  # Total spent now 0.10
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Trace should have been created once
        assert mock_client.trace.call_count == 1

        # Update should have been called twice
        assert mock_trace.update.call_count == 2

        # Last update should show accumulated cost
        last_call = mock_trace.update.call_args_list[-1]
        metadata = last_call[1]["metadata"]
        assert metadata["shekel_spent"] == 0.10

    def test_cost_update_with_custom_tags(self) -> None:
        """Adapter should apply custom tags to traces."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client, tags=["production", "api-v2"])

        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Should have applied tags
        call_args = mock_client.trace.call_args[1]
        assert "tags" in call_args
        assert call_args["tags"] == ["production", "api-v2"]

    def test_cost_update_handles_langfuse_errors_gracefully(self) -> None:
        """If Langfuse API fails, should not break Shekel."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_client.trace.side_effect = Exception("Langfuse API error")

        adapter = LangfuseAdapter(client=mock_client)

        # Should not raise even if Langfuse fails
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 5.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )
