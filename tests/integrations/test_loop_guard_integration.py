"""Integration tests for loop guard end-to-end scenarios.

Mock tests (TestLoopGuardMockIntegration) run without any API keys and verify
that shekel's loop guard correctly intercepts real tool dispatch pipelines.

Real-API tests (TestLoopGuardLiveIntegration) require OPENAI_API_KEY and are
skipped without it.
"""

from __future__ import annotations

import os

import pytest

from shekel import budget
from shekel._budget import Budget
from shekel._tool import tool
from shekel.exceptions import AgentLoopError, BudgetExceededError

# ---------------------------------------------------------------------------
# Mock integration: @tool decorator
# ---------------------------------------------------------------------------


class TestLoopGuardMockIntegration:
    """End-to-end loop guard via @tool-decorated functions — no API keys needed."""

    def test_tool_loop_fires_after_max_calls(self) -> None:
        """Loop guard fires after max_calls identical tool dispatches."""
        call_count = 0

        @tool
        def search(query: str) -> str:
            nonlocal call_count
            call_count += 1
            return "same result"

        with budget(max_usd=10.00, loop_guard=True, loop_guard_max_calls=3) as b:
            b._record_spend(0.01, "gpt-4o", {"input": 10, "output": 5})
            for _ in range(3):
                search(query="what is AI")

            with pytest.raises(AgentLoopError) as exc_info:
                search(query="what is AI")

        err = exc_info.value
        assert err.tool_name == "search"
        assert err.repeat_count == 3
        assert call_count == 3  # tool body never ran on the 4th call

    def test_tool_loop_is_subclass_of_budget_exceeded_error(self) -> None:
        """AgentLoopError is caught by except BudgetExceededError."""

        @tool
        def ping() -> str:
            return "pong"

        with budget(loop_guard=True, loop_guard_max_calls=2):
            ping()
            ping()
            with pytest.raises(BudgetExceededError):
                ping()

    def test_different_tools_tracked_independently(self) -> None:
        """Loop guard fires on tool A only; tool B can still run."""

        @tool
        def tool_a() -> str:
            return "a"

        @tool
        def tool_b() -> str:
            return "b"

        with budget(loop_guard=True, loop_guard_max_calls=2):
            tool_a()
            tool_a()
            # tool_b has 0 calls — still allowed
            tool_b()
            tool_b()
            # tool_a now at limit
            with pytest.raises(AgentLoopError) as exc_info:
                tool_a()
            assert exc_info.value.tool_name == "tool_a"

    def test_loop_guard_does_not_fire_before_limit(self) -> None:
        """Exactly max_calls dispatches are allowed; only the next one fires."""

        @tool
        def counter() -> str:
            return "ok"

        with budget(loop_guard=True, loop_guard_max_calls=5):
            for _ in range(5):
                counter()  # all 5 must succeed

    def test_warn_only_does_not_raise(self) -> None:
        """warn_only=True emits warnings instead of raising AgentLoopError."""

        @tool
        def repeating() -> str:
            return "result"

        with pytest.warns(UserWarning, match="Loop guard"):
            with budget(loop_guard=True, loop_guard_max_calls=2, warn_only=True):
                repeating()
                repeating()
                repeating()  # would raise without warn_only

    def test_loop_guard_state_clears_after_window(self) -> None:
        """After the window expires, call count resets and tool runs freely."""
        import time

        @tool
        def quick_tool() -> str:
            return "fast"

        # 1-second window, max 2 calls
        with budget(loop_guard=True, loop_guard_max_calls=2, loop_guard_window_seconds=1.0):
            quick_tool()
            quick_tool()
            # Would fire now — but let the window expire
            time.sleep(1.1)
            # After expiry, count resets
            quick_tool()  # should not raise

    def test_loop_guard_counts_property_reflects_calls(self) -> None:
        """b.loop_guard_counts returns accurate per-tool call counts."""

        @tool
        def alpha() -> str:
            return "a"

        @tool
        def beta() -> str:
            return "b"

        with budget(loop_guard=True, loop_guard_max_calls=10) as b:
            alpha()
            alpha()
            alpha()
            beta()
            counts = b.loop_guard_counts

        assert counts.get("alpha") == 3
        assert counts.get("beta") == 1

    def test_loop_guard_and_max_tool_calls_independent(self) -> None:
        """Loop guard fires independently of max_tool_calls."""

        @tool
        def bounded() -> str:
            return "x"

        # max_tool_calls=10 (generous), loop_guard fires at 3
        with budget(max_tool_calls=10, loop_guard=True, loop_guard_max_calls=3):
            bounded()
            bounded()
            bounded()
            with pytest.raises(AgentLoopError):
                bounded()

    def test_session_budget_loop_guard_persists_across_with_blocks(self) -> None:
        """Loop guard window accumulates across multiple uses of the same budget."""

        @tool
        def session_tool() -> str:
            return "session"

        b = Budget(loop_guard=True, loop_guard_max_calls=3)
        with b:
            session_tool()
            session_tool()

        with b:
            session_tool()
            with pytest.raises(AgentLoopError):
                session_tool()  # 4th call total, fires

    def test_reset_clears_loop_guard_windows(self) -> None:
        """b.reset() clears loop guard state."""

        @tool
        def resettable() -> str:
            return "reset"

        b = Budget(loop_guard=True, loop_guard_max_calls=2)
        with b:
            resettable()
            resettable()

        b.reset()  # clears windows

        with b:
            resettable()  # should not raise — window is cleared
            resettable()


# ---------------------------------------------------------------------------
# Real API: requires OPENAI_API_KEY
# ---------------------------------------------------------------------------


class TestLoopGuardLiveIntegration:
    """Loop guard with a real OpenAI call — skipped without API key."""

    @pytest.fixture(autouse=True)
    def require_openai_key(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

    def test_real_openai_call_completes_under_loop_guard(self) -> None:
        """A single real OpenAI call completes normally inside loop_guard=True budget."""
        import openai

        client = openai.OpenAI()

        @tool
        def ask_llm(prompt: str) -> str:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            return resp.choices[0].message.content or ""

        with budget(max_usd=0.10, loop_guard=True, loop_guard_max_calls=3) as b:
            result = ask_llm(prompt="Say hi")
            assert isinstance(result, str)
            assert b.spent > 0
            counts = b.loop_guard_counts
            assert counts.get("ask_llm") == 1
