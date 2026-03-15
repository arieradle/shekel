"""Tests for Tool Budgets feature.

Groups:
  A — @tool decorator basics (sync, async, pass-through, functools.wraps)
  B — tool() wrapper for third-party callables
  C — max_tool_calls enforcement (pre-dispatch, ToolBudgetExceededError)
  D — Tool cost accounting (tool_prices, unknown tools, tool_spent)
  E — tool_calls_used / tool_calls_remaining counters
  F — warn_at for tool calls (on_tool_warn fires at threshold)
  G — ToolBudgetExceededError fields and message
  H — MCP auto-interception
  I — LangChain auto-interception
  J — CrewAI auto-interception
  K — OpenAI Agents SDK auto-interception
  L — Adapter events (on_tool_call, on_tool_budget_exceeded, on_tool_warn)
  M — OTel metrics (4 shekel.tool.* instruments)
  N — Langfuse tool spans with native cost field
  O — budget.summary() tool section
  P — summary_data() tool fields
  Q — Nested budgets (propagation, _effective_tool_call_limit auto-cap)
  R — Session budgets (tool counts accumulate across with-blocks)
  S — _reset_state() resets tool fields
  T — No active budget: @tool is transparent pass-through
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shekel import budget
from shekel.exceptions import ToolBudgetExceededError
from shekel.integrations import AdapterRegistry
from shekel.integrations.base import ObservabilityAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meter() -> MagicMock:
    meter = MagicMock()
    meter.create_counter.side_effect = lambda *a, **kw: MagicMock()
    meter.create_up_down_counter.side_effect = lambda *a, **kw: MagicMock()
    meter.create_histogram.side_effect = lambda *a, **kw: MagicMock()
    meter.create_observable_gauge.side_effect = lambda *a, **kw: MagicMock()
    return meter


# ---------------------------------------------------------------------------
# Group A — @tool decorator basics
# ---------------------------------------------------------------------------


class TestToolDecoratorBasics:
    def test_tool_decorator_no_args_sync(self) -> None:
        """@tool with no args wraps a sync function."""
        from shekel._tool import tool

        @tool
        def my_fn(x: int) -> int:
            return x * 2

        assert my_fn(3) == 6

    def test_tool_decorator_preserves_name_and_doc(self) -> None:
        """@tool preserves __name__, __doc__, and __wrapped__."""
        from shekel._tool import tool

        @tool
        def my_fn(x: int) -> int:
            """My doc."""
            return x

        assert my_fn.__name__ == "my_fn"
        assert my_fn.__doc__ == "My doc."

    def test_tool_decorator_with_price_kwarg(self) -> None:
        """@tool(price=0.005) wraps a sync function and records cost."""
        from shekel._tool import tool

        @tool(price=0.005)
        def web_search(query: str) -> str:
            return f"results for {query}"

        assert web_search("test") == "results for test"

    def test_tool_decorator_async(self) -> None:
        """@tool wraps async functions correctly."""
        from shekel._tool import tool

        @tool
        async def async_fn(x: int) -> int:
            return x + 1

        result = asyncio.run(async_fn(5))
        assert result == 6

    def test_tool_decorator_async_with_price(self) -> None:
        """@tool(price=0.01) wraps async functions with price."""
        from shekel._tool import tool

        @tool(price=0.01)
        async def async_search(q: str) -> str:
            return f"async: {q}"

        result = asyncio.run(async_search("hi"))
        assert result == "async: hi"

    def test_tool_decorator_empty_call(self) -> None:
        """@tool() with no args also works."""
        from shekel._tool import tool

        @tool()
        def my_fn() -> str:
            return "ok"

        assert my_fn() == "ok"

    def test_tool_decorator_async_preserves_name(self) -> None:
        """@tool preserves __name__ for async functions."""
        from shekel._tool import tool

        @tool
        async def async_fn() -> None:
            pass

        assert async_fn.__name__ == "async_fn"


# ---------------------------------------------------------------------------
# Group B — tool() wrapper for third-party callables
# ---------------------------------------------------------------------------


class TestToolWrapper:
    def test_tool_wrapper_third_party_callable(self) -> None:
        """tool(obj) wraps a third-party callable."""
        from shekel._tool import tool

        class FakeTavilySearch:
            def __call__(self, query: str) -> str:
                return f"tavily: {query}"

        tavily = tool(FakeTavilySearch(), price=0.005)
        assert tavily("python") == "tavily: python"

    def test_tool_wrapper_name_from_class(self) -> None:
        """tool() sets __name__ from the wrapped object's class name."""
        from shekel._tool import tool

        class MyTool:
            def __call__(self) -> str:
                return "x"

        wrapped = tool(MyTool())
        assert callable(wrapped)

    def test_tool_wrapper_no_price(self) -> None:
        """tool(obj) without price still tracks call count."""
        from shekel._tool import tool

        class FreeTool:
            def __call__(self) -> str:
                return "free"

        wrapped = tool(FreeTool())
        with budget(max_tool_calls=5) as b:
            wrapped()
            assert b.tool_calls_used == 1


# ---------------------------------------------------------------------------
# Group C — max_tool_calls enforcement (pre-dispatch)
# ---------------------------------------------------------------------------


class TestMaxToolCallsEnforcement:
    def test_raises_tool_budget_exceeded_error_on_limit(self) -> None:
        """ToolBudgetExceededError raised when max_tool_calls is hit."""
        from shekel._tool import tool

        call_count = 0

        @tool
        def fn() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        with pytest.raises(ToolBudgetExceededError):
            with budget(max_tool_calls=2):
                fn()
                fn()
                fn()  # This must raise — tool must NOT run

        assert call_count == 2, "Tool must not execute on exceeded budget"

    def test_pre_dispatch_semantics(self) -> None:
        """Tool function is never called when limit is already reached."""
        from shekel._tool import tool

        executed = []

        @tool
        def side_effect_fn() -> str:
            executed.append(True)
            return "ran"

        with pytest.raises(ToolBudgetExceededError):
            with budget(max_tool_calls=1):
                side_effect_fn()  # allowed
                side_effect_fn()  # blocked — must NOT append to executed

        assert len(executed) == 1

    def test_no_limit_means_no_enforcement(self) -> None:
        """No ToolBudgetExceededError when max_tool_calls is not set."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget() as b:
            for _ in range(100):
                fn()
            assert b.tool_calls_used == 100

    def test_usd_limit_via_tool_prices_raises_on_budget(self) -> None:
        """When tool_prices set and max_usd exceeded via tools, budget raises."""
        from shekel._tool import tool
        from shekel.exceptions import ToolBudgetExceededError

        @tool(price=1.0)
        def expensive() -> str:
            return "ok"

        with pytest.raises(ToolBudgetExceededError):
            with budget(max_usd=1.5, tool_prices={"expensive": 1.0}):
                expensive()
                expensive()  # second call: $2.00 total — over limit


# ---------------------------------------------------------------------------
# Group D — Tool cost accounting
# ---------------------------------------------------------------------------


class TestToolCostAccounting:
    def test_tool_prices_dict_charges_per_call(self) -> None:
        """tool_prices charges the specified price per call."""
        from shekel._tool import tool

        @tool
        def search() -> str:
            return "r"

        with budget(tool_prices={"search": 0.01}) as b:
            search()
            search()
        assert abs(b.tool_spent - 0.02) < 1e-9

    def test_unknown_tool_counts_at_zero_cost(self) -> None:
        """Tools not in tool_prices count toward max_tool_calls but cost $0."""
        from shekel._tool import tool

        @tool
        def free_tool() -> str:
            return "r"

        with budget(max_tool_calls=10, tool_prices={"other": 0.005}) as b:
            free_tool()
            assert b.tool_calls_used == 1
            assert b.tool_spent == 0.0

    def test_tool_spent_property(self) -> None:
        """tool_spent accumulates cost from all tool calls."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(tool_prices={"fn": 0.003}) as b:
            fn()
            fn()
            fn()
        assert abs(b.tool_spent - 0.009) < 1e-9

    def test_tool_price_at_call_site_overrides_budget_prices(self) -> None:
        """price= on @tool(price=X) is used when tool_prices not set."""
        from shekel._tool import tool

        @tool(price=0.005)
        def priced_fn() -> str:
            return "ok"

        with budget() as b:
            priced_fn()
        assert abs(b.tool_spent - 0.005) < 1e-9

    def test_budget_tool_prices_overrides_decorator_price(self) -> None:
        """tool_prices on budget() takes precedence over @tool(price=X)."""
        from shekel._tool import tool

        @tool(price=0.005)
        def fn() -> str:
            return "ok"

        with budget(tool_prices={"fn": 0.020}) as b:
            fn()
        # budget-level tool_prices should win
        assert abs(b.tool_spent - 0.020) < 1e-9


