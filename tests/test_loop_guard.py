"""Tests for the Loop Guard feature (shekel v1.1.0).

Domain: loop guard — per-tool call frequency enforcement.

TDD: these tests were written first (red), then implementation made them green.
"""

from __future__ import annotations

import time
import warnings
from collections import deque
from unittest.mock import patch

import pytest

from shekel._budget import Budget
from shekel._tool import tool
from shekel.exceptions import AgentLoopError, BudgetExceededError

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def make_budget(**kwargs: object) -> Budget:
    """Return a Budget with loop_guard=True by default for loop-guard tests."""
    kwargs.setdefault("loop_guard", True)
    return Budget(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Exception class: AgentLoopError
# ---------------------------------------------------------------------------


class TestAgentLoopError:
    def test_is_subclass_of_budget_exceeded_error(self) -> None:
        assert issubclass(AgentLoopError, BudgetExceededError)

    def test_caught_by_budget_exceeded_error(self) -> None:
        err = AgentLoopError(tool_name="search", repeat_count=5, window_seconds=60.0, spent=0.5)
        with pytest.raises(BudgetExceededError):
            raise err

    def test_fields_stored_correctly(self) -> None:
        err = AgentLoopError(tool_name="my_tool", repeat_count=7, window_seconds=30.0, spent=1.23)
        assert err.tool_name == "my_tool"
        assert err.repeat_count == 7
        assert err.window_seconds == 30.0
        assert err.spent == 1.23

    def test_str_includes_tool_name(self) -> None:
        err = AgentLoopError(tool_name="web_search", repeat_count=5, window_seconds=60.0, spent=0.0)
        assert "web_search" in str(err)

    def test_str_includes_repeat_count(self) -> None:
        err = AgentLoopError(tool_name="search", repeat_count=8, window_seconds=60.0, spent=0.0)
        assert "8" in str(err)

    def test_str_shows_all_time_when_window_zero(self) -> None:
        err = AgentLoopError(tool_name="tool_x", repeat_count=3, window_seconds=0, spent=0.0)
        assert "all-time" in str(err)

    def test_str_shows_window_seconds_when_nonzero(self) -> None:
        err = AgentLoopError(tool_name="tool_x", repeat_count=3, window_seconds=120.0, spent=0.0)
        assert "120" in str(err)
        assert "all-time" not in str(err)

    def test_str_shows_spent(self) -> None:
        err = AgentLoopError(tool_name="search", repeat_count=5, window_seconds=60.0, spent=2.5678)
        assert "2.5678" in str(err)

    def test_zero_spent(self) -> None:
        err = AgentLoopError(tool_name="tool", repeat_count=1, window_seconds=60.0, spent=0.0)
        assert err.spent == 0.0

    def test_exception_message_from_init(self) -> None:
        """AgentLoopError args[0] should match __str__ output."""
        err = AgentLoopError(tool_name="my_tool", repeat_count=3, window_seconds=60.0, spent=0.1)
        assert str(err) == err.args[0]


# ---------------------------------------------------------------------------
# 2. Budget constructor — loop guard parameters
# ---------------------------------------------------------------------------


class TestBudgetConstructorLoopGuard:
    def test_loop_guard_defaults_to_false(self) -> None:
        b = Budget()
        assert b.loop_guard is False

    def test_loop_guard_true_stored(self) -> None:
        b = Budget(loop_guard=True)
        assert b.loop_guard is True

    def test_loop_guard_max_calls_default(self) -> None:
        b = Budget(loop_guard=True)
        assert b.loop_guard_max_calls == 5

    def test_loop_guard_window_seconds_default(self) -> None:
        b = Budget(loop_guard=True)
        assert b.loop_guard_window_seconds == 60.0

    def test_custom_max_calls(self) -> None:
        b = Budget(loop_guard=True, loop_guard_max_calls=10)
        assert b.loop_guard_max_calls == 10

    def test_custom_window_seconds(self) -> None:
        b = Budget(loop_guard=True, loop_guard_window_seconds=120.0)
        assert b.loop_guard_window_seconds == 120.0

    def test_loop_guard_windows_initialized_empty(self) -> None:
        b = Budget(loop_guard=True)
        assert b._loop_guard_windows == {}

    def test_loop_guard_windows_is_dict(self) -> None:
        b = Budget(loop_guard=True)
        assert isinstance(b._loop_guard_windows, dict)

    def test_loop_guard_false_still_has_windows_attr(self) -> None:
        """Even when loop_guard=False, the dict attribute should exist."""
        b = Budget(loop_guard=False)
        assert hasattr(b, "_loop_guard_windows")
        assert isinstance(b._loop_guard_windows, dict)


# ---------------------------------------------------------------------------
# 3. _check_loop_guard — basic gate
# ---------------------------------------------------------------------------


class TestCheckLoopGuardBasic:
    def test_does_nothing_when_loop_guard_false(self) -> None:
        b = Budget(loop_guard=False)
        # Should not raise anything
        for _ in range(20):
            b._check_loop_guard("search", "manual")

    def test_passes_for_first_n_calls(self) -> None:
        b = make_budget(loop_guard_max_calls=3)
        # Fill the window manually so _check sees them
        for _ in range(3):
            b._loop_guard_windows.setdefault("search", deque(maxlen=4)).append(time.monotonic())
        # Only 3 in window — should still pass (limit is 3, need >= 3 to fire on 4th)
        # Actually per spec: fires when len(window) >= max_calls at check time
        # After 3 appends len == 3 >= 3 → fires. Let's verify 2 appends passes.

    def test_passes_when_under_limit(self) -> None:
        b = make_budget(loop_guard_max_calls=5)
        # Manually add 4 timestamps to the window
        w: deque[float] = deque(maxlen=6)
        for _ in range(4):
            w.append(time.monotonic())
        b._loop_guard_windows["search"] = w
        # 4 < 5, should not raise
        b._check_loop_guard("search", "manual")

    def test_raises_on_call_exceeding_limit(self) -> None:
        b = make_budget(loop_guard_max_calls=3)
        # Inject 3 recent timestamps
        w: deque[float] = deque(maxlen=4)
        now = time.monotonic()
        for _ in range(3):
            w.append(now)
        b._loop_guard_windows["search"] = w
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("search", "manual")

    def test_error_has_correct_tool_name(self) -> None:
        b = make_budget(loop_guard_max_calls=2)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["my_search"] = w
        with pytest.raises(AgentLoopError) as exc_info:
            b._check_loop_guard("my_search", "manual")
        assert exc_info.value.tool_name == "my_search"

    def test_error_has_correct_repeat_count(self) -> None:
        b = make_budget(loop_guard_max_calls=3)
        w: deque[float] = deque(maxlen=4)
        now = time.monotonic()
        for _ in range(3):
            w.append(now)
        b._loop_guard_windows["tool_x"] = w
        with pytest.raises(AgentLoopError) as exc_info:
            b._check_loop_guard("tool_x", "manual")
        assert exc_info.value.repeat_count == 3

    def test_error_has_correct_window_seconds(self) -> None:
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=45.0)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["t"] = w
        with pytest.raises(AgentLoopError) as exc_info:
            b._check_loop_guard("t", "manual")
        assert exc_info.value.window_seconds == 45.0

    def test_error_has_correct_spent(self) -> None:
        b = make_budget(loop_guard_max_calls=2)
        b._spent = 3.14
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["t"] = w
        with pytest.raises(AgentLoopError) as exc_info:
            b._check_loop_guard("t", "manual")
        assert exc_info.value.spent == pytest.approx(3.14)

    def test_independent_per_tool(self) -> None:
        """Tool A at limit does not affect tool B."""
        b = make_budget(loop_guard_max_calls=2)
        # Fill tool_a to limit
        w_a: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w_a.append(now)
        w_a.append(now)
        b._loop_guard_windows["tool_a"] = w_a
        # tool_a should raise
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("tool_a", "manual")
        # tool_b (no window yet) should pass
        b._check_loop_guard("tool_b", "manual")

    def test_warn_only_emits_warning_not_raise(self) -> None:
        b = make_budget(loop_guard_max_calls=2, warn_only=True)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["search"] = w
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            b._check_loop_guard("search", "manual")
        assert len(caught) == 1

    def test_warn_only_warning_message_includes_tool_name(self) -> None:
        b = make_budget(loop_guard_max_calls=2, warn_only=True)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["fancy_tool"] = w
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            b._check_loop_guard("fancy_tool", "manual")
        assert "fancy_tool" in str(caught[0].message)

    def test_warn_only_warning_message_includes_count(self) -> None:
        b = make_budget(loop_guard_max_calls=2, warn_only=True)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["t"] = w
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            b._check_loop_guard("t", "manual")
        assert "2" in str(caught[0].message)

    def test_warn_only_returns_does_not_raise(self) -> None:
        """After emitting warning, _check_loop_guard returns cleanly."""
        b = make_budget(loop_guard_max_calls=1, warn_only=True)
        w: deque[float] = deque(maxlen=2)
        w.append(time.monotonic())
        b._loop_guard_windows["t"] = w
        # Should not raise; return value is None
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = b._check_loop_guard("t", "manual")
        assert result is None


