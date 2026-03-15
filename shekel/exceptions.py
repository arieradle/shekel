from __future__ import annotations


class ToolBudgetExceededError(Exception):
    """Raised when tool invocations exceed the configured budget limit.

    Raised *before* the tool executes — the tool never runs when the budget
    is already exhausted.
    """

    def __init__(
        self,
        tool_name: str,
        calls_used: int,
        calls_limit: int | None,
        usd_spent: float,
        usd_limit: float | None,
        framework: str = "manual",
    ) -> None:
        self.tool_name = tool_name
        self.calls_used = calls_used
        self.calls_limit = calls_limit
        self.usd_spent = usd_spent
        self.usd_limit = usd_limit
        self.framework = framework
        super().__init__(str(self))

    def __str__(self) -> str:
        limit_str = str(self.calls_limit) if self.calls_limit is not None else "none"
        usd_str = (
            f"  USD: ${self.usd_spent:.4f} of ${self.usd_limit:.2f}\n"
            if self.usd_limit is not None
            else ""
        )
        return (
            f"Tool budget exceeded for '{self.tool_name}' "
            f"({self.calls_used} / {limit_str} calls, framework={self.framework})\n"
            f"{usd_str}"
            f"  Tip: Increase max_tool_calls or add warn_at=0.8 for an early warning."
        )


class BudgetExceededError(Exception):
    """Raised when LLM API spend exceeds the configured budget limit."""

    def __init__(
        self,
        spent: float,
        limit: float,
        model: str = "unknown",
        tokens: dict[str, int] | None = None,
        retry_after: float | None = None,
        window_spent: float | None = None,
    ) -> None:
        self.spent = spent
        self.limit = limit
        self.model = model
        self.tokens: dict[str, int] = tokens if tokens is not None else {"input": 0, "output": 0}
        self.retry_after: float | None = retry_after
        self.window_spent: float | None = window_spent
        super().__init__(str(self))

    def __str__(self) -> str:
        input_tokens = self.tokens.get("input", 0)
        output_tokens = self.tokens.get("output", 0)
        total_tokens = input_tokens + output_tokens
        if total_tokens > 0:
            last_call = (
                f"  Last call: {self.model} — "
                f"{input_tokens} input + {output_tokens} output tokens\n"
            )
        else:
            last_call = f"  Last call: {self.model}\n"
        return (
            f"Budget of ${self.limit:.2f} exceeded (${self.spent:.4f} spent)\n"
            f"{last_call}"
            f"  Tip: Increase max_usd, add warn_at=0.8 for an early warning, "
            f"or add fallback='gpt-4o-mini' to switch to a cheaper model instead of raising."
        )