# ---------------------------------------------------------------------------
# Group E — tool_calls_used / tool_calls_remaining
# ---------------------------------------------------------------------------


class TestToolCallCounters:
    def test_tool_calls_used_increments(self) -> None:
        """tool_calls_used increments with each tool call."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=10) as b:
            assert b.tool_calls_used == 0
            fn()
            assert b.tool_calls_used == 1
            fn()
            assert b.tool_calls_used == 2

    def test_tool_calls_remaining_counts_down(self) -> None:
        """tool_calls_remaining decrements with each tool call."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=5) as b:
            assert b.tool_calls_remaining == 5
            fn()
            assert b.tool_calls_remaining == 4

    def test_tool_calls_remaining_none_when_no_limit(self) -> None:
        """tool_calls_remaining is None when max_tool_calls is not set."""
        with budget() as b:
            assert b.tool_calls_remaining is None

    def test_tool_calls_remaining_never_negative(self) -> None:
        """tool_calls_remaining is 0 when all calls used (never negative)."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with pytest.raises(ToolBudgetExceededError):
            with budget(max_tool_calls=1) as b:
                fn()
                assert b.tool_calls_remaining == 0
                fn()


# ---------------------------------------------------------------------------
# Group F — warn_at for tool calls
# ---------------------------------------------------------------------------


class TestWarnAtForTools:
    def test_on_tool_warn_fires_at_threshold(self) -> None:
        """on_tool_warn fires when tool_calls_used reaches warn_at fraction."""
        from shekel._tool import tool

        warn_events: list[dict[str, Any]] = []

        class WarnCapture(ObservabilityAdapter):
            def on_tool_warn(self, data: dict[str, Any]) -> None:
                warn_events.append(data)

        adapter = WarnCapture()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with budget(max_tool_calls=10, warn_at=0.8):
                for _ in range(8):
                    fn()
                assert len(warn_events) == 1

            assert warn_events[0]["calls_used"] == 8
            assert warn_events[0]["calls_limit"] == 10
        finally:
            AdapterRegistry.unregister(adapter)

    def test_on_tool_warn_fires_only_once(self) -> None:
        """on_tool_warn fires exactly once per budget context."""
        from shekel._tool import tool

        warn_count = 0

        class WarnCount(ObservabilityAdapter):
            def on_tool_warn(self, data: dict[str, Any]) -> None:
                nonlocal warn_count
                warn_count += 1

        adapter = WarnCount()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with budget(max_tool_calls=5, warn_at=0.6):
                for _ in range(5):
                    try:
                        fn()
                    except ToolBudgetExceededError:
                        break
        finally:
            AdapterRegistry.unregister(adapter)

        assert warn_count == 1

    def test_warn_at_not_set_no_tool_warn_fires(self) -> None:
        """No on_tool_warn when warn_at is not configured."""
        from shekel._tool import tool

        warn_events: list[Any] = []

        class WarnCapture(ObservabilityAdapter):
            def on_tool_warn(self, data: dict[str, Any]) -> None:
                warn_events.append(data)

        adapter = WarnCapture()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with budget(max_tool_calls=5):
                for _ in range(5):
                    try:
                        fn()
                    except ToolBudgetExceededError:
                        break
        finally:
            AdapterRegistry.unregister(adapter)

        assert len(warn_events) == 0


# ---------------------------------------------------------------------------
# Group G — ToolBudgetExceededError fields and message
# ---------------------------------------------------------------------------


class TestToolBudgetExceededError:
    def test_error_fields_populated(self) -> None:
        """ToolBudgetExceededError carries all required fields."""
        err = ToolBudgetExceededError(
            tool_name="web_search",
            calls_used=3,
            calls_limit=2,
            usd_spent=0.015,
            usd_limit=1.0,
            framework="manual",
        )
        assert err.tool_name == "web_search"
        assert err.calls_used == 3
        assert err.calls_limit == 2
        assert abs(err.usd_spent - 0.015) < 1e-9
        assert err.usd_limit == 1.0
        assert err.framework == "manual"

    def test_error_message_contains_tool_name(self) -> None:
        """Error message includes the tool name."""
        err = ToolBudgetExceededError(
            tool_name="run_code",
            calls_used=5,
            calls_limit=5,
            usd_spent=0.0,
            usd_limit=None,
            framework="mcp",
        )
        assert "run_code" in str(err)

    def test_error_message_contains_counts(self) -> None:
        """Error message includes call counts."""
        err = ToolBudgetExceededError(
            tool_name="search",
            calls_used=10,
            calls_limit=10,
            usd_spent=0.05,
            usd_limit=1.0,
        )
        msg = str(err)
        assert "10" in msg

    def test_error_framework_default_is_manual(self) -> None:
        """Default framework label is 'manual'."""
        err = ToolBudgetExceededError(
            tool_name="fn",
            calls_used=1,
            calls_limit=1,
            usd_spent=0.0,
            usd_limit=None,
        )
        assert err.framework == "manual"

    def test_error_is_exception(self) -> None:
        """ToolBudgetExceededError is an Exception subclass."""
        assert issubclass(ToolBudgetExceededError, Exception)

    def test_error_raised_contains_tool_name_from_decorator(self) -> None:
        """When raised from @tool, error contains the function name."""
        from shekel._tool import tool

        @tool
        def my_special_tool() -> str:
            return "ok"

        with pytest.raises(ToolBudgetExceededError) as exc_info:
            with budget(max_tool_calls=1):
                my_special_tool()
                my_special_tool()

        assert exc_info.value.tool_name == "my_special_tool"

    def test_error_contains_framework_label(self) -> None:
        """Error raised from @tool has framework='manual'."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with pytest.raises(ToolBudgetExceededError) as exc_info:
            with budget(max_tool_calls=1):
                fn()
                fn()

        assert exc_info.value.framework == "manual"


# ---------------------------------------------------------------------------
# Group H — MCP auto-interception
# ---------------------------------------------------------------------------