# ---------------------------------------------------------------------------
# 4. Rolling window behaviour
# ---------------------------------------------------------------------------


class TestRollingWindow:
    def test_old_timestamps_evicted(self) -> None:
        """After window_seconds elapses, old timestamps are evicted and guard does not fire."""
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=0.05)
        # Inject 2 very old timestamps (well outside window)
        old = time.monotonic() - 10.0
        w: deque[float] = deque(maxlen=3)
        w.append(old)
        w.append(old)
        b._loop_guard_windows["search"] = w
        # After eviction of both old timestamps, count == 0 < 2 — should NOT raise
        b._check_loop_guard("search", "manual")

    def test_after_eviction_count_resets(self) -> None:
        """Eviction resets effective count, allowing tool to be called again."""
        b = make_budget(loop_guard_max_calls=3, loop_guard_window_seconds=1.0)
        old = time.monotonic() - 5.0
        w: deque[float] = deque(maxlen=4)
        for _ in range(3):
            w.append(old)  # all expired
        b._loop_guard_windows["t"] = w
        # All expired → evicted → count 0 → no raise
        b._check_loop_guard("t", "manual")

    def test_window_seconds_zero_means_all_time(self) -> None:
        """window_seconds=0 disables eviction; all timestamps count."""
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=0)
        very_old = time.monotonic() - 1_000_000.0
        w: deque[float] = deque(maxlen=3)
        w.append(very_old)
        w.append(very_old)
        b._loop_guard_windows["t"] = w
        # Even ancient timestamps count when window_seconds == 0
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("t", "manual")

    def test_timestamps_are_monotonic(self) -> None:
        """Recorded timestamps increase or stay equal (never go back in time)."""
        b = make_budget(loop_guard_max_calls=10)
        for i in range(5):
            b._record_tool_call(f"tool_{i}", 0.0, "manual")
        # Check that the timestamps in _loop_guard_windows are monotonically non-decreasing
        for _name, window in b._loop_guard_windows.items():
            ts_list = list(window)
            for i in range(1, len(ts_list)):
                assert ts_list[i] >= ts_list[i - 1]

    def test_mixed_old_and_new_timestamps(self) -> None:
        """Guard fires when only recent timestamps fill the window."""
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=60.0)
        old = time.monotonic() - 120.0  # outside window
        now = time.monotonic()
        w: deque[float] = deque(maxlen=3)
        w.append(old)  # will be evicted
        w.append(now)
        w.append(now)
        b._loop_guard_windows["t"] = w
        # After eviction: 2 recent timestamps >= max_calls=2 → raises
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("t", "manual")

    def test_partially_expired_does_not_fire(self) -> None:
        """Only 1 recent timestamp when max_calls=2 → does NOT fire."""
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=60.0)
        old = time.monotonic() - 120.0
        now_ts = time.monotonic()
        w: deque[float] = deque(maxlen=3)
        w.append(old)  # expired
        w.append(now_ts)  # recent
        b._loop_guard_windows["t"] = w
        b._check_loop_guard("t", "manual")  # 1 < 2 → no raise


