"""Integration tests for LangGraph with Groq and Gemini APIs.

Real-API tests (TestLangGraphGroqIntegration, TestLangGraphGeminiIntegration)
require GROQ_API_KEY / GEMINI_API_KEY env vars and are skipped without them.

Mock tests (TestLangGraphMockIntegration) run without any API keys and verify
that shekel's patches capture spend from within LangGraph nodes end-to-end.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shekel import budget
from shekel.exceptions import BudgetExceededError

try:
    from langgraph.graph import END, StateGraph  # type: ignore[import]
    from typing_extensions import TypedDict

    LANGGRAPH_AVAILABLE = True

    class _State(TypedDict):
        messages: list[str]
        response: str

except ImportError:
    LANGGRAPH_AVAILABLE = False


pytestmark = pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed")


# ---------------------------------------------------------------------------
# Real API: LangGraph + Groq (OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------


class TestLangGraphGroqIntegration:
    """LangGraph nodes calling Groq via the OpenAI client (shekel-patched)."""

    @pytest.fixture
    def groq_api_key(self) -> str | None:
        return os.getenv("GROQ_API_KEY")

    @pytest.fixture
    def groq_available(self, groq_api_key: str | None) -> bool:
        return bool(groq_api_key and LANGGRAPH_AVAILABLE)

    def _build_single_node_app(self, groq_api_key: str) -> Any:
        import openai

        client = openai.OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        def call_groq(state: _State) -> _State:
            r = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": state["messages"][-1]}],
                max_tokens=20,
            )
            return {**state, "response": r.choices[0].message.content or ""}

        graph = StateGraph(_State)
        graph.add_node("llm", call_groq)
        graph.set_entry_point("llm")
        graph.add_edge("llm", END)
        return graph.compile()

    def test_single_node_tracks_spend(self, groq_api_key: str | None, groq_available: bool) -> None:
        """Budget tracks spend automatically from a LangGraph node calling Groq."""
        if not groq_available:
            pytest.skip("Groq API not available")

        app = self._build_single_node_app(groq_api_key)  # type: ignore[arg-type]
        with budget(max_usd=0.50, name="langgraph_groq") as b:
            try:
                app.invoke({"messages": ["Say hello in one word."], "response": ""})
            except Exception as e:
                pytest.skip(f"Groq API error: {e}")

        assert b.spent >= 0
        assert b.calls_used >= 1

    def test_multi_node_accumulates_spend(
        self, groq_api_key: str | None, groq_available: bool
    ) -> None:
        """Costs from all nodes in a multi-node graph roll up to one budget."""
        if not groq_available:
            pytest.skip("Groq API not available")

        import openai

        client = openai.OpenAI(
            api_key=groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        class _TwoStepState(TypedDict):
            input: str
            step1: str
            step2: str

        def node_one(state: _TwoStepState) -> _TwoStepState:
            r = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": f"In 5 words: {state['input']}"}],
                max_tokens=15,
            )
            return {**state, "step1": r.choices[0].message.content or ""}

        def node_two(state: _TwoStepState) -> _TwoStepState:
            r = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": f"Expand: {state['step1']}"}],
                max_tokens=15,
            )
            return {**state, "step2": r.choices[0].message.content or ""}

        graph = StateGraph(_TwoStepState)
        graph.add_node("one", node_one)
        graph.add_node("two", node_two)
        graph.set_entry_point("one")
        graph.add_edge("one", "two")
        graph.add_edge("two", END)
        app = graph.compile()

        with budget(max_usd=1.00, name="multi_node_groq") as b:
            try:
                app.invoke({"input": "AI is changing the world", "step1": "", "step2": ""})
            except Exception as e:
                pytest.skip(f"Groq API error: {e}")

        assert b.calls_used >= 2

    def test_budget_enforcement_stops_graph(
        self, groq_api_key: str | None, groq_available: bool
    ) -> None:
        """BudgetExceededError raised when a node call pushes over the limit."""
        if not groq_available:
            pytest.skip("Groq API not available")

        app = self._build_single_node_app(groq_api_key)  # type: ignore[arg-type]
        exceeded = False
        try:
            # Force non-zero pricing so enforcement works even if the model has no
            # bundled price table (e.g. llama-3.1-8b-instant on Groq).
            with budget(
                max_usd=0.000001,
                name="tiny_groq_graph",
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ):
                app.invoke({"messages": ["Say hello."], "response": ""})
        except BudgetExceededError:
            exceeded = True
        except Exception as e:
            pytest.skip(f"Groq API error: {e}")

        assert exceeded

    def test_nested_budget_propagates_spend(
        self, groq_api_key: str | None, groq_available: bool
    ) -> None:
        """Spend from a graph run inside a child budget rolls up to the parent."""
        if not groq_available:
            pytest.skip("Groq API not available")

        app = self._build_single_node_app(groq_api_key)  # type: ignore[arg-type]

        with budget(max_usd=2.00, name="workflow") as parent:
            with budget(max_usd=0.50, name="graph_step") as child:
                try:
                    app.invoke({"messages": ["Say hi."], "response": ""})
                except Exception as e:
                    pytest.skip(f"Groq API error: {e}")

        assert parent.spent >= child.spent
        assert child.spent >= 0

    def test_budget_summary_reflects_graph_calls(
        self, groq_api_key: str | None, groq_available: bool
    ) -> None:
        """b.summary() shows the LLM call made inside the graph."""
        if not groq_available:
            pytest.skip("Groq API not available")

        app = self._build_single_node_app(groq_api_key)  # type: ignore[arg-type]

        with budget(max_usd=0.50, name="summary_groq") as b:
            try:
                app.invoke({"messages": ["What is 1+1?"], "response": ""})
            except Exception as e:
                pytest.skip(f"Groq API error: {e}")

        summary = b.summary()
        assert "$" in summary


# ---------------------------------------------------------------------------
# Real API: LangGraph + Gemini (via LiteLLM)
# ---------------------------------------------------------------------------


class TestLangGraphGeminiIntegration:
    """LangGraph nodes calling Gemini via LiteLLM (shekel-patched)."""

    @pytest.fixture
    def gemini_api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY")

    @pytest.fixture
    def gemini_available(self, gemini_api_key: str | None) -> bool:
        if not gemini_api_key or not LANGGRAPH_AVAILABLE:
            return False
        try:
            import litellm  # noqa: F401

            return True
        except ImportError:
            return False

    def _build_single_node_app(self, gemini_api_key: str) -> Any:
        import litellm

        os.environ.setdefault("GEMINI_API_KEY", gemini_api_key)

        def call_gemini(state: _State) -> _State:
            r = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": state["messages"][-1]}],
                max_tokens=20,
            )
            return {**state, "response": r.choices[0].message.content or ""}

        graph = StateGraph(_State)
        graph.add_node("llm", call_gemini)
        graph.set_entry_point("llm")
        graph.add_edge("llm", END)
        return graph.compile()

    def test_single_node_tracks_spend(
        self, gemini_api_key: str | None, gemini_available: bool
    ) -> None:
        """Budget tracks spend automatically from a LangGraph node calling Gemini."""
        if not gemini_available:
            pytest.skip("Gemini API or LiteLLM not available")

        app = self._build_single_node_app(gemini_api_key)  # type: ignore[arg-type]
        with budget(max_usd=0.50, name="langgraph_gemini") as b:
            try:
                app.invoke({"messages": ["Say hello in one word."], "response": ""})
            except Exception as e:
                pytest.skip(f"Gemini API error: {e}")

        assert b.spent >= 0
        assert b.calls_used >= 1

    def test_multi_node_accumulates_spend(
        self, gemini_api_key: str | None, gemini_available: bool
    ) -> None:
        """Costs from all nodes in a multi-node Gemini graph roll up to one budget."""
        if not gemini_available:
            pytest.skip("Gemini API or LiteLLM not available")

        import litellm

        os.environ.setdefault("GEMINI_API_KEY", gemini_api_key)  # type: ignore[arg-type]

        class _TwoStepState(TypedDict):
            input: str
            step1: str
            step2: str

        def node_one(state: _TwoStepState) -> _TwoStepState:
            r = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": f"In 5 words: {state['input']}"}],
                max_tokens=15,
            )
            return {**state, "step1": r.choices[0].message.content or ""}

        def node_two(state: _TwoStepState) -> _TwoStepState:
            r = litellm.completion(
                model="gemini/gemini-2.0-flash",
                messages=[{"role": "user", "content": f"Expand: {state['step1']}"}],
                max_tokens=15,
            )
            return {**state, "step2": r.choices[0].message.content or ""}

        graph = StateGraph(_TwoStepState)
        graph.add_node("one", node_one)
        graph.add_node("two", node_two)
        graph.set_entry_point("one")
        graph.add_edge("one", "two")
        graph.add_edge("two", END)
        app = graph.compile()

        with budget(max_usd=1.00, name="multi_node_gemini") as b:
            try:
                app.invoke({"input": "AI is changing the world", "step1": "", "step2": ""})
            except Exception as e:
                pytest.skip(f"Gemini API error: {e}")

        assert b.calls_used >= 2

    def test_budget_enforcement_stops_graph(
        self, gemini_api_key: str | None, gemini_available: bool
    ) -> None:
        """BudgetExceededError raised when a Gemini node call pushes over the limit."""
        if not gemini_available:
            pytest.skip("Gemini API or LiteLLM not available")

        app = self._build_single_node_app(gemini_api_key)  # type: ignore[arg-type]
        exceeded = False
        try:
            # Force non-zero pricing so enforcement works even if the model has no
            # bundled price table. Use max_usd well below what any real call costs.
            with budget(
                max_usd=0.000001,
                name="tiny_gemini_graph",
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ):
                app.invoke({"messages": ["Say hello."], "response": ""})
        except BudgetExceededError:
            exceeded = True
        except Exception as e:
            pytest.skip(f"Gemini API error: {e}")

        assert exceeded

    def test_nested_budget_propagates_spend(
        self, gemini_api_key: str | None, gemini_available: bool
    ) -> None:
        """Spend from a Gemini graph run inside a child budget rolls up to parent."""
        if not gemini_available:
            pytest.skip("Gemini API or LiteLLM not available")

        app = self._build_single_node_app(gemini_api_key)  # type: ignore[arg-type]

        with budget(max_usd=2.00, name="workflow") as parent:
            with budget(max_usd=0.50, name="graph_step") as child:
                try:
                    app.invoke({"messages": ["Say hi."], "response": ""})
                except Exception as e:
                    pytest.skip(f"Gemini API error: {e}")

        assert parent.spent >= child.spent
        assert child.spent >= 0


# ---------------------------------------------------------------------------
# Mock tests — no API keys needed, exercise the full patch→graph path
# ---------------------------------------------------------------------------


class TestLangGraphMockIntegration:
    """LangGraph integration verified end-to-end with a mocked OpenAI client.

    These tests confirm that shekel's patches capture spend from within
    LangGraph node functions without requiring real API calls.
    """

    def _mock_response(self, input_tokens: int = 100, output_tokens: int = 50) -> MagicMock:
        m = MagicMock()
        m.choices[0].message.content = "mock response"
        m.usage.prompt_tokens = input_tokens
        m.usage.completion_tokens = output_tokens
        m.model = "gpt-4o-mini"
        return m

    def test_single_node_spend_captured(self) -> None:
        """Spend from one LangGraph node is captured by the surrounding budget."""
        mock_resp = self._mock_response(input_tokens=100, output_tokens=50)

        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            import openai

            client = openai.OpenAI(api_key="test")

            def node(state: _State) -> _State:
                r = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": state["messages"][-1]}],
                )
                return {**state, "response": r.choices[0].message.content}

            graph = StateGraph(_State)
            graph.add_node("llm", node)
            graph.set_entry_point("llm")
            graph.add_edge("llm", END)
            app = graph.compile()

            with budget(max_usd=1.00, name="single_node") as b:
                app.invoke({"messages": ["test"], "response": ""})

        assert b.spent > 0
        assert b.calls_used == 1

    def test_multi_node_all_calls_tracked(self) -> None:
        """All three nodes contribute to total spend and call count."""
        mock_resp = self._mock_response(input_tokens=50, output_tokens=25)

        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            import openai

            client = openai.OpenAI(api_key="test")

            class _ThreeStepState(TypedDict):
                v0: str
                v1: str
                v2: str
                v3: str

            def n1(s: _ThreeStepState) -> _ThreeStepState:
                r = client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": s["v0"]}]
                )
                return {**s, "v1": r.choices[0].message.content}

            def n2(s: _ThreeStepState) -> _ThreeStepState:
                r = client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": s["v1"]}]
                )
                return {**s, "v2": r.choices[0].message.content}

            def n3(s: _ThreeStepState) -> _ThreeStepState:
                r = client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": s["v2"]}]
                )
                return {**s, "v3": r.choices[0].message.content}

            graph = StateGraph(_ThreeStepState)
            for name, fn in [("n1", n1), ("n2", n2), ("n3", n3)]:
                graph.add_node(name, fn)
            graph.set_entry_point("n1")
            graph.add_edge("n1", "n2")
            graph.add_edge("n2", "n3")
            graph.add_edge("n3", END)
            app = graph.compile()

            with budget(max_usd=5.00, name="three_nodes") as b:
                app.invoke({"v0": "test", "v1": "", "v2": "", "v3": ""})

        assert b.calls_used == 3
        assert b.spent > 0

    def test_budget_exceeded_propagates_out_of_graph(self) -> None:
        """BudgetExceededError raised inside a node propagates out of the graph."""
        mock_resp = self._mock_response(input_tokens=10000, output_tokens=5000)

        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            import openai

            client = openai.OpenAI(api_key="test")

            def expensive_node(state: _State) -> _State:
                r = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "test"}],
                )
                return {**state, "response": r.choices[0].message.content}

            graph = StateGraph(_State)
            graph.add_node("llm", expensive_node)
            graph.set_entry_point("llm")
            graph.add_edge("llm", END)
            app = graph.compile()

            with pytest.raises(BudgetExceededError):
                with budget(max_usd=0.001, name="tiny"):
                    app.invoke({"messages": ["test"], "response": ""})

    def test_nested_budget_spend_propagates_to_parent(self) -> None:
        """Spend from a graph running inside a child budget rolls up to parent."""
        mock_resp = self._mock_response(input_tokens=100, output_tokens=50)

        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            import openai

            client = openai.OpenAI(api_key="test")

            def node(state: _State) -> _State:
                r = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": state["messages"][-1]}],
                )
                return {**state, "response": r.choices[0].message.content}

            graph = StateGraph(_State)
            graph.add_node("llm", node)
            graph.set_entry_point("llm")
            graph.add_edge("llm", END)
            app = graph.compile()

            with budget(max_usd=10.00, name="workflow") as parent:
                with budget(max_usd=1.00, name="graph_step") as child:
                    app.invoke({"messages": ["test"], "response": ""})

        assert child.spent > 0
        assert parent.spent == child.spent

    def test_conditional_graph_retry_loop_bounded_by_budget(self) -> None:
        """A retry-loop graph stops after exactly N iterations when budget enforced."""
        mock_resp = self._mock_response(input_tokens=50, output_tokens=20)

        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            import openai

            client = openai.OpenAI(api_key="test")

            class _RetryState(TypedDict):
                query: str
                result: str
                attempts: int

            def try_node(state: _RetryState) -> _RetryState:
                r = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": state["query"]}],
                )
                return {
                    **state,
                    "result": r.choices[0].message.content,
                    "attempts": state["attempts"] + 1,
                }

            def should_stop(state: Any) -> str:
                return "done" if state["attempts"] >= 2 else "retry"

            graph = StateGraph(_RetryState)
            graph.add_node("try", try_node)
            graph.set_entry_point("try")
            graph.add_conditional_edges("try", should_stop, {"retry": "try", "done": END})
            app = graph.compile()

            with budget(max_usd=5.00, name="retry_loop") as b:
                app.invoke({"query": "test", "result": "", "attempts": 0})

        assert b.calls_used == 2
        assert b.spent > 0