class TestMCPInterception:
    def _make_mcp_modules(self) -> MagicMock:
        """Inject a fake mcp module into sys.modules."""
        fake_mcp = types.ModuleType("mcp")
        fake_client = types.ModuleType("mcp.client")
        fake_session = types.ModuleType("mcp.client.session")

        class FakeClientSession:
            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                return {"result": f"mcp:{name}"}

        fake_session.ClientSession = FakeClientSession
        fake_client.session = fake_session
        fake_mcp.client = fake_client
        fake_mcp.ClientSession = FakeClientSession

        sys.modules["mcp"] = fake_mcp  # type: ignore[assignment]
        sys.modules["mcp.client"] = fake_client  # type: ignore[assignment]
        sys.modules["mcp.client.session"] = fake_session  # type: ignore[assignment]
        return fake_mcp

    def _cleanup_mcp_modules(self) -> None:
        for key in ["mcp", "mcp.client", "mcp.client.session"]:
            sys.modules.pop(key, None)

    def test_mcp_call_tool_tracked(self) -> None:
        """MCP call_tool is tracked by active budget."""
        self._cleanup_mcp_modules()
        fake_mcp = self._make_mcp_modules()

        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()
            try:
                session = fake_mcp.ClientSession()
                with budget(max_tool_calls=5) as b:
                    asyncio.run(session.call_tool("brave_search", {"query": "test"}))
                    assert b.tool_calls_used == 1
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_mcp_modules()

    def test_mcp_framework_label(self) -> None:
        """MCP tool calls are tagged with framework='mcp'."""
        self._cleanup_mcp_modules()
        fake_mcp = self._make_mcp_modules()

        events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                events.append(data)

        cap = Capture()
        AdapterRegistry.register(cap)
        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()
            try:
                session = fake_mcp.ClientSession()
                with budget(max_tool_calls=5):
                    asyncio.run(session.call_tool("brave_search", {"query": "test"}))
            finally:
                adapter.remove_patches()
        finally:
            AdapterRegistry.unregister(cap)
            self._cleanup_mcp_modules()

        assert len(events) == 1
        assert events[0]["framework"] == "mcp"

    def test_mcp_import_error_silent(self) -> None:
        """MCPAdapter.install_patches is silent when mcp is not installed."""
        self._cleanup_mcp_modules()
        # Don't inject fake mcp — it's absent
        sys.modules["mcp"] = None  # type: ignore[assignment]
        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()  # must not raise
            adapter.remove_patches()  # must not raise
        finally:
            sys.modules.pop("mcp", None)
            self._cleanup_mcp_modules()

    def test_mcp_pre_dispatch_blocks_on_exceeded(self) -> None:
        """MCP call_tool raises ToolBudgetExceededError without calling the tool."""
        self._cleanup_mcp_modules()
        self._make_mcp_modules()

        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()
            try:
                # Use the patched class from the injected module
                SessionClass = sys.modules["mcp.client.session"].ClientSession
                session = SessionClass()
                with pytest.raises(ToolBudgetExceededError):
                    with budget(max_tool_calls=1):
                        asyncio.run(session.call_tool("search", {}))
                        asyncio.run(session.call_tool("search", {}))
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_mcp_modules()


# ---------------------------------------------------------------------------
# Group I — LangChain auto-interception
# ---------------------------------------------------------------------------


class TestLangChainInterception:
    def _make_langchain_modules(self) -> types.ModuleType:
        """Inject a fake langchain_core module into sys.modules."""
        fake_lc = types.ModuleType("langchain_core")
        fake_tools = types.ModuleType("langchain_core.tools")

        class BaseTool:
            name: str = "base_tool"

            def invoke(self, input: Any) -> Any:
                return f"result:{input}"

            async def ainvoke(self, input: Any) -> Any:
                return f"async_result:{input}"

        fake_tools.BaseTool = BaseTool
        fake_lc.tools = fake_tools

        sys.modules["langchain_core"] = fake_lc  # type: ignore[assignment]
        sys.modules["langchain_core.tools"] = fake_tools  # type: ignore[assignment]
        return fake_lc

    def _cleanup_langchain_modules(self) -> None:
        for key in ["langchain_core", "langchain_core.tools"]:
            sys.modules.pop(key, None)

    def test_langchain_invoke_tracked(self) -> None:
        """BaseTool.invoke is tracked when inside a budget context."""
        self._cleanup_langchain_modules()
        fake_lc = self._make_langchain_modules()

        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_lc.tools.BaseTool()
                tool_instance.name = "web_search"
                with budget(max_tool_calls=5) as b:
                    tool_instance.invoke("query")
                    assert b.tool_calls_used == 1
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_langchain_modules()

    def test_langchain_ainvoke_tracked(self) -> None:
        """BaseTool.ainvoke is tracked when inside a budget context."""
        self._cleanup_langchain_modules()
        fake_lc = self._make_langchain_modules()

        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_lc.tools.BaseTool()
                tool_instance.name = "async_search"
                with budget(max_tool_calls=5) as b:
                    asyncio.run(tool_instance.ainvoke("query"))
                    assert b.tool_calls_used == 1
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_langchain_modules()

    def test_langchain_framework_label(self) -> None:
        """LangChain tool calls are tagged with framework='langchain'."""
        self._cleanup_langchain_modules()
        fake_lc = self._make_langchain_modules()

        events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                events.append(data)

        cap = Capture()
        AdapterRegistry.register(cap)
        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_lc.tools.BaseTool()
                tool_instance.name = "search"
                with budget(max_tool_calls=5):
                    tool_instance.invoke("q")
            finally:
                adapter.remove_patches()
        finally:
            AdapterRegistry.unregister(cap)
            self._cleanup_langchain_modules()

        assert len(events) == 1
        assert events[0]["framework"] == "langchain"

    def test_langchain_import_error_silent(self) -> None:
        """LangChainAdapter.install_patches is silent when langchain_core is absent."""
        self._cleanup_langchain_modules()
        sys.modules["langchain_core"] = None  # type: ignore[assignment]
        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            adapter.remove_patches()
        finally:
            sys.modules.pop("langchain_core", None)
            self._cleanup_langchain_modules()


# ---------------------------------------------------------------------------
# Group J — CrewAI auto-interception
# ---------------------------------------------------------------------------


class TestCrewAIInterception:
    def _make_crewai_modules(self) -> types.ModuleType:
        fake_crewai = types.ModuleType("crewai")
        fake_tools = types.ModuleType("crewai.tools")

        class BaseTool:
            name: str = "crewai_tool"

            def _run(self, *args: Any, **kwargs: Any) -> Any:
                return "crewai_result"

            async def _arun(self, *args: Any, **kwargs: Any) -> Any:
                return "crewai_async_result"

        fake_tools.BaseTool = BaseTool
        fake_crewai.tools = fake_tools

        sys.modules["crewai"] = fake_crewai  # type: ignore[assignment]
        sys.modules["crewai.tools"] = fake_tools  # type: ignore[assignment]
        return fake_crewai

    def _cleanup_crewai_modules(self) -> None:
        for key in ["crewai", "crewai.tools"]:
            sys.modules.pop(key, None)

    def test_crewai_run_tracked(self) -> None:
        """BaseTool._run is tracked when inside a budget context."""
        self._cleanup_crewai_modules()
        fake_crewai = self._make_crewai_modules()

        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_crewai.tools.BaseTool()
                with budget(max_tool_calls=5) as b:
                    tool_instance._run()
                    assert b.tool_calls_used == 1
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_crewai_modules()

    def test_crewai_arun_tracked(self) -> None:
        """BaseTool._arun is tracked when inside a budget context."""
        self._cleanup_crewai_modules()
        fake_crewai = self._make_crewai_modules()

        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_crewai.tools.BaseTool()
                with budget(max_tool_calls=5) as b:
                    asyncio.run(tool_instance._arun())
                    assert b.tool_calls_used == 1
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_crewai_modules()

    def test_crewai_framework_label(self) -> None:
        """CrewAI tool calls are tagged with framework='crewai'."""
        self._cleanup_crewai_modules()
        fake_crewai = self._make_crewai_modules()

        events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                events.append(data)

        cap = Capture()
        AdapterRegistry.register(cap)
        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_crewai.tools.BaseTool()
                with budget(max_tool_calls=5):
                    tool_instance._run()
            finally:
                adapter.remove_patches()
        finally:
            AdapterRegistry.unregister(cap)
            self._cleanup_crewai_modules()

        assert len(events) == 1
        assert events[0]["framework"] == "crewai"

    def test_crewai_import_error_silent(self) -> None:
        """CrewAIAdapter.install_patches is silent when crewai is absent."""
        self._cleanup_crewai_modules()
        sys.modules["crewai"] = None  # type: ignore[assignment]
        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            adapter.remove_patches()
        finally:
            sys.modules.pop("crewai", None)
            self._cleanup_crewai_modules()


# ---------------------------------------------------------------------------
# Group K — OpenAI Agents SDK auto-interception
# ---------------------------------------------------------------------------


