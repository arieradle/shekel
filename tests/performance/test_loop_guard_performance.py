"""Performance tests: loop guard overhead per tool dispatch.

Verifies that enabling loop_guard adds less than 10 µs per tool dispatch
and that memory usage stays bounded.
"""

from __future__ import annotations

import sys
import time

import pytest

from shekel._budget import Budget


class TestLoopGuardOverhead:
    """Loop guard must add negligible overhead per dispatch."""

    def test_overhead_per_dispatch_under_10us(self) -> None:
        """Loop guard check adds < 10 µs per tool dispatch (wall clock)."""
        N = 1000
        # Use a high max_calls so the gate never fires during measurement
        with Budget(max_usd=100.00, loop_guard=True, loop_guard_max_calls=N + 10) as b:
            # Pre-fill window to simulate a realistic mid-session state
            for i in range(min(N - 1, 50)):
                b._check_loop_guard(f"tool_{i % 5}", "manual")
                b._record_tool_call(f"tool_{i % 5}", 0.0, "manual")

            t0 = time.perf_counter()
            for j in range(N):
                b._check_loop_guard(f"bench_tool_{j % 10}", "manual")
            elapsed = (time.perf_counter() - t0) / N

        assert (
            elapsed < 10e-6
        ), f"loop guard overhead too high: {elapsed * 1e6:.2f} µs per call (limit 10 µs)"

    def test_overhead_empty_window_under_200us(self) -> None:
        """With an empty window (fresh budget), overhead is < 200 µs per check+record pair."""
        N = 2000
        with Budget(loop_guard=True, loop_guard_max_calls=N + 1) as b:
            t0 = time.perf_counter()
            for i in range(N):
                b._check_loop_guard("bench_tool", "manual")
                b._record_tool_call("bench_tool", 0.0, "manual")
            elapsed = (time.perf_counter() - t0) / N

        assert (
            elapsed < 200e-6
        ), f"empty-window loop guard overhead too high: {elapsed * 1e6:.2f} µs (limit 200 µs)"

    def test_overhead_loop_guard_disabled_baseline(self) -> None:
        """Baseline with loop_guard=False: _check_loop_guard is a no-op."""
        N = 2000
        with Budget(loop_guard=False) as b:
            t0 = time.perf_counter()
            for _ in range(N):
                b._check_loop_guard("bench_tool", "manual")
            elapsed = (time.perf_counter() - t0) / N

        # No-op should be < 1 µs
        assert elapsed < 1e-6, f"disabled loop guard check too slow: {elapsed * 1e6:.2f} µs"

    def test_memory_bounded_for_many_tool_names(self) -> None:
        """100 distinct tool names × 5 entries each stays well under 1 MB."""

        N_TOOLS = 100
        MAX_CALLS = 5

        with Budget(loop_guard=True, loop_guard_max_calls=MAX_CALLS) as b:
            for i in range(N_TOOLS):
                tool_name = f"tool_{i:03d}"
                for _ in range(MAX_CALLS - 1):  # fill without triggering
                    b._record_tool_call(tool_name, 0.0, "manual")

            size = sys.getsizeof(b._loop_guard_windows)
            # rough bound: each deque entry is ~28 bytes float, 5 entries × 100 tools
            # plus dict overhead — well under 1 MB
            assert size < 1_000_000, f"_loop_guard_windows too large: {size} bytes"

    def test_eviction_does_not_degrade_over_time(self) -> None:
        """After many window rollovers, per-call overhead stays flat."""
        import time as _time

        N = 500
        with Budget(
            loop_guard=True,
            loop_guard_max_calls=N + 1,
            loop_guard_window_seconds=0.001,  # 1 ms window → fast rollover
        ) as b:
            times: list[float] = []
            for i in range(N):
                if i % 50 == 0:
                    _time.sleep(0.002)  # trigger window rollover
                t0 = _time.perf_counter()
                b._check_loop_guard("rolling_tool", "manual")
                b._record_tool_call("rolling_tool", 0.0, "manual")
                times.append(_time.perf_counter() - t0)

        # No single call should be > 1 ms (even with eviction)
        worst = max(times)
        assert worst < 1e-3, f"worst-case call with eviction: {worst * 1e3:.2f} ms"

    def test_loop_guard_benchmark(self, benchmark: pytest.fixture) -> None:  # type: ignore[type-arg]
        """Benchmark version — runs only when pytest-benchmark is active."""
        b = Budget(loop_guard=True, loop_guard_max_calls=10000)
        b.__enter__()

        def _check() -> None:
            b._check_loop_guard("bench", "manual")

        try:
            benchmark(_check)
        finally:
            b.__exit__(None, None, None)
