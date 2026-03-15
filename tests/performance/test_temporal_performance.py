"""Performance tests for temporal (rolling-window) budgets.

Measures:
- String spec parsing overhead
- InMemoryBackend check_and_add vs plain dict lookup
- TemporalBudget.__enter__/__exit__ overhead vs plain Budget
- Ancestor walk overhead at 1–5 nesting depths
- Window state lookup with large N distinct users
- Memory footprint of TemporalBudget and InMemoryBackend
- BudgetExceededError creation with temporal fields
"""

from __future__ import annotations

import sys
import time

from shekel._budget import Budget
from shekel._temporal import InMemoryBackend, TemporalBudget, _parse_spec
from shekel.exceptions import BudgetExceededError
from shekel.integrations import AdapterRegistry

# ---------------------------------------------------------------------------
# String parser
# ---------------------------------------------------------------------------


class TestParseSpecPerformance:
    """Benchmark _parse_spec() string DSL parsing."""

    def test_parse_dollar_per_hr(self, benchmark):
        """Parse '$5/hr' repeatedly."""
        result = benchmark(_parse_spec, "$5/hr")
        assert result == (5.0, 3600.0)

    def test_parse_dollar_per_30min(self, benchmark):
        """Parse '$10/30min' — with count multiplier."""
        result = benchmark(_parse_spec, "$10/30min")
        assert result == (10.0, 1800.0)

    def test_parse_dollar_per_60s(self, benchmark):
        """Parse '$1/60s'."""
        result = benchmark(_parse_spec, "$1/60s")
        assert result == (1.0, 60.0)

    def test_parse_dollar_per_1hr_long_form(self, benchmark):
        """Parse '$5 per 1hr' — 'per' long form."""
        result = benchmark(_parse_spec, "$5 per 1hr")
        assert result == (5.0, 3600.0)


# ---------------------------------------------------------------------------
# InMemoryBackend operations
# ---------------------------------------------------------------------------


class TestInMemoryBackendPerformance:
    """Benchmark InMemoryBackend operations."""

    def test_get_state_miss(self, benchmark):
        """get_state on an unseen key (cold path)."""
        backend = InMemoryBackend()

        def op():
            return backend.get_state("unknown_key")

        result = benchmark(op)
        assert result == (0.0, None)

    def test_get_state_hit(self, benchmark):
        """get_state on an existing key (warm path)."""
        backend = InMemoryBackend()
        backend._state["existing"] = (2.5, 1000.0)

        def op():
            return backend.get_state("existing")

        result = benchmark(op)
        assert result[0] == 2.5

    def test_check_and_add_within_limit(self, benchmark):
        """check_and_add accepted (most common hot path)."""
        backend = InMemoryBackend()

        def op():
            backend._state.clear()
            return backend.check_and_add("budget", 0.001, 5.0, 3600.0)

        result = benchmark(op)
        assert result is True

    def test_check_and_add_exceeds_limit(self, benchmark):
        """check_and_add rejected (limit exceeded path)."""
        backend = InMemoryBackend()
        backend._state["budget"] = (4.999, 1000.0)

        def op():
            return backend.check_and_add("budget", 0.002, 5.0, 3600.0)

        result = benchmark(op)
        assert result is False

    def test_check_and_add_window_expiry(self, benchmark):
        """check_and_add when window has expired (reset path)."""
        backend = InMemoryBackend()
        # Window started long ago — will expire on every call
        old_start = time.monotonic() - 7200.0
        backend._state["budget"] = (4.5, old_start)

        def op():
            return backend.check_and_add("budget", 0.001, 5.0, 3600.0)

        result = benchmark(op)
        assert result is True

    def test_check_and_add_many_distinct_users(self, benchmark):
        """check_and_add across 1000 distinct user keys (multi-tenant lookup)."""
        backend = InMemoryBackend()
        keys = [f"user:{i}" for i in range(1000)]

        def op():
            for key in keys:
                backend.check_and_add(key, 0.001, 5.0, 3600.0)

        benchmark(op)
        assert len(backend._state) == 1000

    def test_reset(self, benchmark):
        """Backend reset overhead."""
        backend = InMemoryBackend()
        backend._state["budget"] = (2.0, 1000.0)

        def op():
            backend._state["budget"] = (2.0, 1000.0)
            backend.reset("budget")

        benchmark(op)
        assert backend.get_state("budget") == (0.0, None)


