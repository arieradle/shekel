from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable

from shekel._budget import Budget


def with_budget(
    max_usd: float | None = None,
    warn_at: float | None = None,
    on_exceed: Callable[[float, float], None] | None = None,
    price_per_1k_tokens: dict[str, float] | None = None,
    fallback: str | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
    persistent: bool = False,
    hard_cap: float | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that wraps a function in a budget context.

    Accepts the same parameters as budget().

    A fresh Budget object is created on each function call. If you need a shared
    session budget across multiple calls, use ``budget(persistent=True)`` as a
    context manager directly.

    Usage::

        @with_budget(max_usd=1.00, fallback="gpt-4o-mini")
        def run_agent():
            ...

        @with_budget(max_usd=0.50)
        async def run_agent_async():
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                b = Budget(
                    max_usd=max_usd,
                    warn_at=warn_at,
                    on_exceed=on_exceed,
                    price_per_1k_tokens=price_per_1k_tokens,
                    fallback=fallback,
                    on_fallback=on_fallback,
                    persistent=persistent,
                    hard_cap=hard_cap,
                )
                async with b:
                    return await fn(*args, **kwargs)

            return async_wrapper

        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                b = Budget(
                    max_usd=max_usd,
                    warn_at=warn_at,
                    on_exceed=on_exceed,
                    price_per_1k_tokens=price_per_1k_tokens,
                    fallback=fallback,
                    on_fallback=on_fallback,
                    persistent=persistent,
                    hard_cap=hard_cap,
                )
                with b:
                    return fn(*args, **kwargs)

            return sync_wrapper

    return decorator
