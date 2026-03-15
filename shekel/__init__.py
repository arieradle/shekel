from __future__ import annotations

from typing import Any

from shekel._budget import Budget
from shekel._decorator import with_budget
from shekel.exceptions import BudgetExceededError

__version__ = "0.2.8"
__all__ = ["budget", "Budget", "TemporalBudget", "with_budget", "BudgetExceededError"]


def budget(
    spec: str | None = None,
    *,
    name: str | None = None,
    **kwargs: Any,
) -> Budget:
    """Factory for creating Budget or TemporalBudget instances.

    Usage::

        # Temporal (rolling-window) budget from spec string:
        b = budget("$5/hr", name="api")

        # Temporal budget from kwargs:
        b = budget(max_usd=5.0, window_seconds=3600, name="api")

        # Regular budget (backward-compatible):
        b = budget(max_usd=5.0)
    """
    from shekel._temporal import TemporalBudget, _parse_spec

    if spec is not None:
        max_usd, window_seconds = _parse_spec(spec)
        if not name:
            raise ValueError('budget(spec) requires name=, e.g. budget("$5/hr", name="api")')
        return TemporalBudget(max_usd=max_usd, window_seconds=window_seconds, name=name, **kwargs)

    window_seconds = kwargs.pop("window_seconds", None)
    if window_seconds is not None:
        if not name:
            raise ValueError("TemporalBudget requires name=")
        return TemporalBudget(window_seconds=window_seconds, name=name, **kwargs)

    return Budget(name=name, **kwargs)


# Re-export TemporalBudget for direct import
from shekel._temporal import TemporalBudget  # noqa: E402