# ---------------------------------------------------------------------------
# TemporalBudget context manager overhead
# ---------------------------------------------------------------------------


class TestTemporalBudgetContextOverhead:
    """Benchmark TemporalBudget enter/exit vs plain Budget."""

    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_plain_budget_enter_exit(self, benchmark):
        """Baseline: plain Budget enter/exit with no LLM calls."""
        b = Budget(max_usd=5.0, name="baseline")

        def op():
            b.__enter__()
            b.__exit__(None, None, None)

        benchmark(op)

    def test_temporal_budget_enter_exit(self, benchmark):
        """TemporalBudget enter/exit with no LLM calls (no window expiry)."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="temporal", backend=backend)

        def op():
            tb.__enter__()
            tb.__exit__(None, None, None)

        benchmark(op)

    def test_temporal_budget_enter_with_existing_window(self, benchmark):
        """TemporalBudget enter when window is already active (hot path)."""
        backend = InMemoryBackend()
        backend._state["hot"] = (1.0, time.monotonic())
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="hot", backend=backend)

        def op():
            tb.__enter__()
            tb.__exit__(None, None, None)

        benchmark(op)

    def test_temporal_budget_entry_with_expired_window(self, benchmark):
        """TemporalBudget enter when window expired (lazy reset path)."""
        backend = InMemoryBackend()
        old_start = time.monotonic() - 7200.0
        backend._state["expiry"] = (2.5, old_start)
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="expiry", backend=backend)

        def op():
            tb.__enter__()
            tb.__exit__(None, None, None)

        benchmark(op)


# ---------------------------------------------------------------------------
# Ancestor walk performance
# ---------------------------------------------------------------------------


class TestAncestorWalkPerformance:
    """Benchmark _check_temporal_ancestor at various nesting depths."""

    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_ancestor_walk_depth_0(self, benchmark):
        """No active budget — O(1) check."""
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="depth0")

        def op():
            tb._check_temporal_ancestor()

        benchmark(op)

    def test_ancestor_walk_depth_1_regular(self, benchmark):
        """One regular Budget ancestor — walk 1 level."""
        outer = Budget(max_usd=10.0, name="outer")
        inner = TemporalBudget(max_usd=5.0, window_seconds=3600, name="inner")

        outer.__enter__()
        try:

            def op():
                inner._check_temporal_ancestor()

            benchmark(op)
        finally:
            outer.__exit__(None, None, None)

    def test_ancestor_walk_depth_3_regular(self, benchmark):
        """Three regular Budget ancestors — walk 3 levels."""
        b1 = Budget(max_usd=10.0, name="b1")
        b2 = Budget(max_usd=9.0, name="b2")
        b3 = Budget(max_usd=8.0, name="b3")
        inner = TemporalBudget(max_usd=5.0, window_seconds=3600, name="inner3")

        b1.__enter__()
        b2.__enter__()
        b3.__enter__()
        try:

            def op():
                inner._check_temporal_ancestor()

            benchmark(op)
        finally:
            b3.__exit__(None, None, None)
            b2.__exit__(None, None, None)
            b1.__exit__(None, None, None)

    def test_ancestor_walk_depth_5_regular(self, benchmark):
        """Five regular Budget ancestors — maximum walk depth."""
        budgets = [Budget(max_usd=10.0 - i, name=f"b{i}") for i in range(5)]
        inner = TemporalBudget(max_usd=5.0, window_seconds=3600, name="inner5")

        for b in budgets:
            b.__enter__()
        try:

            def op():
                inner._check_temporal_ancestor()

            benchmark(op)
        finally:
            for b in reversed(budgets):
                b.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# _record_spend overhead
# ---------------------------------------------------------------------------


class TestRecordSpendPerformance:
    """Benchmark TemporalBudget._record_spend vs Budget._record_spend."""

    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_plain_budget_record_spend(self, benchmark):
        """Baseline: Budget._record_spend with no window check."""
        b = Budget(max_usd=5.0, name="base_record")
        b.__enter__()
        try:

            def op():
                b._record_spend(0.0001, "gpt-4o-mini", {"input": 10, "output": 5})

            benchmark(op)
        finally:
            b.__exit__(None, None, None)

    def test_temporal_budget_record_spend_within_limit(self, benchmark):
        """TemporalBudget._record_spend — spend accepted (warm backend)."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=100.0, window_seconds=3600, name="rec_ok", backend=backend)
        tb.__enter__()
        try:

            def op():
                tb._record_spend(0.0001, "gpt-4o-mini", {"input": 10, "output": 5})

            benchmark(op)
        finally:
            tb.__exit__(None, None, None)

    def test_temporal_budget_record_spend_no_limit(self, benchmark):
        """TemporalBudget with max_usd=None — skips window check entirely."""
        backend = InMemoryBackend()
        tb = TemporalBudget(
            max_usd=0.0,  # won't be enforced; _effective_limit path
            window_seconds=3600,
            name="no_lim",
            backend=backend,
        )
        # Override effective_limit to None to test the no-limit path
        tb._effective_limit = None  # type: ignore[assignment]

        def op():
            tb._record_spend(0.0001, "gpt-4o-mini", {"input": 10, "output": 5})

        benchmark(op)


