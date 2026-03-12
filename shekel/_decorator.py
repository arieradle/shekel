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
    fallback: dict[str, Any] | None = None,
    on_fallback: Callable[[float, float, str], None] | None = None,
    name: str | None = None,
    max_llm_calls: int | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that wraps a function in a budget context.

    Accepts the same parameters as budget(), including ``name`` for use in
    nested budget hierarchies. A fresh Budget object is created on each
    function call.

    Usage::

        @with_budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})
        def run_agent():
            ...

        @with_budget(max_usd=0.50, name="research")
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
                    name=name,
                    max_llm_calls=max_llm_calls,
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
                    name=name,
                    max_llm_calls=max_llm_calls,
                )
                with b:
                    return fn(*args, **kwargs)

            return sync_wrapper

    return decorator
