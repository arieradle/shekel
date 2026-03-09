from __future__ import annotations


class BudgetExceededError(Exception):
    """Raised when LLM API spend exceeds the configured budget limit."""

    def __init__(
        self,
        spent: float,
        limit: float,
        model: str = "unknown",
        tokens: dict[str, int] | None = None,
    ) -> None:
        self.spent = spent
        self.limit = limit
        self.model = model
        self.tokens: dict[str, int] = tokens if tokens is not None else {"input": 0, "output": 0}
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