# ---------------------------------------------------------------------------
# Memory footprint
# ---------------------------------------------------------------------------


class TestTemporalMemoryFootprint:
    """Benchmark memory usage of temporal budget objects."""

    def test_in_memory_backend_empty_size(self):
        """InMemoryBackend with no entries should be small."""
        backend = InMemoryBackend()
        size = sys.getsizeof(backend) + sys.getsizeof(backend._state)
        assert size < 2000

    def test_in_memory_backend_1000_users_size(self):
        """Backend grows linearly with user count."""
        backend = InMemoryBackend()
        for i in range(1000):
            backend._state[f"user:{i}"] = (float(i) * 0.001, float(i))
        # Dict with 1000 entries should still be bounded
        size = sys.getsizeof(backend._state)
        assert size < 200_000  # well under 200KB

    def test_temporal_budget_instance_size(self):
        """Single TemporalBudget instance should be small."""
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="mem_test")
        size = sys.getsizeof(tb)
        assert size < 5000

    def test_many_temporal_budget_instances(self):
        """1000 TemporalBudget instances with a shared backend."""
        backend = InMemoryBackend()
        budgets = [
            TemporalBudget(
                max_usd=5.0,
                window_seconds=3600,
                name=f"user:{i}",
                backend=backend,
            )
            for i in range(1000)
        ]
        # All instances share one backend — backend memory is bounded
        total_size = sum(sys.getsizeof(b) for b in budgets)
        backend_size = sys.getsizeof(backend._state)
        # Each budget is small; shared backend adds nothing per instance
        assert total_size < 5_000_000  # <5MB for 1000 instances
        assert backend_size < 1000  # empty backend (no window state yet)


# ---------------------------------------------------------------------------
# BudgetExceededError with temporal fields
# ---------------------------------------------------------------------------


class TestTemporalErrorPerformance:
    """Benchmark BudgetExceededError creation with retry_after/window_spent."""

    def test_create_with_retry_after(self, benchmark):
        """BudgetExceededError with retry_after is not meaningfully slower."""

        def create():
            return BudgetExceededError(
                spent=5.01,
                limit=5.0,
                retry_after=1800.0,
                window_spent=5.01,
            )

        result = benchmark(create)
        assert result.retry_after == 1800.0
        assert result.window_spent == 5.01

    def test_create_without_temporal_fields(self, benchmark):
        """Baseline: BudgetExceededError without temporal fields."""

        def create():
            return BudgetExceededError(spent=5.01, limit=5.0)

        result = benchmark(create)
        assert result.retry_after is None
        assert result.window_spent is None
