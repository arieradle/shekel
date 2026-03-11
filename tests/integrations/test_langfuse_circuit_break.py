"""Tests for Langfuse Feature #3: Circuit Break Events."""


class TestCircuitBreakEvents:
    """Test that budget exceeded events create events in Langfuse."""

    def test_budget_exceeded_creates_event(self) -> None:
        """When budget is exceeded, create an event in Langfuse."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        # Simulate budget exceeded
        adapter.on_budget_exceeded(
            {
                "budget_name": "main",
                "spent": 5.50,
                "limit": 5.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 1000, "output": 500},
                "parent_remaining": None,
            }
        )

        # Should have created trace (if not exists)
        assert mock_client.trace.call_count >= 1

        # Should have created an event
        mock_trace.event.assert_called_once()
        event_args = mock_trace.event.call_args[1]
        assert event_args["name"] == "budget_exceeded"

    def test_event_includes_budget_details(self) -> None:
        """Event should include all relevant budget violation details."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_budget_exceeded(
            {
                "budget_name": "api-calls",
                "spent": 10.75,
                "limit": 10.00,
                "overage": 0.75,
                "model": "gpt-4o",
                "tokens": {"input": 2000, "output": 1000},
                "parent_remaining": 5.00,
            }
        )

        event_args = mock_trace.event.call_args[1]
        metadata = event_args["metadata"]

        # Should include key details
        assert metadata["budget_name"] == "api-calls"
        assert metadata["spent"] == 10.75
        assert metadata["limit"] == 10.00
        assert metadata["overage"] == 0.75
        assert metadata["model"] == "gpt-4o"

    def test_event_level_is_warning(self) -> None:
        """Budget exceeded events should have WARNING level."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_budget_exceeded(
            {
                "budget_name": "main",
                "spent": 5.50,
                "limit": 5.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 1000, "output": 500},
                "parent_remaining": None,
            }
        )

        event_args = mock_trace.event.call_args[1]
        assert event_args["level"] == "WARNING"

    def test_nested_budget_exceeded_creates_span_event(self) -> None:
        """Nested budget violation should create event on child span."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)

        # First, create nested budget with cost update
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

        # Then exceed nested budget
        adapter.on_budget_exceeded(
            {
                "budget_name": "parent.child",
                "spent": 2.50,
                "limit": 2.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 1000, "output": 500},
                "parent_remaining": 8.00,
            }
        )

        # Should create event on the span, not trace
        mock_span.event.assert_called_once()
        event_args = mock_span.event.call_args[1]
        assert event_args["name"] == "budget_exceeded"

    def test_event_includes_parent_remaining_if_available(self) -> None:
        """If parent budget exists, include remaining parent budget."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_budget_exceeded(
            {
                "budget_name": "main",
                "spent": 5.50,
                "limit": 5.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 1000, "output": 500},
                "parent_remaining": 15.50,  # Parent has $15.50 left
            }
        )

        event_args = mock_trace.event.call_args[1]
        metadata = event_args["metadata"]
        assert metadata["parent_remaining"] == 15.50

    def test_multiple_budget_exceeded_creates_multiple_events(self) -> None:
        """Multiple budget violations should create multiple events."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        # First violation
        adapter.on_budget_exceeded(
            {
                "budget_name": "phase1",
                "spent": 5.50,
                "limit": 5.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 1000, "output": 500},
                "parent_remaining": None,
            }
        )

        # Second violation
        adapter.on_budget_exceeded(
            {
                "budget_name": "phase2",
                "spent": 3.20,
                "limit": 3.00,
                "overage": 0.20,
                "model": "gpt-4o-mini",
                "tokens": {"input": 500, "output": 250},
                "parent_remaining": None,
            }
        )

        # Should have created two events
        assert mock_trace.event.call_count == 2

    def test_budget_exceeded_with_langfuse_error_does_not_raise(self) -> None:
        """If Langfuse API fails, should not break Shekel."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.event.side_effect = Exception("Langfuse API error")

        adapter = LangfuseAdapter(client=mock_client)

        # Should not raise even if Langfuse fails
        adapter.on_budget_exceeded(
            {
                "budget_name": "main",
                "spent": 5.50,
                "limit": 5.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 1000, "output": 500},
                "parent_remaining": None,
            }
        )

    def test_event_includes_token_counts(self) -> None:
        """Event metadata should include token counts for debugging."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        adapter.on_budget_exceeded(
            {
                "budget_name": "main",
                "spent": 5.50,
                "limit": 5.00,
                "overage": 0.50,
                "model": "gpt-4o",
                "tokens": {"input": 2500, "output": 1500},
                "parent_remaining": None,
            }
        )

        event_args = mock_trace.event.call_args[1]
        metadata = event_args["metadata"]

        assert "tokens" in metadata
        assert metadata["tokens"]["input"] == 2500
        assert metadata["tokens"]["output"] == 1500