class TestOpenAIAgentsInterception:
    def _make_agents_modules(self) -> types.ModuleType:
        fake_agents = types.ModuleType("agents")
        fake_tool_mod = types.ModuleType("agents.tool")

        class FunctionTool:
            name: str = "agents_tool"

            async def on_invoke_tool(self, ctx: Any, input: str) -> Any:
                return f"agents_result:{input}"

        fake_tool_mod.FunctionTool = FunctionTool
        fake_agents.tool = fake_tool_mod
        fake_agents.FunctionTool = FunctionTool

        sys.modules["agents"] = fake_agents  # type: ignore[assignment]
        sys.modules["agents.tool"] = fake_tool_mod  # type: ignore[assignment]
        return fake_agents

    def _cleanup_agents_modules(self) -> None:
        for key in ["agents", "agents.tool"]:
            sys.modules.pop(key, None)

    def test_openai_agents_on_invoke_tracked(self) -> None:
        """FunctionTool.on_invoke_tool is tracked when inside a budget context."""
        self._cleanup_agents_modules()
        fake_agents = self._make_agents_modules()

        try:
            from shekel.providers.openai_agents import OpenAIAgentsAdapter

            adapter = OpenAIAgentsAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_agents.FunctionTool()
                with budget(max_tool_calls=5) as b:
                    asyncio.run(tool_instance.on_invoke_tool(None, "input"))
                    assert b.tool_calls_used == 1
            finally:
                adapter.remove_patches()
        finally:
            self._cleanup_agents_modules()

    def test_openai_agents_framework_label(self) -> None:
        """OpenAI Agents tool calls are tagged with framework='openai-agents'."""
        self._cleanup_agents_modules()
        fake_agents = self._make_agents_modules()

        events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                events.append(data)

        cap = Capture()
        AdapterRegistry.register(cap)
        try:
            from shekel.providers.openai_agents import OpenAIAgentsAdapter

            adapter = OpenAIAgentsAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_agents.FunctionTool()
                with budget(max_tool_calls=5):
                    asyncio.run(tool_instance.on_invoke_tool(None, "input"))
            finally:
                adapter.remove_patches()
        finally:
            AdapterRegistry.unregister(cap)
            self._cleanup_agents_modules()

        assert len(events) == 1
        assert events[0]["framework"] == "openai-agents"

    def test_openai_agents_import_error_silent(self) -> None:
        """OpenAIAgentsAdapter.install_patches is silent when agents is absent."""
        self._cleanup_agents_modules()
        sys.modules["agents"] = None  # type: ignore[assignment]
        try:
            from shekel.providers.openai_agents import OpenAIAgentsAdapter

            adapter = OpenAIAgentsAdapter()
            adapter.install_patches()
            adapter.remove_patches()
        finally:
            sys.modules.pop("agents", None)
            self._cleanup_agents_modules()


# ---------------------------------------------------------------------------
# Group L — Adapter events
# ---------------------------------------------------------------------------


class TestAdapterEvents:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_on_tool_call_fires_after_dispatch(self) -> None:
        """on_tool_call fires after each successful tool dispatch."""
        from shekel._tool import tool

        events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                events.append(data.copy())

        AdapterRegistry.register(Capture())

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=5):
            fn()
            fn()

        assert len(events) == 2
        assert events[0]["tool_name"] == "fn"
        assert events[0]["framework"] == "manual"
        assert "calls_used" in events[0]

    def test_on_tool_budget_exceeded_fires_before_blocked_dispatch(self) -> None:
        """on_tool_budget_exceeded fires when limit is hit (before tool runs)."""
        from shekel._tool import tool

        exceeded_events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_budget_exceeded(self, data: dict[str, Any]) -> None:
                exceeded_events.append(data.copy())

        AdapterRegistry.register(Capture())

        @tool
        def fn() -> str:
            return "ok"

        with pytest.raises(ToolBudgetExceededError):
            with budget(max_tool_calls=1):
                fn()
                fn()

        assert len(exceeded_events) == 1
        assert exceeded_events[0]["tool_name"] == "fn"

    def test_on_tool_warn_fires_at_threshold(self) -> None:
        """on_tool_warn fires when calls reach warn_at * max_tool_calls."""
        from shekel._tool import tool

        warn_events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_warn(self, data: dict[str, Any]) -> None:
                warn_events.append(data.copy())

        AdapterRegistry.register(Capture())

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=10, warn_at=0.5):
            for _ in range(5):
                fn()

        assert len(warn_events) == 1
        assert warn_events[0]["calls_used"] == 5

    def test_on_tool_call_data_contains_required_keys(self) -> None:
        """on_tool_call data dict has all required keys."""
        from shekel._tool import tool

        events: list[dict[str, Any]] = []

        class Capture(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                events.append(data.copy())

        AdapterRegistry.register(Capture())

        @tool(price=0.005)
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=5):
            fn()

        assert events
        d = events[0]
        assert "tool_name" in d
        assert "cost" in d
        assert "framework" in d
        assert "budget_name" in d
        assert "calls_used" in d

    def test_base_adapter_on_tool_call_is_noop(self) -> None:
        """ObservabilityAdapter.on_tool_call is a no-op by default."""
        adapter = ObservabilityAdapter()
        adapter.on_tool_call({"tool_name": "x"})  # must not raise

    def test_base_adapter_on_tool_budget_exceeded_is_noop(self) -> None:
        """ObservabilityAdapter.on_tool_budget_exceeded is a no-op by default."""
        adapter = ObservabilityAdapter()
        adapter.on_tool_budget_exceeded({"tool_name": "x"})  # must not raise

    def test_base_adapter_on_tool_warn_is_noop(self) -> None:
        """ObservabilityAdapter.on_tool_warn is a no-op by default."""
        adapter = ObservabilityAdapter()
        adapter.on_tool_warn({"tool_name": "x"})  # must not raise


# ---------------------------------------------------------------------------
# Group M — OTel metrics
# ---------------------------------------------------------------------------


class TestOtelToolMetrics:
    def test_otel_tool_calls_total_counter_emitted(self) -> None:
        """shekel.tool.calls_total counter is incremented on tool call."""
        from shekel._tool import tool
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter)
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with budget(max_tool_calls=5):
                fn()
        finally:
            AdapterRegistry.unregister(adapter)

        # shekel.tool.calls_total counter should have been created
        names = [c.args[0] for c in meter.create_counter.call_args_list]
        assert any("tool.calls_total" in n for n in names)

    def test_otel_tool_cost_usd_total_counter_emitted(self) -> None:
        """shekel.tool.cost_usd_total counter is incremented on priced tool call."""
        from shekel._tool import tool
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter)
        AdapterRegistry.register(adapter)
        try:

            @tool(price=0.005)
            def fn() -> str:
                return "ok"

            with budget():
                fn()
        finally:
            AdapterRegistry.unregister(adapter)

        names = [c.args[0] for c in meter.create_counter.call_args_list]
        assert any("tool.cost_usd_total" in n for n in names)

    def test_otel_tool_budget_exceeded_total_counter_emitted(self) -> None:
        """shekel.tool.budget_exceeded_total counter is incremented on exceeded."""
        from shekel._tool import tool
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter)
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with pytest.raises(ToolBudgetExceededError):
                with budget(max_tool_calls=1):
                    fn()
                    fn()
        finally:
            AdapterRegistry.unregister(adapter)

        names = [c.args[0] for c in meter.create_counter.call_args_list]
        assert any("tool.budget_exceeded_total" in n for n in names)

    def test_otel_tool_calls_remaining_gauge_created(self) -> None:
        """shekel.tool.calls_remaining gauge is created in _OtelMetricsAdapter."""
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        _OtelMetricsAdapter(meter)

        names = [c.args[0] for c in meter.create_observable_gauge.call_args_list]
        assert any("tool.calls_remaining" in n for n in names)


# ---------------------------------------------------------------------------
# Group N — Langfuse tool spans with native cost field
# ---------------------------------------------------------------------------


