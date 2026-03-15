"""@tool decorator and tool() wrapper for budget-tracking plain Python tools."""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, TypeVar

from shekel._context import get_active_budget

_F = TypeVar("_F", bound=Callable[..., Any])


def _get_tool_name(fn: Any) -> str:
    """Extract a readable name from a function or callable object."""
    if hasattr(fn, "__name__"):
        return str(fn.__name__)
    if hasattr(fn, "__class__"):
        return str(fn.__class__.__name__)
    return "unknown_tool"  # pragma: no cover


def _wrap_sync(
    fn: Callable[..., Any], name: str, decorator_price: float | None
) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        active = get_active_budget()
        if active is not None:
            # Resolve effective price: budget-level tool_prices > decorator price
            price: float | None = None
            if active.tool_prices is not None and name in active.tool_prices:
                price = active.tool_prices[name]
            elif decorator_price is not None:
                price = decorator_price
            active._check_tool_limit(name, "manual")
            result = fn(*args, **kwargs)
            active._record_tool_call(name, price if price is not None else 0.0, "manual")
            return result
        return fn(*args, **kwargs)

    return wrapper


def _wrap_async(
    fn: Callable[..., Any], name: str, decorator_price: float | None
) -> Callable[..., Any]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        active = get_active_budget()
        if active is not None:
            price: float | None = None
            if active.tool_prices is not None and name in active.tool_prices:
                price = active.tool_prices[name]
            elif decorator_price is not None:
                price = decorator_price
            active._check_tool_limit(name, "manual")
            result = await fn(*args, **kwargs)
            active._record_tool_call(name, price if price is not None else 0.0, "manual")
            return result
        return await fn(*args, **kwargs)

    return wrapper


def _wrap_callable(obj: Any, name: str, decorator_price: float | None) -> Callable[..., Any]:
    """Wrap a non-function callable (e.g. a third-party tool instance)."""
    original_call = obj.__call__

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        active = get_active_budget()
        if active is not None:
            price: float | None = None
            if active.tool_prices is not None and name in active.tool_prices:
                price = active.tool_prices[name]
            elif decorator_price is not None:
                price = decorator_price
            active._check_tool_limit(name, "manual")
            result = original_call(*args, **kwargs)
            active._record_tool_call(name, price if price is not None else 0.0, "manual")
            return result
        return original_call(*args, **kwargs)

    wrapper.__name__ = name
    wrapper.__doc__ = getattr(obj, "__doc__", None)
    return wrapper


def tool(
    fn: Any = None,
    *,
    price: float | None = None,
) -> Any:
    """Decorator / wrapper to make a Python function or callable budget-trackable.

    Usage::

        @tool                        # free tool — just count calls
        def read_file(path): ...

        @tool(price=0.005)           # priced tool — count + charge
        def web_search(query): ...

        @tool()                      # same as @tool, empty call form
        def my_fn(): ...

        tavily = tool(TavilySearchResults(), price=0.005)  # third-party wrapper

    When called inside a ``with budget(...)`` context, the tool checks the
    limit before running and records the call after.  When no budget is active,
    it is a transparent pass-through with zero overhead beyond a ContextVar read.
    """
    # Called as @tool (no parentheses) — fn is the decorated function
    if fn is not None and callable(fn) and not isinstance(fn, type):
        # Check if it looks like a plain function or an arbitrary callable instance
        if hasattr(fn, "__func__") or (hasattr(fn, "__module__") and hasattr(fn, "__qualname__")):
            # Plain function
            name = _get_tool_name(fn)
            if asyncio.iscoroutinefunction(fn):
                return _wrap_async(fn, name, price)
            return _wrap_sync(fn, name, price)
        else:
            # Callable object (third-party tool instance)
            name = _get_tool_name(fn)
            return _wrap_callable(fn, name, price)

    # Called as @tool(...) or tool(...) with keyword args only
    # fn is None — return a decorator
    def decorator(f: Any) -> Any:
        name = _get_tool_name(f)
        if asyncio.iscoroutinefunction(f):
            return _wrap_async(f, name, price)
        if callable(f) and not hasattr(f, "__qualname__"):  # pragma: no cover
            return _wrap_callable(f, name, price)  # pragma: no cover
        return _wrap_sync(f, name, price)

    return decorator
