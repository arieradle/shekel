from __future__ import annotations

from typing import Any

from shekel._budget import Budget
from shekel._decorator import with_budget
from shekel._tool import tool
from shekel.exceptions import (
    AgentBudgetExceededError,
    AgentLoopError,
    BudgetConfigMismatchError,
    BudgetExceededError,
    ChainBudgetExceededError,
    NodeBudgetExceededError,
    SessionBudgetExceededError,
    SpendVelocityExceededError,
    TaskBudgetExceededError,
    ToolBudgetExceededError,
)

__version__ = "1.0.2"
__all__ = [
    "budget",
    "Budget",
    "TemporalBudget",
    "with_budget",
    "BudgetExceededError",
    "BudgetConfigMismatchError",
    "ToolBudgetExceededError",
    "NodeBudgetExceededError",
    "AgentBudgetExceededError",
    "TaskBudgetExceededError",
    "SessionBudgetExceededError",
    "ChainBudgetExceededError",
    "AgentLoopError",
    "SpendVelocityExceededError",
    "tool",
]

# Cap-related kwargs that must NOT be mixed with a spec string.
_CAP_KWARGS = frozenset(
    {"max_usd", "max_llm_calls", "max_tool_calls", "max_tokens", "window_seconds"}
)


def budget(
    spec: str | None = None,
    *,
    name: str | None = None,
    **kwargs: Any,
) -> Budget:
    """Factory for creating Budget or TemporalBudget instances.

    Two forms — never mixed::

        # Spec string (per-cap windows, richer form):
        b = budget("$5/hr", name="api")
        b = budget("$5/hr + 100 calls/hr", name="api")

        # Kwargs (single shared window, convenience shorthand):
        b = budget(max_usd=5.0, window_seconds=3600, name="api")
        b = budget(max_usd=5.0, max_llm_calls=100, window_seconds=3600, name="api")

        # Regular budget (no rolling window):
        b = budget(max_usd=5.0)
    """
    from shekel._temporal import TemporalBudget, _parse_cap_spec

    if spec is not None:
        # Form-mixing guard: spec string + cap/window kwargs is an error.
        mixed = _CAP_KWARGS.intersection(kwargs)
        if mixed:
            raise ValueError(
                f"Cannot mix spec string with cap/window kwargs: {sorted(mixed)}. "
                "Use either the spec-string form or the kwargs form, never both."
            )
        if not name:
            raise ValueError('budget(spec) requires name=, e.g. budget("$5/hr", name="api")')
        caps = _parse_cap_spec(spec)
        return TemporalBudget(caps=caps, name=name, **kwargs)

    window_seconds = kwargs.pop("window_seconds", None)
    if window_seconds is not None:
        if not name:
            raise ValueError("TemporalBudget requires name=")
        return TemporalBudget(window_seconds=window_seconds, name=name, **kwargs)

    return Budget(name=name, **kwargs)


# Re-export TemporalBudget for direct import
from shekel._temporal import TemporalBudget  # noqa: E402
