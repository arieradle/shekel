"""Langfuse adapter for Shekel observability integration."""

from typing import Any, Union

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
        tags: Union[list[str], None] = None,
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
        self._span_stack: list[Any] = []  # Stack of spans for nested budgets
        self._fallback_active = False  # Track if fallback is currently active
        self._fallback_model: Union[str, None] = None  # Current fallback model

    def on_cost_update(self, budget_data: dict[str, Any]) -> None:
        """Called after each LLM API call with updated cost information.

        Sends cost and usage data to Langfuse as metadata on the current trace/span.
        For nested budgets, creates a hierarchy of spans to match the budget structure.

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
            depth = budget_data["depth"]
            full_name = budget_data["full_name"]

            # Create trace if it doesn't exist (depth 0, first call)
            if self._trace is None:
                self._trace = self.client.trace(
                    name=self.trace_name,
                    tags=self.tags if self.tags else None,
                )

            # Build metadata
            metadata = {
                "shekel_spent": budget_data["spent"],
                "shekel_limit": budget_data["limit"],
                "shekel_budget_name": full_name,
                "shekel_last_model": budget_data["model"],
            }

            # Add utilization if limit is set
            if budget_data["limit"] is not None and budget_data["limit"] > 0:
                utilization = budget_data["spent"] / budget_data["limit"]
                metadata["shekel_utilization"] = utilization
            else:
                metadata["shekel_utilization"] = None

            # Include fallback info if active
            if self._fallback_active:
                metadata["shekel_fallback_active"] = True
                metadata["shekel_fallback_model"] = self._fallback_model

            # Handle nesting
            if depth == 0:
                # Top-level budget: update trace
                # Adjust span stack if we returned from nested budget
                self._span_stack = []
                if self._trace is not None:  # Type guard
                    self._trace.update(metadata=metadata)
            else:
                # Nested budget: manage span hierarchy
                # Adjust stack to match current depth
                while len(self._span_stack) >= depth:
                    self._span_stack.pop()

                # Determine parent (trace or parent span)
                if depth == 1:
                    parent = self._trace
                else:
                    parent = self._span_stack[-1]

                # Check if we need to create a new span or update existing
                if parent is not None and len(self._span_stack) < depth:
                    # Create new span
                    span = parent.span(name=full_name)
                    self._span_stack.append(span)
                else:
                    # Update existing span at this depth
                    span = self._span_stack[depth - 1]

                # Update span with metadata
                if span is not None:  # Type guard
                    span.update(metadata=metadata)

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
        try:
            # Create trace if it doesn't exist
            if self._trace is None:
                self._trace = self.client.trace(
                    name=self.trace_name,
                    tags=self.tags if self.tags else None,
                )

            # Determine which object to attach event to (trace or span)
            # If budget_name contains '.', it's nested - find the appropriate span
            budget_name = error_data["budget_name"]

            if "." in budget_name and len(self._span_stack) > 0:
                # Nested budget - attach event to current span
                target = self._span_stack[-1]
            else:
                # Top-level budget - attach event to trace
                target = self._trace

            # Build event metadata
            metadata = {
                "budget_name": budget_name,
                "spent": error_data["spent"],
                "limit": error_data["limit"],
                "overage": error_data["overage"],
                "model": error_data["model"],
                "tokens": error_data["tokens"],
            }

            # Include parent remaining if available
            if error_data.get("parent_remaining") is not None:
                metadata["parent_remaining"] = error_data["parent_remaining"]

            # Create event
            if target is not None:  # Type guard
                target.event(
                    name="budget_exceeded",
                    level="WARNING",
                    metadata=metadata,
                )

        except Exception:
            # Don't break Shekel if Langfuse fails
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
        try:
            # Create trace if it doesn't exist
            if self._trace is None:
                self._trace = self.client.trace(
                    name=self.trace_name,
                    tags=self.tags if self.tags else None,
                )

            # Update internal state
            self._fallback_active = True
            self._fallback_model = fallback_data["to_model"]

            # Determine target (trace or current span)
            if len(self._span_stack) > 0:
                target = self._span_stack[-1]
            else:
                target = self._trace

            # Build event metadata
            event_metadata = {
                "from_model": fallback_data["from_model"],
                "to_model": fallback_data["to_model"],
                "switched_at": fallback_data["switched_at"],
                "cost_primary": fallback_data["cost_primary"],
                "cost_fallback": fallback_data["cost_fallback"],
                "savings": fallback_data["savings"],
            }

            # Create event
            if target is not None:  # Type guard
                target.event(
                    name="fallback_activated",
                    level="INFO",
                    metadata=event_metadata,
                )

            # Also update trace/span metadata to show fallback is active
            update_metadata = {
                "shekel_fallback_active": True,
                "shekel_fallback_model": fallback_data["to_model"],
            }

            if target is not None:  # Type guard
                target.update(metadata=update_metadata)

        except Exception:
            # Don't break Shekel if Langfuse fails
            pass

    def on_tool_call(self, tool_data: dict[str, Any]) -> None:
        """Called after every tool dispatch. Creates a Langfuse span with cost field.

        Populates Langfuse's native ``cost`` field so the platform's cost UI
        shows full agent cost (LLM + tools), not just LLM spend.

        Args:
            tool_data: Dictionary containing:
                - tool_name: str - Name of the tool
                - cost: float - USD cost of this call
                - framework: str - Source framework
                - budget_name: str - Active budget name
                - calls_used: int - Tool calls used so far
                - calls_remaining: int | None - Remaining tool call budget
                - usd_spent: float - Total tool USD spent so far
        """
        try:
            if self._trace is None:
                self._trace = self.client.trace(
                    name=self.trace_name,
                    tags=self.tags if self.tags else None,
                )

            tool_name = tool_data.get("tool_name", "unknown")
            cost = float(tool_data.get("cost", 0.0) or 0.0)

            # Determine parent (trace or current span)
            parent = self._span_stack[-1] if self._span_stack else self._trace

            if parent is not None:
                parent.span(
                    name=f"tool:{tool_name}",
                    metadata={
                        "tool_name": tool_name,
                        "framework": tool_data.get("framework", "unknown"),
                        "budget_name": tool_data.get("budget_name", "unnamed"),
                        "calls_used": tool_data.get("calls_used"),
                        "calls_remaining": tool_data.get("calls_remaining"),
                        "usd_spent": tool_data.get("usd_spent"),
                    },
                    cost=cost if cost > 0.0 else None,
                )
        except Exception:
            pass
