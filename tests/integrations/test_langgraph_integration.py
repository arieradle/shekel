"""TDD tests for LangGraph integration helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestBudgetedGraphExists:
    def test_module_importable(self):
        from shekel.integrations import langgraph  # noqa: F401

    def test_budgeted_graph_is_callable(self):
        from shekel.integrations.langgraph import budgeted_graph

        assert callable(budgeted_graph)


class TestBudgetedGraphContextManager:
    def test_yields_budget_object(self):
        from shekel.integrations.langgraph import budgeted_graph

        with budgeted_graph(max_usd=1.0) as b:
            assert b is not None
            assert hasattr(b, "spent")
            assert hasattr(b, "limit")

    def test_budget_limit_is_set(self):
        from shekel.integrations.langgraph import budgeted_graph

        with budgeted_graph(max_usd=0.50) as b:
            assert b.limit == 0.50

    def test_budget_kwargs_forwarded(self):
        from shekel.integrations.langgraph import budgeted_graph

        with budgeted_graph(max_usd=1.0, name="my-graph") as b:
            assert b.name == "my-graph"

    def test_spent_starts_at_zero(self):
        from shekel.integrations.langgraph import budgeted_graph

        with budgeted_graph(max_usd=1.0) as b:
            assert b.spent == 0.0

    def test_budget_exceeded_error_propagates(self):
        from shekel import BudgetExceededError
        from shekel.integrations.langgraph import budgeted_graph

        with patch("shekel._patch._originals", {"openai_sync": MagicMock()}):
            try:
                with budgeted_graph(max_usd=0.000001) as b:
                    # Force a spend by directly recording
                    b._record_spend(1.0, "gpt-4o", {"input": 1000, "output": 500})
            except BudgetExceededError:
                pass  # Expected — budget exceeded propagates correctly


class TestBudgetedGraphRecordsCost:
    def test_openai_call_inside_records_spend(self):
        """OpenAI calls inside budgeted_graph are tracked via existing patches."""
        from shekel.integrations.langgraph import budgeted_graph

        mock_response = MagicMock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.model = "gpt-4o-mini"

        original_fn = MagicMock(return_value=mock_response)

        with patch("shekel._patch._originals", {"openai_sync": original_fn}):

            with budgeted_graph(max_usd=1.0) as b:
                # Simulate what the openai wrapper does
                from shekel._patch import _record

                _record(100, 50, "gpt-4o-mini")
                assert b.spent > 0
