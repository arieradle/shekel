from __future__ import annotations


class BudgetConfigMismatchError(Exception):
    """Raised when a distributed budget backend detects a config mismatch.

    Occurs when a budget name is already registered in the backend with
    different limits or window settings than the current configuration.
    Call reset() on the backend to clear the existing state.
    """


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
        exceeded_counter: str | None = None,
    ) -> None:
        self.spent = spent
        self.limit = limit
        self.model = model
        self.tokens: dict[str, int] = tokens if tokens is not None else {"input": 0, "output": 0}
        self.retry_after: float | None = retry_after
        self.window_spent: float | None = window_spent
        self.exceeded_counter: str | None = exceeded_counter
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
        counter_note = f"  Counter: {self.exceeded_counter}\n" if self.exceeded_counter else ""
        return (
            f"Budget of ${self.limit:.2f} exceeded (${self.spent:.4f} spent)\n"
            f"{last_call}"
            f"{counter_note}"
            f"  Tip: Increase max_usd, add warn_at=0.8 for an early warning, "
            f"or add fallback='gpt-4o-mini' to switch to a cheaper model instead of raising."
        )


class NodeBudgetExceededError(BudgetExceededError):
    """Raised when a LangGraph node exceeds its budget cap.

    Raised *before* the node body executes when an explicit cap is set,
    or during execution when the parent budget is exhausted.
    """

    def __init__(self, node_name: str, spent: float, limit: float) -> None:
        self.node_name = node_name
        super().__init__(spent=spent, limit=limit, model=f"node:{node_name}")

    def __str__(self) -> str:
        return (
            f"Node budget exceeded for '{self.node_name}' "
            f"(${self.spent:.4f} / ${self.limit:.2f})\n"
            f"  Tip: Increase b.node('{self.node_name}', max_usd=...) "
            f"or remove the explicit cap to use the parent budget only.\n"
            f"  Run b.tree() for full spend breakdown."
        )


class AgentBudgetExceededError(BudgetExceededError):
    """Raised when an agent exceeds its budget cap (CrewAI, OpenClaw)."""

    def __init__(self, agent_name: str, spent: float, limit: float) -> None:
        self.agent_name = agent_name
        super().__init__(spent=spent, limit=limit, model=f"agent:{agent_name}")

    def __str__(self) -> str:
        return (
            f"Agent budget exceeded for '{self.agent_name}' "
            f"(${self.spent:.4f} / ${self.limit:.2f})\n"
            f"  Tip: Increase b.agent('{self.agent_name}', max_usd=...) "
            f"or remove the explicit cap to use the parent budget only.\n"
            f"  Run b.tree() for full spend breakdown."
        )


class TaskBudgetExceededError(BudgetExceededError):
    """Raised when a task exceeds its budget cap (CrewAI).

    Raised *before* the task executes when an explicit cap is set.
    """

    def __init__(self, task_name: str, spent: float, limit: float) -> None:
        self.task_name = task_name
        super().__init__(spent=spent, limit=limit, model=f"task:{task_name}")

    def __str__(self) -> str:
        return (
            f"Task budget exceeded for '{self.task_name}' "
            f"(${self.spent:.4f} / ${self.limit:.2f})\n"
            f"  Tip: Increase b.task('{self.task_name}', max_usd=...) "
            f"or remove the explicit cap to use the parent budget only.\n"
            f"  Run b.tree() for full spend breakdown."
        )


class ChainBudgetExceededError(BudgetExceededError):
    """Raised when a LangChain chain or runnable exceeds its budget cap.

    Raised *before* the chain body executes when an explicit cap is set,
    or during execution when the parent budget is exhausted.
    """

    def __init__(self, chain_name: str, spent: float, limit: float) -> None:
        self.chain_name = chain_name
        super().__init__(spent=spent, limit=limit, model=f"chain:{chain_name}")

    def __str__(self) -> str:
        return (
            f"Chain budget exceeded for '{self.chain_name}' "
            f"(${self.spent:.4f} / ${self.limit:.2f})\n"
            f"  Tip: Increase b.chain('{self.chain_name}', max_usd=...) "
            f"or remove the explicit cap to use the parent budget only.\n"
            f"  Run b.tree() for full spend breakdown."
        )


