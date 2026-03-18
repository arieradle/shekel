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

    def on_tool_call(self, tool_data: dict[str, Any]) -> None:
        """Called after every successful tool dispatch.

        Args:
            tool_data: Dictionary containing:
                - tool_name: str - Name of the tool that was called
                - cost: float - USD cost of this call (0.0 if unpriced)
                - framework: str - Source framework ('manual', 'mcp', 'langchain', etc.)
                - budget_name: str - Name of the active budget
                - calls_used: int - Tool calls used so far (including this one)
                - calls_remaining: int | None - Remaining tool call budget
                - usd_spent: float - Total tool USD spent so far
        """
        pass

    def on_tool_budget_exceeded(self, error_data: dict[str, Any]) -> None:
        """Called when a tool call is blocked due to budget exhaustion.

        Fired *before* the tool executes — the tool never runs.

        Args:
            error_data: Dictionary containing:
                - tool_name: str - Name of the tool that was blocked
                - calls_used: int - Tool calls used at the time of blocking
                - calls_limit: int | None - The tool call limit
                - usd_spent: float - Total tool USD spent so far
                - usd_limit: float | None - The USD limit (None if not set)
                - framework: str - Source framework
                - budget_name: str - Name of the active budget
        """
        pass

    def on_backend_unavailable(self, error_data: dict[str, Any]) -> None:
        """Called when a distributed budget backend is unreachable or errors.

        Fired before raising BudgetExceededError (fail-closed) or allowing
        the call through (fail-open), depending on on_unavailable setting.

        Args:
            error_data: Dictionary containing:
                - budget_name: str - Name of the budget whose backend failed
                - error: str - String description of the error
        """
        pass

    def on_tool_warn(self, warn_data: dict[str, Any]) -> None:
        """Called when tool calls reach the warn_at threshold.

        Fires once per budget context when tool_calls_used >= warn_at × max_tool_calls.

        Args:
            warn_data: Dictionary containing:
                - tool_name: str - Name of the tool that triggered the warning
                - calls_used: int - Tool calls used at the time of warning
                - calls_limit: int | None - The tool call limit
                - budget_name: str - Name of the active budget
                - warn_at: float - The threshold fraction that was configured
        """
        pass
