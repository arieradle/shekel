"""OpenAI Agents SDK provider adapter for Shekel tool budget tracking."""

from __future__ import annotations

from typing import Any

_original_on_invoke_tool: Any = None


def _get_price(budget: Any, tool_name: str) -> float:
    if budget.tool_prices is not None and tool_name in budget.tool_prices:
        return float(budget.tool_prices[tool_name])
    return 0.0


class OpenAIAgentsAdapter:
    """Auto-patches agents.tool.FunctionTool.on_invoke_tool."""

    def install_patches(self) -> None:
        global _original_on_invoke_tool
        try:
            import agents

            if agents is None:  # pragma: no cover
                return  # pragma: no cover
            import agents.tool as _agents_tool

            if _original_on_invoke_tool is not None:
                return  # Already patched

            _original_on_invoke_tool = _agents_tool.FunctionTool.on_invoke_tool

            from shekel._context import get_active_budget

            orig = _original_on_invoke_tool

            async def _patched_on_invoke_tool(self: Any, ctx: Any, input: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "openai-agents")
                    result = await orig(self, ctx, input)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "openai-agents")
                    return result
                return await orig(self, ctx, input)

            _agents_tool.FunctionTool.on_invoke_tool = _patched_on_invoke_tool
        except (ImportError, AttributeError, TypeError):
            pass

    def remove_patches(self) -> None:
        global _original_on_invoke_tool
        try:
            if _original_on_invoke_tool is None:
                return
            import agents

            if agents is None:  # pragma: no cover
                _original_on_invoke_tool = None  # pragma: no cover
                return  # pragma: no cover
            import agents.tool as _agents_tool

            _agents_tool.FunctionTool.on_invoke_tool = _original_on_invoke_tool
            _original_on_invoke_tool = None
        except (ImportError, AttributeError, TypeError):  # pragma: no cover
            _original_on_invoke_tool = None  # pragma: no cover
