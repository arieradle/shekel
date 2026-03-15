"""CrewAI provider adapter for Shekel tool budget tracking."""

from __future__ import annotations

from typing import Any

_original_run: Any = None
_original_arun: Any = None


def _get_price(budget: Any, tool_name: str) -> float:
    if budget.tool_prices is not None and tool_name in budget.tool_prices:
        return float(budget.tool_prices[tool_name])
    return 0.0


class CrewAIAdapter:
    """Auto-patches crewai.tools.BaseTool._run / _arun."""

    def install_patches(self) -> None:
        global _original_run, _original_arun
        try:
            import crewai.tools as _crewai_tools

            if _original_run is not None:
                return  # Already patched

            _original_run = _crewai_tools.BaseTool._run
            _original_arun = _crewai_tools.BaseTool._arun

            from shekel._context import get_active_budget

            orig_run = _original_run
            orig_arun = _original_arun

            def _patched_run(self: Any, *args: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "crewai")
                    result = orig_run(self, *args, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "crewai")
                    return result
                return orig_run(self, *args, **kwargs)

            async def _patched_arun(self: Any, *args: Any, **kwargs: Any) -> Any:
                active = get_active_budget()
                tool_name = getattr(self, "name", self.__class__.__name__)
                if active is not None:
                    active._check_tool_limit(tool_name, "crewai")
                    result = await orig_arun(self, *args, **kwargs)
                    price = _get_price(active, tool_name)
                    active._record_tool_call(tool_name, price, "crewai")
                    return result
                return await orig_arun(self, *args, **kwargs)

            _crewai_tools.BaseTool._run = _patched_run
            _crewai_tools.BaseTool._arun = _patched_arun
        except (ImportError, AttributeError, TypeError):
            pass  # crewai not installed or API changed — skip silently

    def remove_patches(self) -> None:
        global _original_run, _original_arun
        try:
            if _original_run is None:
                return
            import crewai.tools as _crewai_tools

            _crewai_tools.BaseTool._run = _original_run
            _crewai_tools.BaseTool._arun = _original_arun
            _original_run = None
            _original_arun = None
        except (ImportError, AttributeError, TypeError):  # pragma: no cover
            _original_run = None  # pragma: no cover
            _original_arun = None  # pragma: no cover
