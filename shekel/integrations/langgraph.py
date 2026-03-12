"""LangGraph integration helper for Shekel LLM cost tracking.

Shekel works with LangGraph out of the box — existing OpenAI/Anthropic patches
automatically intercept all LLM calls inside graph nodes. This module provides
a convenience context manager so you don't need to import budget directly.

Example:
    >>> from shekel.integrations.langgraph import budgeted_graph
    >>>
    >>> with budgeted_graph(max_usd=0.10) as b:
    ...     result = app.invoke({"question": "What is 2+2?"})
    ...     print(f"Spent: ${b.spent:.4f}")
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from shekel import budget as shekel_budget
from shekel._budget import Budget


@contextmanager
def budgeted_graph(max_usd: float, **budget_kwargs: Any) -> Generator[Budget, None, None]:
    """Run a LangGraph graph inside a shekel budget.

    A convenience wrapper around :func:`shekel.budget` for LangGraph workflows.
    All LLM calls made within LangGraph nodes are automatically tracked via
    shekel's existing OpenAI/Anthropic patches — no extra configuration needed.

    Args:
        max_usd: Maximum spend in USD before :class:`shekel.BudgetExceededError` is raised.
        **budget_kwargs: Additional keyword arguments forwarded to :func:`shekel.budget`
            (e.g. ``name``, ``warn_at``, ``fallback``, ``max_llm_calls``).

    Yields:
        The active :class:`shekel._budget.Budget` instance.

    Raises:
        shekel.BudgetExceededError: If spend exceeds ``max_usd``.

    Example:
        >>> with budgeted_graph(max_usd=0.50, name="research-graph") as b:
        ...     result = app.invoke(state)
        ...     print(f"Spent: ${b.spent:.4f} / ${b.limit:.2f}")
    """
    with shekel_budget(max_usd=max_usd, **budget_kwargs) as b:
        yield b
