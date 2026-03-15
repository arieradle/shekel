"""Base interface for observability platform adapters."""

from typing import Any


class ObservabilityAdapter:
    """Base interface for observability platform integrations.

    Adapters implement this interface to receive events from Shekel's
    budget tracking system and forward them to observability platforms.

    All methods are no-ops by default. Subclasses override the methods
    they need to implement specific platform integrations.

    Example:
        class LangfuseAdapter(ObservabilityAdapter):
            def on_cost_update(self, budget_data: dict[str, Any]) -> None:
                # Update Langfuse span with cost data
                pass
    """

    def on_cost_update(self, budget_data: dict[str, Any]) -> None:
        """Called after each LLM API call with updated cost information.

        Args:
            budget_data: Dictionary containing:
                - spent: float - Current total spend in USD
                - limit: float | None - Budget limit in USD (None for track-only)
                - name: str | None - Budget name (for nested budgets)
                - full_name: str - Full hierarchical budget path
                - depth: int - Nesting depth (0 for root)
                - model: str - Model used for the call
                - call_cost: float - Cost of this specific call
        """
        pass

    def on_budget_exceeded(self, error_data: dict[str, Any]) -> None:
        """Called when a budget limit is exceeded.

        Args:
            error_data: Dictionary containing:
                - budget_name: str - Name of the budget that was exceeded
                - spent: float - Total amount spent
                - limit: float - The budget limit that was exceeded
                - overage: float - Amount over the limit
                - model: str - Model that triggered the exception
                - tokens: dict - Token counts (input, output)
                - parent_remaining: float | None - Parent budget remaining (if nested)
        """
        pass

    def on_fallback_activated(self, fallback_data: dict[str, Any]) -> None:
        """Called when fallback model is activated due to budget constraints.

        Args:
            fallback_data: Dictionary containing:
                - from_model: str - Original model name
                - to_model: str - Fallback model name
                - switched_at: float - Cost when switch occurred
                - cost_primary: float - Cost spent on primary model
                - cost_fallback: float - Cost spent on fallback model
                - savings: float - Estimated savings from using fallback
        """
        pass

    def on_budget_exit(self, exit_data: dict[str, Any]) -> None:
        """Called when a budget context exits.

        Args:
            exit_data: Dictionary containing:
                - budget_name: str - Name of the budget
                - budget_full_name: str - Full hierarchical budget path
                - status: str - "completed", "exceeded", or "warned"
                - spent_usd: float - Total USD spent
                - limit_usd: float | None - Budget limit (None for track-only)
                - utilization: float | None - spent/limit ratio (None when no limit)
                - duration_seconds: float - Time spent inside with-block
                - calls_made: int - Number of LLM calls made
                - model_switched: bool - Whether fallback was activated
                - from_model: str | None - Primary model name (if switched)
                - to_model: str | None - Fallback model name (if switched)
        """
        pass

    def on_autocap(self, autocap_data: dict[str, Any]) -> None:
        """Called when a child budget is auto-capped by parent remaining.

        Args:
            autocap_data: Dictionary containing:
                - child_name: str - Name of the child budget
                - parent_name: str - Name of the parent budget
                - original_limit: float - Child's originally requested limit
                - effective_limit: float - Actual capped limit applied
        """
        pass

    def on_window_reset(self, reset_data: dict[str, Any]) -> None:
        """Called when a TemporalBudget window expires on entry.

        Args:
            reset_data: Dictionary containing:
                - budget_name: str - Name of the temporal budget
                - window_seconds: float - Duration of the rolling window
                - previous_spent: float - Amount spent in the previous window
        """
        pass
