"""Langfuse adapter for Shekel observability integration."""

from typing import Any

from shekel.integrations.base import ObservabilityAdapter


class LangfuseAdapter(ObservabilityAdapter):
    """Adapter to send Shekel budget events to Langfuse for observability.
    
    This adapter integrates Shekel's LLM cost tracking with Langfuse's
    observability platform, enabling rich tracing, cost analysis, and
    budget monitoring in the Langfuse UI.
    
    Example:
        >>> from langfuse import Langfuse
        >>> from shekel import budget
        >>> from shekel.integrations import AdapterRegistry
        >>> from shekel.integrations.langfuse import LangfuseAdapter
        >>> 
        >>> # Initialize Langfuse client
        >>> lf = Langfuse(public_key="...", secret_key="...")
        >>> 
        >>> # Register adapter
        >>> adapter = LangfuseAdapter(client=lf, trace_name="my-workflow")
        >>> AdapterRegistry.register(adapter)
        >>> 
        >>> # Use budget as normal - events automatically flow to Langfuse
        >>> with budget(max_usd=5.00) as b:
        >>>     response = openai_client.chat.completions.create(...)
    """

    def __init__(
        self,
        client: Any,
        trace_name: str = "shekel-budget",
        tags: list[str] | None = None,
    ) -> None:
        """Initialize the Langfuse adapter.
        
        Args:
            client: Langfuse client instance (from langfuse.Langfuse)
            trace_name: Name for the trace in Langfuse UI (default: "shekel-budget")
            tags: Optional list of tags to attach to traces/spans
        """
        self.client = client
        self.trace_name = trace_name
        self.tags = tags or []
        self._trace = None  # Current trace object

    def on_cost_update(self, budget_data: dict[str, Any]) -> None:
        """Called after each LLM API call with updated cost information.
        
        Sends cost and usage data to Langfuse as metadata on the current trace/span.
        
        Args:
            budget_data: Dictionary containing:
                - spent: Total spent so far (float)
                - limit: Budget limit (float or None)
                - name: Budget name (str or None)
                - full_name: Full hierarchical budget name (str)
                - depth: Nesting depth (int)
                - model: Model used for this call (str)
                - call_cost: Cost of this specific call (float)
        """
        try:
            # Create trace if it doesn't exist
            if self._trace is None:
                self._trace = self.client.trace(
                    name=self.trace_name,
                    tags=self.tags if self.tags else None,
                )
            
            # Build metadata
            metadata = {
                "shekel_spent": budget_data["spent"],
                "shekel_limit": budget_data["limit"],
                "shekel_budget_name": budget_data["full_name"],
                "shekel_last_model": budget_data["model"],
            }
            
            # Add utilization if limit is set
            if budget_data["limit"] is not None and budget_data["limit"] > 0:
                utilization = budget_data["spent"] / budget_data["limit"]
                metadata["shekel_utilization"] = utilization
            else:
                metadata["shekel_utilization"] = None
            
            # Update trace with new metadata
            self._trace.update(metadata=metadata)
            
        except Exception:
            # Don't break Shekel if Langfuse fails
            pass

    def on_budget_exceeded(self, error_data: dict[str, Any]) -> None:
        """Called when a budget limit is exceeded.
        
        Creates an event in Langfuse marking the budget violation for debugging.
        
        Args:
            error_data: Dictionary containing:
                - budget_name: Name of the budget that was exceeded (str)
                - spent: Total amount spent (float)
                - limit: The budget limit that was exceeded (float)
                - overage: Amount over budget (float)
                - model: Model being used when limit hit (str)
                - tokens: Token counts (dict)
                - parent_remaining: Parent budget remaining (float or None)
        """
        # TODO: Implement in Story 3.1
        pass

    def on_fallback_activated(self, fallback_data: dict[str, Any]) -> None:
        """Called when fallback model is activated due to budget constraints.
        
        Creates an event and updates metadata to track model switching for cost optimization.
        
        Args:
            fallback_data: Dictionary containing:
                - from_model: Original model (str)
                - to_model: Fallback model (str)
                - switched_at: Cost when switch occurred (float)
                - cost_primary: Total cost on primary model (float)
                - cost_fallback: Total cost on fallback model (float)
                - savings: Estimated savings from fallback (float)
        """
        # TODO: Implement in Story 3.2
        pass