class AgentLoopError(BudgetExceededError):
    """Raised when the same tool is called too many times in a rolling time window.

    Indicates a probable agent loop — the same tool being called repetitively
    without making progress. Raised *before* the tool executes (pre-dispatch gate).

    Attributes:
        tool_name: The tool that triggered the loop guard.
        repeat_count: Number of calls to this tool within the window at time of detection.
        window_seconds: The configured rolling window duration in seconds (0 = all-time).
        spent: Total USD spent by the budget at time of detection.
    """

    def __init__(
        self,
        tool_name: str,
        repeat_count: int,
        window_seconds: float,
        spent: float,
    ) -> None:
        self.tool_name = tool_name
        self.repeat_count = repeat_count
        self.window_seconds = window_seconds
        # limit=spent to avoid a misleading "0 of 0" message — no fixed USD limit for loops
        super().__init__(spent=spent, limit=spent, model=f"loop:{tool_name}")

    def __str__(self) -> str:
        window_str = (
            f"in the last {self.window_seconds:.0f}s"
            if self.window_seconds > 0
            else "total (all-time)"
        )
        return (
            f"Agent loop detected on tool '{self.tool_name}': "
            f"called {self.repeat_count} times {window_str}.\n"
            f"  Total spent: ${self.spent:.4f}\n"
            f"  Tip: Increase loop_guard_max_calls, increase loop_guard_window_seconds, "
            f"or investigate why the agent is repeating '{self.tool_name}'."
        )


class SpendVelocityExceededError(BudgetExceededError):
    """Raised when LLM spend rate exceeds the configured velocity limit.

    Subclasses BudgetExceededError so existing except-clauses catch it.

    Attributes:
        spent_in_window: Total USD spent within the velocity window.
        limit_usd: The configured velocity limit in USD.
        window_seconds: The rolling window duration in seconds.
        velocity_per_min: Normalized spend rate (USD/min) for display.
        limit_per_min: Normalized limit (USD/min) for display.
    """

    def __init__(
        self,
        spent_in_window: float,
        limit_usd: float,
        window_seconds: float,
        model: str = "unknown",
        tokens: dict[str, int] | None = None,
    ) -> None:
        self.spent_in_window = spent_in_window
        self.limit_usd = limit_usd
        self.window_seconds = window_seconds
        self.velocity_per_min = (spent_in_window / window_seconds) * 60.0
        self.limit_per_min = (limit_usd / window_seconds) * 60.0
        super().__init__(
            spent=spent_in_window,
            limit=limit_usd,
            model=model,
            tokens=tokens,
        )

    def __str__(self) -> str:
        input_tokens = self.tokens.get("input", 0)
        output_tokens = self.tokens.get("output", 0)
        total_tokens = input_tokens + output_tokens
        token_str = (
            f"  Last call: {self.model} — "
            f"{input_tokens} input + {output_tokens} output tokens\n"
            if total_tokens > 0
            else f"  Last call: {self.model}\n"
        )
        return (
            f"Spend velocity limit exceeded: "
            f"${self.spent_in_window:.4f} spent in {self.window_seconds:.0f}s window "
            f"(limit: ${self.limit_usd:.2f}/{self.window_seconds:.0f}s, "
            f"~${self.limit_per_min:.2f}/min)\n"
            f"{token_str}"
            f"  Tip: Increase max_velocity, add warn_velocity for early warning, "
            f"or use warn_only=True to observe without blocking."
        )


class SessionBudgetExceededError(BudgetExceededError):
    """Raised when an always-on agent session exceeds its rolling-window budget (OpenClaw)."""

    def __init__(
        self,
        agent_name: str,
        spent: float,
        limit: float,
        window: float | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.window = window
        super().__init__(spent=spent, limit=limit, model=f"session:{agent_name}")

    def __str__(self) -> str:
        window_str = f" over {self.window:.0f}s window" if self.window is not None else ""
        return (
            f"Session budget exceeded for agent '{self.agent_name}' "
            f"(${self.spent:.4f} / ${self.limit:.2f}{window_str})\n"
            f"  Tip: Increase the session budget or use a longer rolling window."
        )
