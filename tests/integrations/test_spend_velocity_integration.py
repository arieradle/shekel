"""Integration tests for spend velocity end-to-end scenarios.

Mock tests (TestSpendVelocityMockIntegration) run without API keys and verify
that velocity enforcement fires correctly in realistic multi-call sequences.

Real-API tests (TestSpendVelocityLiveIntegration) require OPENAI_API_KEY.
"""

from __future__ import annotations

import os
import time

import pytest

from shekel import budget
from shekel._budget import Budget
from shekel.exceptions import BudgetExceededError, SpendVelocityExceededError


def _inject_spend(b: Budget, amount: float, model: str = "gpt-4o-mini") -> None:
    """Directly record spend on a budget (simulates a completed LLM call)."""
    b._record_spend(amount, model, {"input": 10, "output": 5})


# ---------------------------------------------------------------------------
# Mock integration
# ---------------------------------------------------------------------------


class TestSpendVelocityMockIntegration:
    """End-to-end velocity enforcement via direct _record_spend — no API keys."""

    def test_velocity_fires_on_burst(self) -> None:
        """Bursty spend exceeding velocity limit raises SpendVelocityExceededError."""
        with budget(max_usd=50.00, max_velocity="$0.10/min") as b:
            _inject_spend(b, 0.05)
            _inject_spend(b, 0.05)
            with pytest.raises(SpendVelocityExceededError) as exc_info:
                _inject_spend(b, 0.01)

        err = exc_info.value
        assert err.spent_in_window > 0.10
        assert err.limit_usd == pytest.approx(0.10)
        assert err.window_seconds == pytest.approx(60.0)
        assert err.velocity_per_min > 0

    def test_velocity_error_caught_by_budget_exceeded_error(self) -> None:
        """SpendVelocityExceededError is caught by except BudgetExceededError."""
        with budget(max_velocity="$0.05/min") as b:
            _inject_spend(b, 0.03)
            with pytest.raises(BudgetExceededError):
                _inject_spend(b, 0.03)

    def test_velocity_fires_before_max_usd(self) -> None:
        """Velocity fires before total cap — SpendVelocityExceededError, not BudgetExceededError."""
        with budget(max_usd=10.00, max_velocity="$0.05/min") as b:
            _inject_spend(b, 0.03)
            with pytest.raises(SpendVelocityExceededError):
                _inject_spend(b, 0.03)

    def test_velocity_only_no_total_cap(self) -> None:
        """budget(max_velocity=...) with no max_usd — only velocity enforced."""
        with budget(max_velocity="$0.10/min") as b:
            _inject_spend(b, 0.06)
            # next inject pushes window_sum to 0.06 + 0.06 = 0.12 > 0.10
            with pytest.raises(SpendVelocityExceededError):
                _inject_spend(b, 0.06)

    def test_warn_velocity_fires_before_hard_stop(self) -> None:
        """warn_velocity callback fires before velocity hard stop."""
        warnings_received = []

        def on_warn(spent: float, limit: float) -> None:
            warnings_received.append((spent, limit))

        with budget(
            max_usd=10.00,
            max_velocity="$0.10/min",
            warn_velocity="$0.06/min",
            on_warn=on_warn,
        ) as b:
            _inject_spend(b, 0.04)
            _inject_spend(b, 0.03)  # triggers warn_velocity (0.07 > 0.06)
            # warn fired once
            assert len(warnings_received) == 1
            assert warnings_received[0][1] == pytest.approx(0.06)

            with pytest.raises(SpendVelocityExceededError):
                _inject_spend(b, 0.04)  # triggers hard stop (0.11 > 0.10)

    def test_warn_velocity_fires_once_per_window(self) -> None:
        """warn_velocity fires at most once per window (not on every call after threshold)."""
        warn_count = 0

        def on_warn(spent: float, limit: float) -> None:
            nonlocal warn_count
            warn_count += 1

        with budget(
            max_velocity="$0.20/min",
            warn_velocity="$0.05/min",
            on_warn=on_warn,
        ) as b:
            _inject_spend(b, 0.06)  # crosses warn threshold
            _inject_spend(b, 0.01)  # still above threshold
            _inject_spend(b, 0.01)  # still above threshold

        assert warn_count == 1  # fired exactly once

    def test_velocity_warn_only_no_raise(self) -> None:
        """warn_only=True: velocity warning fires via warnings.warn, no exception raised."""
        with pytest.warns(UserWarning, match="velocity"):
            with budget(max_velocity="$0.05/min", warn_only=True) as b:
                _inject_spend(b, 0.03)
                _inject_spend(b, 0.03)  # would raise without warn_only
                assert b.spent == pytest.approx(0.06)

    def test_velocity_window_rollover_resets(self) -> None:
        """After window expires all entries pruned, velocity can fire again in next window."""
        with budget(max_velocity="$0.05/1s") as b:
            _inject_spend(b, 0.03)
            # wait for window to expire before the second burst
            time.sleep(1.1)
            # new window — can spend up to limit again
            _inject_spend(b, 0.03)  # should not raise (fresh window)

    def test_velocity_compound_with_max_usd(self) -> None:
        """Both max_usd and max_velocity active — velocity fires first on burst."""
        with budget(max_usd=5.00, max_velocity="$0.08/min") as b:
            _inject_spend(b, 0.05)
            with pytest.raises(SpendVelocityExceededError):
                _inject_spend(b, 0.04)  # velocity fires (0.09 > 0.08)
            # total cap (5.00) never reached

    def test_zero_cost_calls_do_not_affect_velocity(self) -> None:
        """Zero-cost calls (cached responses) accumulate in deque but don't affect velocity sum."""
        with budget(max_velocity="$0.05/min") as b:
            for _ in range(20):
                _inject_spend(b, 0.0)  # zero-cost
            assert b._velocity_window_sum == pytest.approx(0.0)

    def test_reset_clears_velocity_window(self) -> None:
        """b.reset() clears velocity window and warn_fired flag."""
        b = Budget(max_velocity="$0.05/min")
        with b:
            _inject_spend(b, 0.04)
        b.reset()
        assert b._velocity_window_sum == pytest.approx(0.0)
        assert b._velocity_warn_fired is False

    def test_async_budget_velocity_enforced(self) -> None:
        """Velocity enforcement works identically inside async with budget()."""
        import asyncio

        async def _run() -> None:
            async with budget(max_velocity="$0.05/min") as b:  # type: ignore[attr-defined]
                _inject_spend(b, 0.03)
                with pytest.raises(SpendVelocityExceededError):
                    _inject_spend(b, 0.03)

        asyncio.get_event_loop().run_until_complete(_run())

    def test_velocity_error_fields(self) -> None:
        """SpendVelocityExceededError carries correct field values."""
        with budget(max_velocity="$0.10/30s") as b:
            _inject_spend(b, 0.06)
            try:
                _inject_spend(b, 0.06)
            except SpendVelocityExceededError as e:
                assert e.window_seconds == pytest.approx(30.0)
                assert e.limit_usd == pytest.approx(0.10)
                assert e.limit_per_min == pytest.approx(0.10 / 30.0 * 60.0)
                assert e.velocity_per_min > e.limit_per_min

    def test_nested_budget_parent_velocity_independent(self) -> None:
        """Child budget tracks its own velocity; parent receives full child spend on exit."""
        with budget(name="parent", max_usd=10.00) as parent:
            with budget(name="child", max_velocity="$0.05/min") as child:
                _inject_spend(child, 0.03)
                # next inject pushes child window_sum to 0.06 > 0.05; spend is
                # recorded on child._spent before the velocity check raises, so
                # both 0.03 amounts propagate to parent on child exit.
                with pytest.raises(SpendVelocityExceededError):
                    _inject_spend(child, 0.03)
            # parent still alive — child propagated full 0.06
            assert parent.spent == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# Real API: requires OPENAI_API_KEY
# ---------------------------------------------------------------------------


class TestSpendVelocityLiveIntegration:
    """Velocity enforcement with a real OpenAI call — skipped without API key."""

    @pytest.fixture(autouse=True)
    def require_openai_key(self) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

    def test_single_real_call_under_velocity_limit(self) -> None:
        """A single real OpenAI call completes normally under a generous velocity limit."""
        import openai

        client = openai.OpenAI()

        with budget(max_usd=0.10, max_velocity="$5/min") as b:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say one word."}],
                max_tokens=5,
            )
            assert resp.choices[0].message.content
            assert b.spent > 0
            assert b._velocity_window_sum == pytest.approx(b.spent, abs=1e-6)
