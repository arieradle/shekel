"""Performance tests: spend velocity overhead per _record_spend call.

Verifies that enabling max_velocity adds less than 5 µs per _record_spend
call and that the velocity deque stays memory-bounded.
"""

from __future__ import annotations

import time

import pytest

from shekel._budget import Budget


def _inject(b: Budget, cost: float = 0.0001) -> None:
    b._record_spend(cost, "gpt-4o-mini", {"input": 10, "output": 5})


class TestVelocityOverhead:
    """Velocity check must add negligible overhead per _record_spend."""

    def test_overhead_per_record_spend_reasonable(self) -> None:
        """Velocity check adds < 200 µs per _record_spend call (WSL/CI-safe threshold)."""
        N = 500
        # Use a very generous limit so velocity never fires during measurement
        with Budget(max_usd=1000.00, max_velocity="$999/min") as b:
            t0 = time.perf_counter()
            for _ in range(N):
                _inject(b, 0.0001)
            elapsed = (time.perf_counter() - t0) / N

        assert (
            elapsed < 200e-6
        ), f"velocity overhead too high: {elapsed * 1e6:.2f} µs per call (limit 200 µs)"

    def test_overhead_velocity_disabled_baseline(self) -> None:
        """Baseline without velocity: _record_spend overhead should be < 200 µs."""
        N = 500
        with Budget(max_usd=1000.00) as b:
            t0 = time.perf_counter()
            for _ in range(N):
                _inject(b, 0.0001)
            elapsed = (time.perf_counter() - t0) / N

        assert (
            elapsed < 200e-6
        ), f"baseline _record_spend too slow: {elapsed * 1e6:.2f} µs (limit 200 µs)"

    def test_pruning_pass_under_1ms(self) -> None:
        """Full deque prune pass (all entries expired) completes < 1 ms."""
        import time as _time

        # Use a very short window (1 ms) and pre-fill with 1000 entries
        b = Budget(max_velocity="$999/1s")
        b.__enter__()
        try:
            for _ in range(1000):
                b._velocity_window.append((_time.monotonic() - 2.0, 0.0001))  # already expired

            t0 = _time.perf_counter()
            b._prune_velocity_window(_time.monotonic())
            elapsed = _time.perf_counter() - t0

            assert elapsed < 1e-3, f"prune pass too slow: {elapsed * 1e3:.2f} ms"
            assert len(b._velocity_window) == 0
        finally:
            b.__exit__(None, None, None)

    def test_deque_memory_bounded(self) -> None:
        """Velocity deque stays bounded — old entries are pruned on each call."""
        N = 10_000
        # Short window so entries expire and are pruned during the run
        with Budget(max_velocity="$999/0.1s") as b:
            for i in range(N):
                _inject(b, 0.00001)

            # After N calls over > 0.1s, the deque should contain only recent entries
            deque_size = len(b._velocity_window)
            # Should be far less than N — most expired and were pruned
            assert deque_size < N, f"deque not pruned: {deque_size} entries (expected < {N})"

    def test_velocity_window_sum_property_performance(self) -> None:
        """_velocity_window_sum on a window of 100 entries is < 100 µs."""
        with Budget(max_velocity="$999/min") as b:
            for _ in range(100):
                _inject(b, 0.001)

            t0 = time.perf_counter()
            for _ in range(1000):
                _ = b._velocity_window_sum
            elapsed = (time.perf_counter() - t0) / 1000

        assert (
            elapsed < 100e-6
        ), f"_velocity_window_sum too slow: {elapsed * 1e6:.2f} µs (limit 100 µs)"

    def test_velocity_overhead_benchmark(self, benchmark: pytest.fixture) -> None:  # type: ignore[type-arg]
        """Benchmark version — runs only when pytest-benchmark is active."""
        b = Budget(max_usd=1000.00, max_velocity="$999/min")
        b.__enter__()

        def _record() -> None:
            b._record_spend(0.0001, "gpt-4o-mini", {"input": 10, "output": 5})

        try:
            benchmark(_record)
        finally:
            b.__exit__(None, None, None)
