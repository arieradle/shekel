"""Tests for Langfuse Feature #2: Nested Budget Mapping."""


class TestNestedBudgetMapping:
    """Test that Shekel's nested budgets map to Langfuse span hierarchy."""

    def test_nested_budget_creates_child_span(self) -> None:
        """When a nested budget is encountered, create a child span."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)

        # Parent budget
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Child budget (depth=1)
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 2.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Should have created a span for the child
        mock_trace.span.assert_called_once()
        span_args = mock_trace.span.call_args[1]
        assert span_args["name"] == "parent.child"

    def test_multiple_nested_levels_create_hierarchy(self) -> None:
        """Multiple nesting levels should create proper span hierarchy."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span1 = MagicMock()
        mock_span2 = MagicMock()

        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span1
        mock_span1.span.return_value = mock_span2

        adapter = LangfuseAdapter(client=mock_client)

        # Level 0: parent
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Level 1: child
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 2.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Level 2: grandchild
        adapter.on_cost_update(
            {
                "spent": 0.02,
                "limit": 0.50,
                "name": "grandchild",
                "full_name": "parent.child.grandchild",
                "depth": 2,
                "model": "gpt-4o-mini",
                "call_cost": 0.02,
            }
        )

        # Trace should have been created once
        assert mock_client.trace.call_count == 1

        # Should have created span for child under trace
        assert mock_trace.span.call_count == 1

        # Should have created span for grandchild under child span
        assert mock_span1.span.call_count == 1

    def test_sibling_budgets_create_sibling_spans(self) -> None:
        """Sibling budgets at same depth should create sibling spans."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span1 = MagicMock()
        mock_span2 = MagicMock()

        mock_client.trace.return_value = mock_trace
        mock_trace.span.side_effect = [mock_span1, mock_span2]

        adapter = LangfuseAdapter(client=mock_client)

        # Parent
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # First child
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 2.00,
                "name": "child1",
                "full_name": "parent.child1",
                "depth": 1,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Second child (sibling)
        adapter.on_cost_update(
            {
                "spent": 0.03,
                "limit": 1.00,
                "name": "child2",
                "full_name": "parent.child2",
                "depth": 1,
                "model": "gpt-4o-mini",
                "call_cost": 0.03,
            }
        )

        # Should have created 2 sibling spans
        assert mock_trace.span.call_count == 2

    def test_span_metadata_includes_budget_info(self) -> None:
        """Child spans should have their own budget metadata."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()

        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)

        # Parent
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Child with its own budget
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 2.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o",
                "call_cost": 0.05,
            }
        )

        # Child span should have been updated with metadata
        mock_span.update.assert_called()
        update_args = mock_span.update.call_args[1]
        metadata = update_args["metadata"]

        assert metadata["shekel_spent"] == 0.05
        assert metadata["shekel_limit"] == 2.00
        assert metadata["shekel_budget_name"] == "parent.child"
        assert metadata["shekel_utilization"] == 0.025  # 0.05 / 2.00

    def test_returning_to_parent_updates_parent_span(self) -> None:
        """When returning to parent budget, updates should go to parent span."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()

        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)

        # Parent (depth=0)
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Child (depth=1)
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 2.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o",
                "call_cost": 0.05,
            }
        )

        # Back to parent (depth=0) with new spend
        adapter.on_cost_update(
            {
                "spent": 0.20,  # Parent accumulated more
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Trace (parent) should have been updated twice
        assert mock_trace.update.call_count == 2

        # Latest update should show accumulated parent spend
        last_update = mock_trace.update.call_args_list[-1]
        metadata = last_update[1]["metadata"]
        assert metadata["shekel_spent"] == 0.20

    def test_flat_budgets_dont_create_spans(self) -> None:
        """Non-nested budgets (depth=0) should only use the trace, not spans."""
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)

        # Multiple depth=0 updates (no nesting)
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        adapter.on_cost_update(
            {
                "spent": 0.20,
                "limit": 10.00,
                "name": "main",
                "full_name": "main",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Should never create spans (only trace)
        mock_trace.span.assert_not_called()

        # Should update trace twice
        assert mock_trace.update.call_count == 2

    def test_nested_update_with_null_trace_is_safe(self) -> None:
        """on_cost_update with depth>0 when trace() returns None is handled gracefully.

        When client.trace() returns None (e.g. connection failure), parent is None
        for depth=1 updates, hitting the else branch at langfuse.py:127.
        The IndexError is caught and the adapter continues silently.
        """
        from unittest.mock import MagicMock

        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_client.trace.return_value = None  # simulate trace creation failure
        adapter = LangfuseAdapter(client=mock_client)

        # Establish a top-level "trace" (which is None due to mock)
        adapter.on_cost_update(
            {
                "spent": 0.10,
                "limit": 10.00,
                "name": "parent",
                "full_name": "parent",
                "depth": 0,
                "model": "gpt-4o-mini",
                "call_cost": 0.10,
            }
        )

        # Now a nested update: parent = self._trace = None → hits else branch (line 127)
        adapter.on_cost_update(
            {
                "spent": 0.05,
                "limit": 2.00,
                "name": "child",
                "full_name": "parent.child",
                "depth": 1,
                "model": "gpt-4o-mini",
                "call_cost": 0.05,
            }
        )

        # Should not raise — exception is swallowed gracefully
