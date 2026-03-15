"""MCP (Model Context Protocol) provider adapter for Shekel tool budget tracking."""

from __future__ import annotations

from typing import Any

_original_call_tool: Any = None


def _get_price(budget: Any, tool_name: str) -> float:
    if budget.tool_prices is not None and tool_name in budget.tool_prices:
        return float(budget.tool_prices[tool_name])
    return 0.0


class MCPAdapter:
    """Auto-patches mcp.ClientSession.call_tool for zero-ceremony tool tracking."""

    def install_patches(self) -> None:
        global _original_call_tool
        try:
            import mcp

            if mcp is None:  # pragma: no cover
                return  # pragma: no cover
            import mcp.client.session as _mcp_session

            if _original_call_tool is not None:
                return  # Already patched

            _original_call_tool = _mcp_session.ClientSession.call_tool

            from shekel._context import get_active_budget
            from shekel.exceptions import ToolBudgetExceededError  # noqa: F401

            orig = _original_call_tool

            async def _patched_call_tool(self: Any, name: str, arguments: dict[str, Any]) -> Any:
                active = get_active_budget()
                if active is not None:
                    active._check_tool_limit(name, "mcp")
                    result = await orig(self, name, arguments)
                    price = _get_price(active, name)
                    active._record_tool_call(name, price, "mcp")
                    return result
                return await orig(self, name, arguments)

            _mcp_session.ClientSession.call_tool = _patched_call_tool
        except (ImportError, AttributeError, TypeError):
            pass

    def remove_patches(self) -> None:
        global _original_call_tool
        try:
            if _original_call_tool is None:
                return
            import mcp

            if mcp is None:  # pragma: no cover
                _original_call_tool = None  # pragma: no cover
                return  # pragma: no cover
            import mcp.client.session as _mcp_session

            _mcp_session.ClientSession.call_tool = _original_call_tool
            _original_call_tool = None
        except (ImportError, AttributeError, TypeError):  # pragma: no cover
            _original_call_tool = None  # pragma: no cover