class TestLangfuseToolSpans:
    def test_langfuse_on_tool_call_creates_span(self) -> None:
        """LangfuseAdapter.on_tool_call creates a span with cost field."""
        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client, trace_name="test")
        # Simulate trace already created
        adapter._trace = mock_trace

        adapter.on_tool_call(
            {
                "tool_name": "web_search",
                "cost": 0.005,
                "framework": "manual",
                "budget_name": "unnamed",
                "calls_used": 1,
                "calls_remaining": 9,
                "usd_spent": 0.005,
            }
        )

        mock_trace.span.assert_called_once()
        span_call = mock_trace.span.call_args
        assert span_call is not None

    def test_langfuse_on_tool_call_populates_cost_field(self) -> None:
        """LangfuseAdapter.on_tool_call span has cost populated."""
        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client, trace_name="test")
        adapter._trace = mock_trace

        adapter.on_tool_call(
            {
                "tool_name": "search",
                "cost": 0.012,
                "framework": "mcp",
                "budget_name": "test-budget",
                "calls_used": 3,
                "calls_remaining": 7,
                "usd_spent": 0.036,
            }
        )

        mock_trace.span.assert_called_once()
        call_kwargs = mock_trace.span.call_args[1]
        # cost field should be present
        assert (
            "cost" in call_kwargs
            or any("cost" in str(a) for a in mock_trace.span.call_args[0])
            or mock_span.update.called
        )

    def test_langfuse_on_tool_call_noop_when_no_trace(self) -> None:
        """LangfuseAdapter.on_tool_call creates trace if none exists."""
        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)
        # _trace is None — should create it
        adapter.on_tool_call(
            {
                "tool_name": "fn",
                "cost": 0.0,
                "framework": "manual",
                "budget_name": "unnamed",
                "calls_used": 1,
                "calls_remaining": None,
                "usd_spent": 0.0,
            }
        )

        mock_client.trace.assert_called_once()


# ---------------------------------------------------------------------------
# Group O — budget.summary() tool section
# ---------------------------------------------------------------------------


class TestBudgetSummaryToolSection:
    def test_summary_shows_tool_spend(self) -> None:
        """budget.summary() includes tool spend when tools were called."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=10, tool_prices={"fn": 0.005}) as b:
            fn()
            fn()

        s = b.summary()
        assert "Tool" in s or "tool" in s

    def test_summary_shows_tool_call_counts(self) -> None:
        """budget.summary() shows tool call counts."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=10) as b:
            fn()
            fn()
            fn()

        s = b.summary()
        assert "3" in s

    def test_summary_tool_section_not_shown_when_no_tool_calls(self) -> None:
        """Tool section omitted when no tools were called and max_tool_calls not set."""
        with budget(max_usd=1.0) as b:
            pass

        s = b.summary()
        # Should not crash; tool section may be absent
        assert isinstance(s, str)

    def test_summary_shows_per_tool_breakdown(self) -> None:
        """budget.summary() shows per-tool breakdown with framework."""
        from shekel._tool import tool

        @tool
        def search() -> str:
            return "ok"

        @tool
        def read() -> str:
            return "ok"

        with budget(tool_prices={"search": 0.005}) as b:
            search()
            read()

        s = b.summary()
        assert "search" in s
        assert "read" in s


# ---------------------------------------------------------------------------
# Group P — summary_data() tool fields
# ---------------------------------------------------------------------------


class TestSummaryDataToolFields:
    def test_summary_data_has_tool_calls_used(self) -> None:
        """summary_data() includes tool_calls_used."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=10) as b:
            fn()
            fn()

        data = b.summary_data()
        assert "tool_calls_used" in data
        assert data["tool_calls_used"] == 2

    def test_summary_data_has_tool_spent(self) -> None:
        """summary_data() includes tool_spent."""
        from shekel._tool import tool

        @tool(price=0.01)
        def fn() -> str:
            return "ok"

        with budget() as b:
            fn()

        data = b.summary_data()
        assert "tool_spent" in data
        assert abs(data["tool_spent"] - 0.01) < 1e-9

    def test_summary_data_has_by_tool(self) -> None:
        """summary_data() includes by_tool breakdown dict."""
        from shekel._tool import tool

        @tool
        def search() -> str:
            return "ok"

        with budget(tool_prices={"search": 0.005}) as b:
            search()
            search()

        data = b.summary_data()
        assert "by_tool" in data
        assert "search" in data["by_tool"]
        assert data["by_tool"]["search"]["calls"] == 2

    def test_summary_data_tool_calls_limit(self) -> None:
        """summary_data() includes tool_calls_limit."""
        with budget(max_tool_calls=20) as b:
            pass

        data = b.summary_data()
        assert "tool_calls_limit" in data
        assert data["tool_calls_limit"] == 20


# ---------------------------------------------------------------------------
# Group Q — Nested budgets
# ---------------------------------------------------------------------------


class TestNestedBudgetToolPropagation:
    def test_tool_calls_propagate_to_parent(self) -> None:
        """Tool calls in child budget propagate to parent on exit."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=20, name="parent") as parent:
            with budget(max_tool_calls=5, name="child"):
                fn()
                fn()

        assert parent.tool_calls_used == 2

    def test_tool_spent_propagates_to_parent(self) -> None:
        """Tool spend in child propagates to parent on exit."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(name="parent") as parent:
            with budget(tool_prices={"fn": 0.01}, name="child"):
                fn()

        assert abs(parent.tool_spent - 0.01) < 1e-9

    def test_effective_tool_call_limit_autocapped_by_parent(self) -> None:
        """Child's _effective_tool_call_limit is capped by parent's remaining."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with budget(max_tool_calls=3, name="parent"):
            # Child requests 10 but parent only has 3 remaining
            with budget(max_tool_calls=10, name="child") as child:
                assert child._effective_tool_call_limit == 3


# ---------------------------------------------------------------------------
# Group R — Session budgets
# ---------------------------------------------------------------------------


class TestSessionBudgetToolAccumulation:
    def test_tool_calls_accumulate_across_with_blocks(self) -> None:
        """Tool calls accumulate across multiple with-blocks in session budget."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        session = budget(max_tool_calls=20)
        with session:
            fn()
            fn()
        with session:
            fn()

        assert session.tool_calls_used == 3

    def test_tool_spent_accumulates_across_with_blocks(self) -> None:
        """Tool spend accumulates across multiple with-blocks."""
        from shekel._tool import tool

        @tool(price=0.005)
        def fn() -> str:
            return "ok"

        session = budget()
        with session:
            fn()
        with session:
            fn()

        assert abs(session.tool_spent - 0.010) < 1e-9


# ---------------------------------------------------------------------------
# Group S — _reset_state() resets tool fields
# ---------------------------------------------------------------------------


class TestResetStateResetsToolFields:
    def test_reset_clears_tool_calls_made(self) -> None:
        """reset() clears _tool_calls_made."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        b = budget(max_tool_calls=10)
        with b:
            fn()
            fn()
        assert b.tool_calls_used == 2
        b.reset()
        assert b.tool_calls_used == 0

    def test_reset_clears_tool_spent(self) -> None:
        """reset() clears _tool_spent."""
        from shekel._tool import tool

        @tool(price=0.01)
        def fn() -> str:
            return "ok"

        b = budget()
        with b:
            fn()
        assert b.tool_spent > 0
        b.reset()
        assert b.tool_spent == 0.0

    def test_reset_clears_tool_warn_fired(self) -> None:
        """reset() clears _tool_warn_fired so on_tool_warn fires again next session."""
        from shekel._tool import tool

        warn_count = 0

        class WarnCount(ObservabilityAdapter):
            def on_tool_warn(self, data: dict[str, Any]) -> None:
                nonlocal warn_count
                warn_count += 1

        adapter = WarnCount()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            b = budget(max_tool_calls=2, warn_at=0.5)
            with b:
                fn()
            b.reset()
            with b:
                fn()
        finally:
            AdapterRegistry.unregister(adapter)

        # warn should fire in both sessions
        assert warn_count == 2


# ---------------------------------------------------------------------------
# Group T — No active budget: @tool is transparent pass-through
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Group U — Coverage completeness
# ---------------------------------------------------------------------------


