"""LangChain / LangGraph provider adapter for Shekel tool budget tracking."""

from __future__ import annotations

from typing import Any

_original_invoke: Any = None
_original_ainvoke: Any = None


def _get_price(budget: Any, tool_name: str) -> float:
    if budget.tool_prices is not None and tool_name in budget.tool_prices:
        return float(budget.tool_prices[tool_name])
    return 0.0


class LangChainAdapter:
    """Auto-patches langchain_core.tools.BaseTool.invoke / ainvoke."""

    def install_patches(self) -> None:
        global _original_invoke, _original_ainvoke
        try:
            import langchain_core

            if langchain_core is None:  # pragma: no cover
                return  # pragma: no cover
            import langchain_core.tools as _lc_tools

            if _original_invoke is not None:
                return  # Already patched

            _original_invoke = _lc_tools.BaseTool.invoke
            _original_ainvoke = _lc_tools.BaseTool.ainvoke

            from shekel._context import get_active_budget

            orig_invoke = _original_invoke
            orig_ainvoke = _original_ainvoke

            def _patched_invoke(self: Any, input: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "langchain")
                    result = orig_invoke(self, input, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "langchain")
                    return result
                return orig_invoke(self, input, **kwargs)

            async def _patched_ainvoke(self: Any, input: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "langchain")
                    result = await orig_ainvoke(self, input, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "langchain")
                    return result
                return await orig_ainvoke(self, input, **kwargs)

            _lc_tools.BaseTool.invoke = _patched_invoke  # type: ignore[assignment, method-assign]
            _lc_tools.BaseTool.ainvoke = _patched_ainvoke  # type: ignore[assignment, method-assign]
        except (ImportError, AttributeError, TypeError):
            pass

    def remove_patches(self) -> None:
        global _original_invoke, _original_ainvoke
        try:
            if _original_invoke is None:
                return
            import langchain_core

            if langchain_core is None:  # pragma: no cover
                _original_invoke = None  # pragma: no cover
                _original_ainvoke = None  # pragma: no cover
                return  # pragma: no cover
            import langchain_core.tools as _lc_tools

            _lc_tools.BaseTool.invoke = _original_invoke  # type: ignore[method-assign]
            _lc_tools.BaseTool.ainvoke = _original_ainvoke  # type: ignore[method-assign]
            _original_invoke = None
            _original_ainvoke = None
        except (ImportError, AttributeError, TypeError):  # pragma: no cover
            _original_invoke = None  # pragma: no cover
            _original_ainvoke = None  # pragma: no cover