# ---------------------------------------------------------------------------
# 5. _record_tool_call timestamp append
# ---------------------------------------------------------------------------


class TestRecordToolCallTimestampAppend:
    def test_timestamp_appended_when_loop_guard_enabled(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("search", 0.0, "manual")
        assert "search" in b._loop_guard_windows
        assert len(b._loop_guard_windows["search"]) == 1

    def test_no_timestamp_when_loop_guard_disabled(self) -> None:
        b = Budget(loop_guard=False)
        b._record_tool_call("search", 0.0, "manual")
        assert "search" not in b._loop_guard_windows

    def test_deque_maxlen_is_max_calls_plus_one(self) -> None:
        b = make_budget(loop_guard_max_calls=5)
        b._record_tool_call("t", 0.0, "manual")
        assert b._loop_guard_windows["t"].maxlen == 6

    def test_separate_deques_per_tool(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("tool_a", 0.0, "manual")
        b._record_tool_call("tool_b", 0.0, "manual")
        assert "tool_a" in b._loop_guard_windows
        assert "tool_b" in b._loop_guard_windows
        assert b._loop_guard_windows["tool_a"] is not b._loop_guard_windows["tool_b"]

    def test_multiple_calls_same_tool_append(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        for _ in range(4):
            b._record_tool_call("search", 0.0, "manual")
        assert len(b._loop_guard_windows["search"]) == 4

    def test_deque_respects_maxlen(self) -> None:
        """Old entries are dropped when deque is full."""
        b = make_budget(loop_guard_max_calls=3)  # maxlen = 4
        for _ in range(10):
            b._record_tool_call("t", 0.0, "manual")
        assert len(b._loop_guard_windows["t"]) == 4  # maxlen=4


# ---------------------------------------------------------------------------
# 6. loop_guard_counts property
# ---------------------------------------------------------------------------


class TestLoopGuardCounts:
    def test_returns_empty_when_loop_guard_false(self) -> None:
        b = Budget(loop_guard=False)
        # _loop_guard_windows is empty, so result should be empty
        assert b.loop_guard_counts == {}

    def test_returns_correct_counts_per_tool(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("tool_a", 0.0, "manual")
        b._record_tool_call("tool_a", 0.0, "manual")
        b._record_tool_call("tool_b", 0.0, "manual")
        counts = b.loop_guard_counts
        assert counts["tool_a"] == 2
        assert counts["tool_b"] == 1

    def test_expired_timestamps_excluded(self) -> None:
        b = make_budget(loop_guard_max_calls=10, loop_guard_window_seconds=1.0)
        old = time.monotonic() - 10.0
        w: deque[float] = deque(maxlen=11)
        w.append(old)
        w.append(old)
        w.append(time.monotonic())  # recent
        b._loop_guard_windows["t"] = w
        counts = b.loop_guard_counts
        assert counts["t"] == 1  # only the recent one

    def test_snapshot_does_not_mutate_internal_state(self) -> None:
        b = make_budget(loop_guard_max_calls=10, loop_guard_window_seconds=60.0)
        b._record_tool_call("t", 0.0, "manual")
        original_len = len(b._loop_guard_windows["t"])
        _ = b.loop_guard_counts
        assert len(b._loop_guard_windows["t"]) == original_len

    def test_all_time_window_counts_all(self) -> None:
        b = make_budget(loop_guard_max_calls=10, loop_guard_window_seconds=0)
        old = time.monotonic() - 1_000_000.0
        w: deque[float] = deque(maxlen=11)
        w.append(old)
        w.append(old)
        b._loop_guard_windows["t"] = w
        counts = b.loop_guard_counts
        assert counts["t"] == 2

    def test_returns_zero_counts_for_empty_window(self) -> None:
        b = make_budget(loop_guard_max_calls=5, loop_guard_window_seconds=1.0)
        # All timestamps expired
        old = time.monotonic() - 100.0
        w: deque[float] = deque(maxlen=6)
        w.append(old)
        b._loop_guard_windows["t"] = w
        counts = b.loop_guard_counts
        assert counts["t"] == 0


# ---------------------------------------------------------------------------
# 7. _reset_state
# ---------------------------------------------------------------------------


class TestResetState:
    def test_clears_loop_guard_windows_on_reset(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("search", 0.0, "manual")
        assert "search" in b._loop_guard_windows
        b._reset_state()
        assert b._loop_guard_windows == {}

    def test_loop_guard_windows_is_fresh_dict_after_reset(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("t", 0.0, "manual")
        b._reset_state()
        assert isinstance(b._loop_guard_windows, dict)
        assert len(b._loop_guard_windows) == 0

    def test_reset_also_clears_tool_calls_made(self) -> None:
        """Existing reset behaviour still works alongside loop guard reset."""
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("t", 0.5, "manual")
        b._reset_state()
        assert b._tool_calls_made == 0
        assert b._tool_spent == 0.0


# ---------------------------------------------------------------------------
# 8. Call site integration via @tool decorator
# ---------------------------------------------------------------------------


class TestCallSiteIntegrationViaTool:
    def test_loop_guard_fires_via_tool_decorator(self) -> None:
        """Loop guard is triggered through the @tool-decorated function path."""
        b = make_budget(loop_guard_max_calls=2)

        @tool
        def my_search(q: str) -> str:
            return f"result for {q}"

        with b:
            my_search("q1")
            my_search("q2")
            with pytest.raises(AgentLoopError):
                my_search("q3")

    def test_guard_fires_before_tool_body_executes(self) -> None:
        """When loop guard fires, the tool body must NOT be called."""
        b = make_budget(loop_guard_max_calls=1)
        call_count = 0

        @tool
        def counting_tool() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        with b:
            counting_tool()  # first call succeeds
            with pytest.raises(AgentLoopError):
                counting_tool()  # guard fires — body must not run
        assert call_count == 1

    def test_loop_guard_fires_before_tool_limit(self) -> None:
        """When both loop_guard and max_tool_calls are set, loop guard fires first."""
        b = Budget(loop_guard=True, loop_guard_max_calls=2, max_tool_calls=100)

        @tool
        def t() -> str:
            return "ok"

        with b:
            t()
            t()
            with pytest.raises(AgentLoopError):
                t()  # loop guard fires (limit=2, 3rd call)

    def test_no_guard_when_loop_guard_false_via_tool(self) -> None:
        """With loop_guard=False, tool can be called any number of times."""
        b = Budget(loop_guard=False)

        @tool
        def repeated_tool() -> str:
            return "ok"

        with b:
            for _ in range(20):
                repeated_tool()

    @pytest.mark.asyncio
    async def test_async_tool_loop_guard_fires(self) -> None:
        """Loop guard fires for async @tool-decorated functions."""
        b = make_budget(loop_guard_max_calls=2)
        call_count = 0

        @tool
        async def async_search(q: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result for {q}"

        with b:
            await async_search("q1")
            await async_search("q2")
            with pytest.raises(AgentLoopError):
                await async_search("q3")
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_body_not_called_when_guard_fires(self) -> None:
        """Async tool body is not called when loop guard fires."""
        b = make_budget(loop_guard_max_calls=1)
        call_count = 0

        @tool
        async def async_tool() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        with b:
            await async_tool()
            with pytest.raises(AgentLoopError):
                await async_tool()
        assert call_count == 1


# ---------------------------------------------------------------------------
# 9. warn_only behaviour
# ---------------------------------------------------------------------------


class TestWarnOnlyBehaviour:
    def test_warn_only_uses_warnings_warn_not_print(self) -> None:
        """Must use warnings.warn, not print."""
        b = make_budget(loop_guard_max_calls=2, warn_only=True)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["t"] = w
        with patch("builtins.print") as mock_print:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                b._check_loop_guard("t", "manual")
            mock_print.assert_not_called()
        assert len(caught) == 1

    def test_warn_only_run_continues_after_guard(self) -> None:
        """With warn_only=True, calling a tool beyond limit still returns normally."""
        b = Budget(loop_guard=True, loop_guard_max_calls=2, warn_only=True)

        @tool
        def t() -> str:
            return "ok"

        results = []
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with b:
                results.append(t())
                results.append(t())
                results.append(t())  # warn_only — continues
        assert results == ["ok", "ok", "ok"]

    def test_warn_only_false_raises_not_warns(self) -> None:
        """When warn_only=False, loop guard raises AgentLoopError."""
        b = make_budget(loop_guard_max_calls=2, warn_only=False)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows["t"] = w
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("t", "manual")


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_string_tool_name_tracked(self) -> None:
        """Empty string is a valid key for the loop guard dict."""
        b = make_budget(loop_guard_max_calls=10)
        b._record_tool_call("", 0.0, "manual")
        assert "" in b._loop_guard_windows

    def test_empty_string_tool_name_check_loop_guard(self) -> None:
        b = make_budget(loop_guard_max_calls=2)
        w: deque[float] = deque(maxlen=3)
        now = time.monotonic()
        w.append(now)
        w.append(now)
        b._loop_guard_windows[""] = w
        with pytest.raises(AgentLoopError) as exc_info:
            b._check_loop_guard("", "manual")
        assert exc_info.value.tool_name == ""

    def test_very_large_max_calls_no_performance_issue(self) -> None:
        """Large max_calls value should not cause errors or slowness."""
        b = make_budget(loop_guard_max_calls=1000)
        for i in range(100):
            b._record_tool_call(f"tool_{i % 5}", 0.0, "manual")
        # 100 calls across 5 tools → each tool 20 calls — no guard fires
        b._check_loop_guard("tool_0", "manual")  # should not raise (20 < 1000)

    def test_window_seconds_zero_no_eviction(self) -> None:
        """With window_seconds=0, timestamps are never evicted."""
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=0)
        very_old = time.monotonic() - 1_000_000.0
        w: deque[float] = deque(maxlen=3)
        w.append(very_old)
        w.append(very_old)
        b._loop_guard_windows["t"] = w
        # No eviction → count 2 >= max_calls=2 → raises
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("t", "manual")

    def test_loop_guard_max_calls_one(self) -> None:
        """max_calls=1: guard fires on the second call."""
        b = make_budget(loop_guard_max_calls=1)
        w: deque[float] = deque(maxlen=2)
        w.append(time.monotonic())
        b._loop_guard_windows["t"] = w
        with pytest.raises(AgentLoopError):
            b._check_loop_guard("t", "manual")

    def test_loop_guard_counts_multiple_tools(self) -> None:
        b = make_budget(loop_guard_max_calls=10)
        for _ in range(3):
            b._record_tool_call("a", 0.0, "manual")
        for _ in range(5):
            b._record_tool_call("b", 0.0, "manual")
        counts = b.loop_guard_counts
        assert counts["a"] == 3
        assert counts["b"] == 5

    def test_check_loop_guard_no_window_created_when_disabled(self) -> None:
        """When loop_guard=False, _check_loop_guard should not create windows."""
        b = Budget(loop_guard=False)
        b._check_loop_guard("any_tool", "manual")
        assert "any_tool" not in b._loop_guard_windows

    def test_record_tool_call_creates_window_on_first_call(self) -> None:
        b = make_budget(loop_guard_max_calls=5)
        assert "new_tool" not in b._loop_guard_windows
        b._record_tool_call("new_tool", 0.0, "manual")
        assert "new_tool" in b._loop_guard_windows

    def test_check_loop_guard_creates_window_setdefault(self) -> None:
        """_check_loop_guard uses setdefault, so calling it creates the window."""
        b = make_budget(loop_guard_max_calls=5)
        # No prior record calls — check should still work and create window
        b._check_loop_guard("never_called", "manual")  # count is 0 < 5, no raise
        assert "never_called" in b._loop_guard_windows

    def test_multiple_budgets_independent(self) -> None:
        """Two Budget instances have independent loop guard state."""
        b1 = make_budget(loop_guard_max_calls=2)
        b2 = make_budget(loop_guard_max_calls=2)
        now = time.monotonic()
        w: deque[float] = deque(maxlen=3)
        w.append(now)
        w.append(now)
        b1._loop_guard_windows["t"] = w
        # b1 at limit, b2 still clean
        with pytest.raises(AgentLoopError):
            b1._check_loop_guard("t", "manual")
        b2._check_loop_guard("t", "manual")  # should not raise

    def test_loop_guard_window_seconds_very_small(self) -> None:
        """A tiny window (0.001s) causes all prior timestamps to expire quickly."""
        b = make_budget(loop_guard_max_calls=2, loop_guard_window_seconds=0.001)
        # Inject 2 timestamps from 1 second ago — far outside 0.001s window
        old = time.monotonic() - 1.0
        w: deque[float] = deque(maxlen=3)
        w.append(old)
        w.append(old)
        b._loop_guard_windows["t"] = w
        # Both expired → evicted → no raise
        b._check_loop_guard("t", "manual")