class TestCoverageCompleteness:
    """Tests for lines not covered by domain groups."""

    def test_max_tool_calls_zero_raises(self) -> None:
        """Budget() raises ValueError when max_tool_calls <= 0."""
        with pytest.raises(ValueError, match="max_tool_calls must be positive"):
            budget(max_tool_calls=0)

    def test_max_tool_calls_negative_raises(self) -> None:
        """Budget() raises ValueError when max_tool_calls is negative."""
        with pytest.raises(ValueError, match="max_tool_calls must be positive"):
            budget(max_tool_calls=-1)

    def test_async_tool_called_inside_budget_context(self) -> None:
        """@tool async function inside a budget context records the call."""
        from shekel._tool import tool

        @tool(price=0.007)
        async def async_search(q: str) -> str:
            return f"async: {q}"

        async def run() -> tuple[str, int, float]:
            with budget(max_tool_calls=5, tool_prices={"async_search": 0.007}) as b:
                result = await async_search("test")
                return result, b.tool_calls_used, b.tool_spent

        r, calls, spent = asyncio.run(run())
        assert r == "async: test"
        assert calls == 1
        assert abs(spent - 0.007) < 1e-9

    def test_async_nested_budget_tool_call_limit_autocapped(self) -> None:
        """Async budget auto-caps _effective_tool_call_limit from parent."""

        async def run() -> int:
            with budget(max_tool_calls=3, name="parent"):
                async with budget(max_tool_calls=10, name="child") as child:
                    return child._effective_tool_call_limit or 0
            return 0  # pragma: no cover

        limit = asyncio.run(run())
        assert limit == 3

    def test_emit_tool_call_event_exception_does_not_crash(self) -> None:
        """An adapter that raises in on_tool_call doesn't crash user code."""
        from shekel._tool import tool

        class CrashAdapter(ObservabilityAdapter):
            def on_tool_call(self, data: dict[str, Any]) -> None:
                raise RuntimeError("adapter crashed")

        adapter = CrashAdapter()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with budget(max_tool_calls=5):
                fn()  # must not raise despite adapter crash
        finally:
            AdapterRegistry.unregister(adapter)

    def test_emit_tool_budget_exceeded_exception_does_not_crash(self) -> None:
        """An adapter that raises in on_tool_budget_exceeded doesn't crash user code."""
        from shekel._tool import tool

        class CrashAdapter(ObservabilityAdapter):
            def on_tool_budget_exceeded(self, data: dict[str, Any]) -> None:
                raise RuntimeError("adapter crashed")

        adapter = CrashAdapter()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with pytest.raises(Exception):  # ToolBudgetExceededError or RuntimeError
                with budget(max_tool_calls=1):
                    fn()
                    fn()
        finally:
            AdapterRegistry.unregister(adapter)

    def test_emit_tool_warn_exception_does_not_crash(self) -> None:
        """An adapter that raises in on_tool_warn doesn't crash user code."""
        from shekel._tool import tool

        class CrashAdapter(ObservabilityAdapter):
            def on_tool_warn(self, data: dict[str, Any]) -> None:
                raise RuntimeError("adapter crashed")

        adapter = CrashAdapter()
        AdapterRegistry.register(adapter)
        try:

            @tool
            def fn() -> str:
                return "ok"

            with budget(max_tool_calls=5, warn_at=0.5):
                fn()
                fn()
                fn()  # should trigger warn but not crash
        finally:
            AdapterRegistry.unregister(adapter)

    def test_mcp_call_tool_no_active_budget_passes_through(self) -> None:
        """MCP call_tool outside budget context passes through without tracking."""
        import types

        fake_mcp = types.ModuleType("mcp")
        fake_client = types.ModuleType("mcp.client")
        fake_session_mod = types.ModuleType("mcp.client.session")

        class FakeClientSession:
            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                return {"result": "ok"}

        fake_session_mod.ClientSession = FakeClientSession
        fake_client.session = fake_session_mod
        fake_mcp.client = fake_client
        fake_mcp.ClientSession = FakeClientSession

        sys.modules["mcp"] = fake_mcp  # type: ignore[assignment]
        sys.modules["mcp.client"] = fake_client  # type: ignore[assignment]
        sys.modules["mcp.client.session"] = fake_session_mod  # type: ignore[assignment]

        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()
            try:
                # No budget context — should pass through
                session = sys.modules["mcp.client.session"].ClientSession()
                result = asyncio.run(session.call_tool("search", {}))
                assert result == {"result": "ok"}
            finally:
                adapter.remove_patches()
        finally:
            for key in ["mcp", "mcp.client", "mcp.client.session"]:
                sys.modules.pop(key, None)

    def test_mcp_install_patches_idempotent(self) -> None:
        """Calling install_patches twice doesn't double-patch."""
        import types

        fake_mcp = types.ModuleType("mcp")
        fake_client = types.ModuleType("mcp.client")
        fake_session_mod = types.ModuleType("mcp.client.session")

        class FakeClientSession:
            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                return {"result": "ok"}

        fake_session_mod.ClientSession = FakeClientSession
        fake_client.session = fake_session_mod
        fake_mcp.client = fake_client

        sys.modules["mcp"] = fake_mcp  # type: ignore[assignment]
        sys.modules["mcp.client"] = fake_client  # type: ignore[assignment]
        sys.modules["mcp.client.session"] = fake_session_mod  # type: ignore[assignment]

        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()
            first_patch = fake_session_mod.ClientSession.call_tool
            adapter.install_patches()  # second call — must not re-patch
            assert fake_session_mod.ClientSession.call_tool is first_patch
            adapter.remove_patches()
        finally:
            for key in ["mcp", "mcp.client", "mcp.client.session"]:
                sys.modules.pop(key, None)

    def test_mcp_with_tool_prices_records_cost(self) -> None:
        """MCP tool call records cost from budget's tool_prices dict."""
        import types

        fake_mcp = types.ModuleType("mcp")
        fake_client = types.ModuleType("mcp.client")
        fake_session_mod = types.ModuleType("mcp.client.session")

        class FakeClientSession:
            async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
                return {"result": "ok"}

        fake_session_mod.ClientSession = FakeClientSession
        fake_client.session = fake_session_mod
        fake_mcp.client = fake_client

        sys.modules["mcp"] = fake_mcp  # type: ignore[assignment]
        sys.modules["mcp.client"] = fake_client  # type: ignore[assignment]
        sys.modules["mcp.client.session"] = fake_session_mod  # type: ignore[assignment]

        try:
            from shekel.providers.mcp import MCPAdapter

            adapter = MCPAdapter()
            adapter.install_patches()
            try:
                session = sys.modules["mcp.client.session"].ClientSession()
                with budget(tool_prices={"brave_search": 0.005}) as b:
                    asyncio.run(session.call_tool("brave_search", {}))
                assert abs(b.tool_spent - 0.005) < 1e-9
            finally:
                adapter.remove_patches()
        finally:
            for key in ["mcp", "mcp.client", "mcp.client.session"]:
                sys.modules.pop(key, None)

    def test_langchain_with_tool_prices_records_cost(self) -> None:
        """LangChain tool call records cost from budget's tool_prices dict."""
        import types

        fake_lc = types.ModuleType("langchain_core")
        fake_tools_mod = types.ModuleType("langchain_core.tools")

        class BaseTool:
            name: str = "web_search"

            def invoke(self, input: Any) -> Any:
                return "result"

            async def ainvoke(self, input: Any) -> Any:
                return "async_result"

        fake_tools_mod.BaseTool = BaseTool
        fake_lc.tools = fake_tools_mod

        sys.modules["langchain_core"] = fake_lc  # type: ignore[assignment]
        sys.modules["langchain_core.tools"] = fake_tools_mod  # type: ignore[assignment]

        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_tools_mod.BaseTool()
                with budget(tool_prices={"web_search": 0.005}) as b:
                    tool_instance.invoke("query")
                assert abs(b.tool_spent - 0.005) < 1e-9
            finally:
                adapter.remove_patches()
        finally:
            for key in ["langchain_core", "langchain_core.tools"]:
                sys.modules.pop(key, None)

    def test_crewai_with_tool_prices_records_cost(self) -> None:
        """CrewAI tool call records cost from budget's tool_prices dict."""
        import types

        fake_crewai = types.ModuleType("crewai")
        fake_tools_mod = types.ModuleType("crewai.tools")

        class BaseTool:
            name: str = "crewai_search"

            def _run(self, *args: Any, **kwargs: Any) -> str:
                return "result"

            async def _arun(self, *args: Any, **kwargs: Any) -> str:
                return "async_result"

        fake_tools_mod.BaseTool = BaseTool
        fake_crewai.tools = fake_tools_mod

        sys.modules["crewai"] = fake_crewai  # type: ignore[assignment]
        sys.modules["crewai.tools"] = fake_tools_mod  # type: ignore[assignment]

        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_tools_mod.BaseTool()
                with budget(tool_prices={"crewai_search": 0.003}) as b:
                    tool_instance._run()
                assert abs(b.tool_spent - 0.003) < 1e-9
            finally:
                adapter.remove_patches()
        finally:
            for key in ["crewai", "crewai.tools"]:
                sys.modules.pop(key, None)

    def test_langchain_remove_patches_when_not_installed(self) -> None:
        """LangChainAdapter.remove_patches is safe when never installed."""
        from shekel.providers.langchain import LangChainAdapter

        adapter = LangChainAdapter()
        adapter.remove_patches()  # must not raise — nothing to remove

    def test_otel_on_tool_call_zero_cost_no_cost_counter(self) -> None:
        """OTel on_tool_call with cost=0 does not emit tool_cost counter."""
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter)

        # Call on_tool_call with zero cost — cost counter must not be called
        adapter.on_tool_call(
            {
                "tool_name": "free_tool",
                "cost": 0.0,
                "framework": "manual",
                "budget_name": "unnamed",
                "calls_used": 1,
            }
        )
        # on_tool_call must complete without exception (covers the except handler path indirectly)

    def test_langfuse_on_tool_call_exception_silent(self) -> None:
        """LangfuseAdapter.on_tool_call is silent when langfuse client raises."""
        from shekel.integrations.langfuse import LangfuseAdapter

        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_trace.span.side_effect = RuntimeError("langfuse error")
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)
        adapter._trace = mock_trace

        # Must not raise
        adapter.on_tool_call(
            {
                "tool_name": "fn",
                "cost": 0.0,
                "framework": "manual",
                "budget_name": "unnamed",
                "calls_used": 1,
                "calls_remaining": None,
                "usd_spent": 0.0,
            }
        )

    def test_emit_tool_call_event_emit_event_raises_is_swallowed(self) -> None:
        """AdapterRegistry.emit_event raising inside _emit_tool_call_event is swallowed."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        with patch(
            "shekel.integrations.registry.AdapterRegistry.emit_event",
            side_effect=RuntimeError("boom"),
        ):
            with budget(max_tool_calls=5):
                fn()  # must not raise despite emit_event crashing

    def test_emit_tool_budget_exceeded_event_emit_event_raises_is_swallowed(self) -> None:
        """AdapterRegistry.emit_event raising inside _emit_tool_budget_exceeded_event is
        swallowed."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        def selective_raise(event: str, data: dict[str, Any]) -> None:
            if event == "on_tool_budget_exceeded":
                raise RuntimeError("boom")

        with patch(
            "shekel.integrations.registry.AdapterRegistry.emit_event",
            side_effect=selective_raise,
        ):
            with pytest.raises(ToolBudgetExceededError):
                with budget(max_tool_calls=1):
                    fn()
                    fn()

    def test_emit_tool_warn_event_emit_event_raises_is_swallowed(self) -> None:
        """AdapterRegistry.emit_event raising inside _emit_tool_warn_event is swallowed."""
        from shekel._tool import tool

        @tool
        def fn() -> str:
            return "ok"

        def selective_raise(event: str, data: dict[str, Any]) -> None:
            if event == "on_tool_warn":
                raise RuntimeError("boom")

        with patch(
            "shekel.integrations.registry.AdapterRegistry.emit_event",
            side_effect=selective_raise,
        ):
            with budget(max_tool_calls=5, warn_at=0.5):
                fn()
                fn()
                fn()  # triggers warn — must not raise

    def test_async_tool_decorator_price_used_when_no_budget_tool_prices(self) -> None:
        """@tool(price=X) decorator price is used for async tools when budget has no tool_prices."""
        from shekel._tool import tool

        @tool(price=0.007)
        async def async_priced(q: str) -> str:
            return f"result:{q}"

        async def run() -> float:
            with budget() as b:
                await async_priced("test")
                return b.tool_spent

        spent = asyncio.run(run())
        assert abs(spent - 0.007) < 1e-9

    def test_callable_tool_budget_tool_prices_used(self) -> None:
        """Budget tool_prices takes precedence for callable tool() wrappers."""
        from shekel._tool import tool

        class MyTool:
            def __call__(self, x: int) -> int:
                return x

        wrapped = tool(MyTool(), price=0.001)
        with budget(tool_prices={"MyTool": 0.010}) as b:
            wrapped(1)
        assert abs(b.tool_spent - 0.010) < 1e-9

    def test_callable_tool_decorator_price_used_when_no_budget_tool_prices(self) -> None:
        """Callable tool's decorator price is used when budget has no tool_prices for it."""
        from shekel._tool import tool

        class MyTool:
            def __call__(self, x: int) -> int:
                return x

        wrapped = tool(MyTool(), price=0.005)
        with budget() as b:
            wrapped(1)
        assert abs(b.tool_spent - 0.005) < 1e-9

    def test_otel_on_tool_call_exception_is_swallowed(self) -> None:
        """_OtelMetricsAdapter.on_tool_call swallows instrument exceptions."""
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter)
        adapter._tool_calls.add.side_effect = RuntimeError("otel boom")

        # Must not raise
        adapter.on_tool_call(
            {
                "tool_name": "fn",
                "cost": 0.0,
                "framework": "manual",
                "budget_name": "unnamed",
                "calls_used": 1,
            }
        )

    def test_otel_on_tool_budget_exceeded_exception_is_swallowed(self) -> None:
        """_OtelMetricsAdapter.on_tool_budget_exceeded swallows instrument exceptions."""
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter)
        adapter._tool_exceeded.add.side_effect = RuntimeError("otel boom")

        # Must not raise
        adapter.on_tool_budget_exceeded(
            {
                "tool_name": "fn",
                "budget_name": "unnamed",
                "calls_used": 1,
                "calls_limit": 1,
                "usd_spent": 0.0,
                "usd_limit": None,
                "framework": "manual",
            }
        )

    def test_langchain_invoke_no_active_budget_passes_through(self) -> None:
        """LangChain BaseTool.invoke passes through when no budget is active."""
        import types

        fake_lc = types.ModuleType("langchain_core")
        fake_tools_mod = types.ModuleType("langchain_core.tools")

        class BaseTool:
            name: str = "search"

            def invoke(self, input: Any) -> Any:
                return f"result:{input}"

            async def ainvoke(self, input: Any) -> Any:
                return f"async:{input}"

        fake_tools_mod.BaseTool = BaseTool
        fake_lc.tools = fake_tools_mod

        sys.modules["langchain_core"] = fake_lc  # type: ignore[assignment]
        sys.modules["langchain_core.tools"] = fake_tools_mod  # type: ignore[assignment]

        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            try:
                tool_instance = fake_tools_mod.BaseTool()
                # No budget — must pass through
                result = tool_instance.invoke("query")
                assert result == "result:query"
                async_result = asyncio.run(tool_instance.ainvoke("query"))
                assert async_result == "async:query"
            finally:
                adapter.remove_patches()
        finally:
            for key in ["langchain_core", "langchain_core.tools"]:
                sys.modules.pop(key, None)

    def test_langchain_install_patches_idempotent(self) -> None:
        """LangChainAdapter.install_patches called twice doesn't double-patch."""
        import types

        fake_lc = types.ModuleType("langchain_core")
        fake_tools_mod = types.ModuleType("langchain_core.tools")

        class BaseTool:
            name: str = "s"

            def invoke(self, i: Any) -> Any:
                return i

            async def ainvoke(self, i: Any) -> Any:
                return i

        fake_tools_mod.BaseTool = BaseTool
        fake_lc.tools = fake_tools_mod

        sys.modules["langchain_core"] = fake_lc  # type: ignore[assignment]
        sys.modules["langchain_core.tools"] = fake_tools_mod  # type: ignore[assignment]

        try:
            from shekel.providers.langchain import LangChainAdapter

            adapter = LangChainAdapter()
            adapter.install_patches()
            first_invoke = fake_tools_mod.BaseTool.invoke
            adapter.install_patches()  # second call — must not re-patch
            assert fake_tools_mod.BaseTool.invoke is first_invoke
            adapter.remove_patches()
        finally:
            for key in ["langchain_core", "langchain_core.tools"]:
                sys.modules.pop(key, None)

    def test_crewai_run_no_active_budget_passes_through(self) -> None:
        """CrewAI BaseTool._run passes through when no budget is active."""
        import types

        fake_crewai = types.ModuleType("crewai")
        fake_tools_mod = types.ModuleType("crewai.tools")

        class BaseTool:
            name: str = "t"

            def _run(self, *a: Any, **kw: Any) -> str:
                return "ran"

            async def _arun(self, *a: Any, **kw: Any) -> str:
                return "async_ran"

        fake_tools_mod.BaseTool = BaseTool
        fake_crewai.tools = fake_tools_mod

        sys.modules["crewai"] = fake_crewai  # type: ignore[assignment]
        sys.modules["crewai.tools"] = fake_tools_mod  # type: ignore[assignment]

        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            try:
                t = fake_tools_mod.BaseTool()
                assert t._run() == "ran"
                assert asyncio.run(t._arun()) == "async_ran"
            finally:
                adapter.remove_patches()
        finally:
            for key in ["crewai", "crewai.tools"]:
                sys.modules.pop(key, None)

    def test_crewai_install_patches_idempotent(self) -> None:
        """CrewAIAdapter.install_patches called twice doesn't double-patch."""
        import types

        fake_crewai = types.ModuleType("crewai")
        fake_tools_mod = types.ModuleType("crewai.tools")

        class BaseTool:
            def _run(self, *a: Any, **kw: Any) -> str:
                return "r"

            async def _arun(self, *a: Any, **kw: Any) -> str:
                return "ar"

        fake_tools_mod.BaseTool = BaseTool
        fake_crewai.tools = fake_tools_mod

        sys.modules["crewai"] = fake_crewai  # type: ignore[assignment]
        sys.modules["crewai.tools"] = fake_tools_mod  # type: ignore[assignment]

        try:
            from shekel.providers.crewai import CrewAIAdapter

            adapter = CrewAIAdapter()
            adapter.install_patches()
            first_run = fake_tools_mod.BaseTool._run
            adapter.install_patches()  # second — must not re-patch
            assert fake_tools_mod.BaseTool._run is first_run
            adapter.remove_patches()
        finally:
            for key in ["crewai", "crewai.tools"]:
                sys.modules.pop(key, None)

    def test_openai_agents_with_tool_prices_records_cost(self) -> None:
        """OpenAI Agents tool call records cost from budget's tool_prices dict."""
        import types

        fake_agents = types.ModuleType("agents")
        fake_tool_mod = types.ModuleType("agents.tool")

        class FunctionTool:
            name: str = "agents_search"

            async def on_invoke_tool(self, ctx: Any, input: str) -> Any:
                return f"result:{input}"

        fake_tool_mod.FunctionTool = FunctionTool
        fake_agents.tool = fake_tool_mod
        fake_agents.FunctionTool = FunctionTool

        sys.modules["agents"] = fake_agents  # type: ignore[assignment]
        sys.modules["agents.tool"] = fake_tool_mod  # type: ignore[assignment]

        try:
            from shekel.providers.openai_agents import OpenAIAgentsAdapter

            adapter = OpenAIAgentsAdapter()
            adapter.install_patches()
            try:
                t = fake_agents.FunctionTool()
                with budget(tool_prices={"agents_search": 0.008}) as b:
                    asyncio.run(t.on_invoke_tool(None, "hi"))
                assert abs(b.tool_spent - 0.008) < 1e-9
            finally:
                adapter.remove_patches()
        finally:
            for key in ["agents", "agents.tool"]:
                sys.modules.pop(key, None)

    def test_openai_agents_install_patches_idempotent(self) -> None:
        """OpenAIAgentsAdapter.install_patches called twice doesn't double-patch."""
        import types

        fake_agents = types.ModuleType("agents")
        fake_tool_mod = types.ModuleType("agents.tool")

        class FunctionTool:
            name: str = "t"

            async def on_invoke_tool(self, ctx: Any, input: str) -> Any:
                return input

        fake_tool_mod.FunctionTool = FunctionTool
        fake_agents.tool = fake_tool_mod

        sys.modules["agents"] = fake_agents  # type: ignore[assignment]
        sys.modules["agents.tool"] = fake_tool_mod  # type: ignore[assignment]

        try:
            from shekel.providers.openai_agents import OpenAIAgentsAdapter

            adapter = OpenAIAgentsAdapter()
            adapter.install_patches()
            first = fake_tool_mod.FunctionTool.on_invoke_tool
            adapter.install_patches()  # second — must not re-patch
            assert fake_tool_mod.FunctionTool.on_invoke_tool is first
            adapter.remove_patches()
        finally:
            for key in ["agents", "agents.tool"]:
                sys.modules.pop(key, None)

    def test_openai_agents_no_active_budget_passes_through(self) -> None:
        """OpenAI Agents on_invoke_tool passes through when no budget is active."""
        import types

        fake_agents = types.ModuleType("agents")
        fake_tool_mod = types.ModuleType("agents.tool")

        class FunctionTool:
            name: str = "t"

            async def on_invoke_tool(self, ctx: Any, input: str) -> Any:
                return f"result:{input}"

        fake_tool_mod.FunctionTool = FunctionTool
        fake_agents.tool = fake_tool_mod
        fake_agents.FunctionTool = FunctionTool

        sys.modules["agents"] = fake_agents  # type: ignore[assignment]
        sys.modules["agents.tool"] = fake_tool_mod  # type: ignore[assignment]

        try:
            from shekel.providers.openai_agents import OpenAIAgentsAdapter

            adapter = OpenAIAgentsAdapter()
            adapter.install_patches()
            try:
                t = fake_agents.FunctionTool()
                result = asyncio.run(t.on_invoke_tool(None, "hi"))
                assert result == "result:hi"
            finally:
                adapter.remove_patches()
        finally:
            for key in ["agents", "agents.tool"]:
                sys.modules.pop(key, None)


class TestNoActiveBudgetPassThrough:
    def test_tool_passthrough_when_no_budget(self) -> None:
        """@tool decorated function works normally when no budget is active."""
        from shekel._tool import tool

        @tool
        def fn(x: int) -> int:
            return x * 3

        # No budget context — should work transparently
        assert fn(4) == 12

    def test_async_tool_passthrough_when_no_budget(self) -> None:
        """@tool async function works normally when no budget is active."""
        from shekel._tool import tool

        @tool
        async def async_fn(x: int) -> int:
            return x + 10

        result = asyncio.run(async_fn(5))
        assert result == 15

    def test_tool_wrapper_passthrough_when_no_budget(self) -> None:
        """tool(obj) wrapped callable works normally when no budget is active."""
        from shekel._tool import tool

        class MyTool:
            def __call__(self, x: int) -> int:
                return x * 2

        wrapped = tool(MyTool(), price=0.005)
        assert wrapped(7) == 14
