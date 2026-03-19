"""Tests for the Spend Velocity feature (shekel v1.1.0).

Domain: spend velocity — rolling-window spend rate enforcement.

TDD: these tests were written first (red), then implementation made them green.
"""

from __future__ import annotations

import time
import warnings
from collections import deque

import pytest

from shekel._budget import Budget, _parse_velocity_spec
from shekel.exceptions import BudgetExceededError, SpendVelocityExceededError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_budget(**kwargs: object) -> Budget:
    """Return a Budget with velocity settings."""
    return Budget(**kwargs)  # type: ignore[arg-type]


def record_spend(b: Budget, cost: float, model: str = "gpt-4o") -> None:
    """Directly invoke _record_spend on a budget (simulates an LLM call)."""
    b._record_spend(cost, model, {"input": 100, "output": 50})


# ---------------------------------------------------------------------------
# 1. Parser: _parse_velocity_spec
# ---------------------------------------------------------------------------


class TestParseVelocitySpec:
    def test_dollars_per_min(self) -> None:
        amount, window = _parse_velocity_spec("$0.50/min")
        assert amount == pytest.approx(0.50)
        assert window == pytest.approx(60.0)

    def test_dollars_per_hr(self) -> None:
        amount, window = _parse_velocity_spec("$2/hr")
        assert amount == pytest.approx(2.0)
        assert window == pytest.approx(3600.0)

    def test_dollars_per_30s(self) -> None:
        amount, window = _parse_velocity_spec("$0.10/30s")
        assert amount == pytest.approx(0.10)
        assert window == pytest.approx(30.0)

    def test_dollars_per_1_5min(self) -> None:
        amount, window = _parse_velocity_spec("$1/1.5min")
        assert amount == pytest.approx(1.0)
        assert window == pytest.approx(90.0)

    def test_dollars_per_h_alias(self) -> None:
        amount, window = _parse_velocity_spec("$5/h")
        assert amount == pytest.approx(5.0)
        assert window == pytest.approx(3600.0)

    def test_dollars_per_sec(self) -> None:
        amount, window = _parse_velocity_spec("$0.25/sec")
        assert amount == pytest.approx(0.25)
        assert window == pytest.approx(1.0)

    def test_dollars_per_m_alias_for_min(self) -> None:
        amount, window = _parse_velocity_spec("$2/m")
        assert amount == pytest.approx(2.0)
        assert window == pytest.approx(60.0)

    def test_case_insensitive_min(self) -> None:
        amount, window = _parse_velocity_spec("$0.50/MIN")
        assert amount == pytest.approx(0.50)
        assert window == pytest.approx(60.0)

    def test_case_insensitive_hr(self) -> None:
        amount, window = _parse_velocity_spec("$1/HR")
        assert amount == pytest.approx(1.0)
        assert window == pytest.approx(3600.0)

    def test_leading_trailing_whitespace_stripped(self) -> None:
        amount, window = _parse_velocity_spec("  $0.50/min  ")
        assert amount == pytest.approx(0.50)
        assert window == pytest.approx(60.0)

    def test_fractional_window_1_5min(self) -> None:
        amount, window = _parse_velocity_spec("$0.50/1.5min")
        assert amount == pytest.approx(0.50)
        assert window == pytest.approx(90.0)

    def test_fractional_window_2_5hr(self) -> None:
        amount, window = _parse_velocity_spec("$1/2.5hr")
        assert amount == pytest.approx(1.0)
        assert window == pytest.approx(9000.0)

    def test_s_alias_for_sec(self) -> None:
        amount, window = _parse_velocity_spec("$0.10/5s")
        assert amount == pytest.approx(0.10)
        assert window == pytest.approx(5.0)

    def test_implicit_count_of_1_for_sec(self) -> None:
        # "$0.25/sec" means 0.25 per 1 second
        amount, window = _parse_velocity_spec("$0.25/sec")
        assert amount == pytest.approx(0.25)
        assert window == pytest.approx(1.0)

    def test_malformed_missing_unit(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse velocity spec"):
            _parse_velocity_spec("$1.50")

    def test_malformed_missing_dollar_sign(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse velocity spec"):
            _parse_velocity_spec("1.50/min")

    def test_malformed_zero_amount(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            _parse_velocity_spec("$0/min")

    def test_malformed_empty_string(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse velocity spec"):
            _parse_velocity_spec("")

    def test_malformed_no_slash(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse velocity spec"):
            _parse_velocity_spec("$1min")

    def test_malformed_negative_amount(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse velocity spec"):
            _parse_velocity_spec("$-1/min")

    def test_returns_tuple(self) -> None:
        result = _parse_velocity_spec("$1/hr")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_large_amount(self) -> None:
        amount, window = _parse_velocity_spec("$1000/hr")
        assert amount == pytest.approx(1000.0)
        assert window == pytest.approx(3600.0)

    def test_very_small_amount(self) -> None:
        amount, window = _parse_velocity_spec("$0.001/sec")
        assert amount == pytest.approx(0.001)
        assert window == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. SpendVelocityExceededError class
# ---------------------------------------------------------------------------


class TestSpendVelocityExceededError:
    def test_is_subclass_of_budget_exceeded_error(self) -> None:
        assert issubclass(SpendVelocityExceededError, BudgetExceededError)

    def test_caught_by_budget_exceeded_error(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        with pytest.raises(BudgetExceededError):
            raise err

    def test_spent_in_window_stored(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.spent_in_window == pytest.approx(0.75)

    def test_limit_usd_stored(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.limit_usd == pytest.approx(0.50)

    def test_window_seconds_stored(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.window_seconds == pytest.approx(60.0)

    def test_velocity_per_min_computed(self) -> None:
        # spent=0.75 in 60s -> 0.75/min
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.velocity_per_min == pytest.approx(0.75)

    def test_velocity_per_min_with_shorter_window(self) -> None:
        # spent=0.10 in 30s -> 0.10/30 * 60 = 0.20/min
        err = SpendVelocityExceededError(
            spent_in_window=0.10,
            limit_usd=0.05,
            window_seconds=30.0,
        )
        assert err.velocity_per_min == pytest.approx(0.20)

    def test_limit_per_min_computed(self) -> None:
        # limit=0.50 in 60s -> 0.50/min
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.limit_per_min == pytest.approx(0.50)

    def test_limit_per_min_with_shorter_window(self) -> None:
        # limit=0.05 in 30s -> 0.05/30 * 60 = 0.10/min
        err = SpendVelocityExceededError(
            spent_in_window=0.10,
            limit_usd=0.05,
            window_seconds=30.0,
        )
        assert err.limit_per_min == pytest.approx(0.10)

    def test_str_includes_window_sum(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.7531,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert "0.7531" in str(err)

    def test_str_includes_window_seconds(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert "60" in str(err)

    def test_str_includes_limit_per_min(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        # limit_per_min = 0.50 for this case
        assert "0.50" in str(err)

    def test_model_stored_via_super(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
            model="gpt-4o",
        )
        assert err.model == "gpt-4o"

    def test_tokens_stored_via_super(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
            tokens={"input": 100, "output": 50},
        )
        assert err.tokens == {"input": 100, "output": 50}

    def test_default_model_is_unknown(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.model == "unknown"

    def test_spent_field_equals_spent_in_window(self) -> None:
        # BudgetExceededError.spent should equal spent_in_window
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.spent == pytest.approx(0.75)

    def test_limit_field_equals_limit_usd(self) -> None:
        err = SpendVelocityExceededError(
            spent_in_window=0.75,
            limit_usd=0.50,
            window_seconds=60.0,
        )
        assert err.limit == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# 3. Budget constructor: max_velocity / warn_velocity params
# ---------------------------------------------------------------------------


class TestBudgetConstructorVelocity:
    def test_max_velocity_sets_limit(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        assert b._velocity_limit_usd == pytest.approx(0.50)

    def test_max_velocity_sets_window_seconds(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        assert b._velocity_window_seconds == pytest.approx(60.0)

    def test_max_velocity_none_by_default(self) -> None:
        b = make_budget()
        assert b._velocity_limit_usd is None

    def test_max_velocity_hr(self) -> None:
        b = make_budget(max_velocity="$2/hr")
        assert b._velocity_limit_usd == pytest.approx(2.0)
        assert b._velocity_window_seconds == pytest.approx(3600.0)

    def test_max_velocity_without_max_usd_is_valid(self) -> None:
        # Velocity-only guard — no max_usd required
        b = make_budget(max_velocity="$2/hr")
        assert b.max_usd is None
        assert b._velocity_limit_usd == pytest.approx(2.0)

    def test_warn_velocity_without_max_velocity_raises(self) -> None:
        with pytest.raises(ValueError, match="warn_velocity requires max_velocity"):
            make_budget(warn_velocity="$0.25/min")

    def test_warn_velocity_equal_to_max_velocity_raises(self) -> None:
        with pytest.raises(ValueError, match="must be less than"):
            make_budget(max_velocity="$0.50/min", warn_velocity="$0.50/min")

    def test_warn_velocity_greater_than_max_velocity_raises(self) -> None:
        with pytest.raises(ValueError, match="must be less than"):
            make_budget(max_velocity="$0.50/min", warn_velocity="$0.60/min")

    def test_warn_velocity_less_than_max_velocity_is_valid(self) -> None:
        b = make_budget(max_velocity="$0.50/min", warn_velocity="$0.30/min")
        assert b._warn_velocity_limit_usd == pytest.approx(0.30)

    def test_warn_velocity_stored_correctly(self) -> None:
        b = make_budget(max_velocity="$1.00/hr", warn_velocity="$0.80/hr")
        assert b._warn_velocity_limit_usd == pytest.approx(0.80)

    def test_velocity_window_deque_initialized(self) -> None:
        b = make_budget(max_velocity="$1/min")
        assert isinstance(b._velocity_window, deque)
        assert len(b._velocity_window) == 0

    def test_velocity_warn_fired_initialized_false(self) -> None:
        b = make_budget(max_velocity="$1/min", warn_velocity="$0.5/min")
        assert b._velocity_warn_fired is False

    def test_malformed_max_velocity_raises(self) -> None:
        with pytest.raises(ValueError):
            make_budget(max_velocity="bad spec")

    def test_malformed_warn_velocity_raises(self) -> None:
        with pytest.raises(ValueError):
            make_budget(max_velocity="$1/min", warn_velocity="bad spec")

    def test_velocity_combined_with_max_usd(self) -> None:
        b = make_budget(max_usd=10.0, max_velocity="$0.50/min")
        assert b.max_usd == pytest.approx(10.0)
        assert b._velocity_limit_usd == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# 4. _check_velocity_limit — hard cap
# ---------------------------------------------------------------------------


class TestCheckVelocityLimit:
    def test_no_velocity_limit_no_raise(self) -> None:
        b = make_budget()
        # No velocity limit — should not raise regardless of spend
        b._record_spend(999.0, "gpt-4o", {"input": 0, "output": 0})
        # No exception raised

    def test_first_call_under_limit_no_raise(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        # 0.50 < 1.00 → no raise

    def test_accumulation_triggers_error(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError):
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})

    def test_error_has_correct_spent_in_window(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError) as exc_info:
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        assert exc_info.value.spent_in_window == pytest.approx(1.10, rel=1e-3)

    def test_error_has_correct_limit_usd(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError) as exc_info:
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        assert exc_info.value.limit_usd == pytest.approx(1.00)

    def test_error_has_correct_window_seconds(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError) as exc_info:
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        assert exc_info.value.window_seconds == pytest.approx(60.0)

    def test_warn_only_issues_warning_not_raise(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_only=True)
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        assert len(w) >= 1
        messages = " ".join(str(x.message) for x in w)
        assert "velocity" in messages.lower()

    def test_warn_only_with_on_warn_callback(self) -> None:
        calls: list[tuple[float, float]] = []
        b = make_budget(
            max_velocity="$1.00/min", warn_only=True, on_warn=lambda s, lim: calls.append((s, lim))
        )
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        assert len(calls) >= 1
        # The velocity-exceeded on_warn should have been called with (window_sum, limit)
        sums = [c[0] for c in calls]
        assert any(s > 1.0 for s in sums)

    def test_caught_by_budget_exceeded_error(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(BudgetExceededError):
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})

    def test_exactly_at_limit_does_not_raise(self) -> None:
        # window_sum == limit (not strictly greater) → no raise
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(1.00, "gpt-4o", {"input": 0, "output": 0})
        # Should not raise (window_sum == limit, not > limit)

    def test_slightly_over_limit_raises(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError):
            b._record_spend(0.51, "gpt-4o", {"input": 0, "output": 0})


# ---------------------------------------------------------------------------
# 5. _check_velocity_warn — soft warning
# ---------------------------------------------------------------------------


class TestCheckVelocityWarn:
    def test_no_warn_velocity_no_warning(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b._record_spend(0.80, "gpt-4o", {"input": 0, "output": 0})
        velocity_warns = [x for x in w if "velocity warning" in str(x.message).lower()]
        assert len(velocity_warns) == 0

    def test_fires_when_warn_limit_reached(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b._record_spend(0.55, "gpt-4o", {"input": 0, "output": 0})
        velocity_warns = [x for x in w if "velocity warning" in str(x.message).lower()]
        assert len(velocity_warns) == 1

    def test_fires_only_once_not_on_every_call(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.30/min")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
            b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
            b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
        velocity_warns = [x for x in w if "velocity warning" in str(x.message).lower()]
        assert len(velocity_warns) == 1

    def test_on_warn_callback_called_with_correct_args(self) -> None:
        calls: list[tuple[float, float]] = []
        b = make_budget(
            max_velocity="$1.00/min",
            warn_velocity="$0.50/min",
            on_warn=lambda s, lim: calls.append((s, lim)),
        )
        b._record_spend(0.55, "gpt-4o", {"input": 0, "output": 0})
        # Filter for the velocity warn call (window_sum ~= 0.55, limit = 0.50)
        velocity_calls = [(s, lim) for s, lim in calls if lim == pytest.approx(0.50)]
        assert len(velocity_calls) >= 1
        assert velocity_calls[0][0] == pytest.approx(0.55)

    def test_on_warn_not_set_uses_warnings_warn(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.40/min")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b._record_spend(0.45, "gpt-4o", {"input": 0, "output": 0})
        velocity_warns = [x for x in w if "velocity warning" in str(x.message).lower()]
        assert len(velocity_warns) == 1

    def test_warn_fired_flag_set_after_warning(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        assert b._velocity_warn_fired is True

    def test_warn_not_fired_below_threshold(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        assert b._velocity_warn_fired is False

    def test_warn_resets_when_window_rolls_over(self) -> None:
        b = make_budget(max_velocity="$1.00/5s", warn_velocity="$0.50/5s")
        # Fire warning first
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        assert b._velocity_warn_fired is True
        # Manually clear window to simulate roll-over
        b._velocity_window.clear()
        b._prune_velocity_window(time.monotonic())  # triggers reset of warn_fired
        assert b._velocity_warn_fired is False


# ---------------------------------------------------------------------------
# 6. Rolling window / pruning
# ---------------------------------------------------------------------------


class TestRollingWindowPruning:
    def test_old_entries_evicted(self) -> None:
        b = make_budget(max_velocity="$1.00/1s")
        now = 1000.0
        # Add an old entry directly
        b._velocity_window.append((now - 2.0, 0.80))  # 2 seconds old, outside 1s window
        b._prune_velocity_window(now)
        assert len(b._velocity_window) == 0

    def test_recent_entries_kept(self) -> None:
        b = make_budget(max_velocity="$1.00/60s")
        now = 1000.0
        b._velocity_window.append((now - 30.0, 0.30))  # 30s old, inside 60s window
        b._prune_velocity_window(now)
        assert len(b._velocity_window) == 1

    def test_warn_fired_resets_when_window_empties(self) -> None:
        b = make_budget(max_velocity="$1.00/1s", warn_velocity="$0.50/1s")
        b._velocity_warn_fired = True
        b._velocity_window.clear()
        b._prune_velocity_window(time.monotonic())
        assert b._velocity_warn_fired is False

    def test_velocity_window_sum_empty_deque(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        assert b._velocity_window_sum == pytest.approx(0.0)

    def test_velocity_window_sum_with_entries(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._velocity_window.append((time.monotonic(), 0.30))
        b._velocity_window.append((time.monotonic(), 0.20))
        assert b._velocity_window_sum == pytest.approx(0.50)

    def test_zero_cost_appended_but_no_effect_on_sum(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.0, "gpt-4o", {"input": 0, "output": 0})
        # zero-cost entry should be in window but sum stays 0
        assert b._velocity_window_sum == pytest.approx(0.0)
        assert len(b._velocity_window) == 1

    def test_append_velocity_entry_adds_to_window(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._append_velocity_entry(0.25)
        assert len(b._velocity_window) == 1
        assert b._velocity_window[0][1] == pytest.approx(0.25)

    def test_append_velocity_entry_prunes_old_first(self) -> None:
        b = make_budget(max_velocity="$1.00/1s")
        old_time = time.monotonic() - 5.0  # way outside 1s window
        b._velocity_window.append((old_time, 0.50))
        b._append_velocity_entry(0.10)
        # Old entry should be pruned, only new one remains
        assert len(b._velocity_window) == 1
        assert b._velocity_window[0][1] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# 7. _reset_state
# ---------------------------------------------------------------------------


class TestResetStateVelocity:
    def test_velocity_window_cleared(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._velocity_window.append((time.monotonic(), 0.50))
        b._reset_state()
        assert len(b._velocity_window) == 0

    def test_velocity_warn_fired_reset(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        b._velocity_warn_fired = True
        b._reset_state()
        assert b._velocity_warn_fired is False

    def test_reset_state_does_not_change_config(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        b._reset_state()
        assert b._velocity_limit_usd == pytest.approx(1.00)
        assert b._warn_velocity_limit_usd == pytest.approx(0.50)
        assert b._velocity_window_seconds == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# 8. Pipeline ordering
# ---------------------------------------------------------------------------


class TestPipelineOrdering:
    def test_velocity_fires_before_total_limit(self) -> None:
        # Set velocity limit lower than max_usd — velocity should fire first
        b = make_budget(max_usd=10.0, max_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError):
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})

    def test_velocity_error_caught_by_budget_exceeded_error(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(BudgetExceededError):
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})

    def test_only_velocity_fires_when_both_present(self) -> None:
        # velocity < max_usd so velocity fires, not BudgetExceededError from total
        b = make_budget(max_usd=5.00, max_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        exc = None
        try:
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        except SpendVelocityExceededError as e:
            exc = e
        assert exc is not None
        # Total spent (0.60) is well below max_usd (5.00)
        assert b._spent < 5.00


# ---------------------------------------------------------------------------
# 9. Velocity-only (no max_usd)
# ---------------------------------------------------------------------------


class TestVelocityOnlyBudget:
    def test_velocity_only_no_total_cap_fires_velocity_error(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        with pytest.raises(SpendVelocityExceededError):
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})

    def test_velocity_only_under_limit_no_raise(self) -> None:
        b = make_budget(max_velocity="$2.00/hr")
        b._record_spend(1.00, "gpt-4o", {"input": 0, "output": 0})
        # 1.00 < 2.00 → no raise

    def test_velocity_only_max_usd_is_none(self) -> None:
        b = make_budget(max_velocity="$2/hr")
        assert b.max_usd is None


# ---------------------------------------------------------------------------
# 10. Integration with _record_spend
# ---------------------------------------------------------------------------


class TestRecordSpendIntegration:
    def test_record_spend_triggers_velocity_check(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.60, "gpt-4o", {"input": 100, "output": 50})
        with pytest.raises(SpendVelocityExceededError):
            b._record_spend(0.50, "gpt-4o", {"input": 100, "output": 50})

    def test_multiple_calls_accumulate_in_window(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
        b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
        b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
        b._record_spend(0.20, "gpt-4o", {"input": 0, "output": 0})
        # Total = 0.80, limit = 1.00 → no raise
        with pytest.raises(SpendVelocityExceededError):
            b._record_spend(0.25, "gpt-4o", {"input": 0, "output": 0})

    def test_velocity_window_populated_after_record_spend(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.10, "gpt-4o", {"input": 0, "output": 0})
        assert len(b._velocity_window) == 1

    def test_spent_accumulates_even_with_velocity_error(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        try:
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        except SpendVelocityExceededError:
            pass
        # Both costs were recorded to _spent before the check
        assert b._spent == pytest.approx(1.10, rel=1e-3)

    def test_velocity_error_propagates_from_record_spend(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        raised = False
        try:
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
        except SpendVelocityExceededError:
            raised = True
        assert raised


# ---------------------------------------------------------------------------
# 11. Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManagerVelocity:
    @pytest.mark.asyncio
    async def test_async_context_manager_velocity_raises(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        async with b:
            b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})
            with pytest.raises(SpendVelocityExceededError):
                b._record_spend(0.30, "gpt-4o", {"input": 0, "output": 0})

    @pytest.mark.asyncio
    async def test_async_context_manager_no_raise_under_limit(self) -> None:
        b = make_budget(max_velocity="$1.00/min")
        async with b:
            b._record_spend(0.40, "gpt-4o", {"input": 0, "output": 0})
            b._record_spend(0.40, "gpt-4o", {"input": 0, "output": 0})
        # 0.80 < 1.00 → no exception

    @pytest.mark.asyncio
    async def test_async_context_manager_velocity_warn(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            async with b:
                b._record_spend(0.60, "gpt-4o", {"input": 0, "output": 0})
        velocity_warns = [x for x in w if "velocity warning" in str(x.message).lower()]
        assert len(velocity_warns) == 1


# ---------------------------------------------------------------------------
# 12. Edge cases & additional coverage
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_velocity_limit_usd_none_no_check_velocity_limit(self) -> None:
        b = make_budget()
        # No limit set — _check_velocity_limit should be a no-op
        b._check_velocity_limit()  # Should not raise

    def test_velocity_warn_limit_none_no_check_velocity_warn(self) -> None:
        b = make_budget()
        # No warn limit — _check_velocity_warn should be a no-op
        b._check_velocity_warn()  # Should not raise

    def test_prune_velocity_window_no_op_on_empty(self) -> None:
        b = make_budget(max_velocity="$1/min")
        b._prune_velocity_window(time.monotonic())  # Should not raise

    def test_velocity_window_sum_property_on_no_velocity_budget(self) -> None:
        b = make_budget()
        assert b._velocity_window_sum == pytest.approx(0.0)

    def test_warn_velocity_fires_with_exact_threshold_amount(self) -> None:
        # warn fires when window_sum >= warn_limit (inclusive)
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})
        velocity_warns = [x for x in w if "velocity warning" in str(x.message).lower()]
        assert len(velocity_warns) == 1

    def test_velocity_warn_fired_not_double_fired(self) -> None:
        calls: list[tuple[float, float]] = []
        b = make_budget(
            max_velocity="$1.00/min",
            warn_velocity="$0.30/min",
            on_warn=lambda s, lim: calls.append((s, lim)),
        )
        # First call triggers warn at 0.40
        b._record_spend(0.40, "gpt-4o", {"input": 0, "output": 0})
        initial_count = sum(1 for _, lim in calls if lim == pytest.approx(0.30))
        # Second call (still in window, still over threshold)
        b._record_spend(0.10, "gpt-4o", {"input": 0, "output": 0})
        second_count = sum(1 for _, lim in calls if lim == pytest.approx(0.30))
        # Warn should have fired exactly once
        assert initial_count == 1
        assert second_count == 1

    def test_velocity_limit_equal_not_exceeded_no_raise(self) -> None:
        b = make_budget(max_velocity="$0.50/min")
        # Spend exactly 0.50 — window_sum == limit → no raise (condition is strictly >)
        b._record_spend(0.50, "gpt-4o", {"input": 0, "output": 0})

    def test_reset_state_called_by_reset(self) -> None:
        b = make_budget(max_velocity="$1.00/min", warn_velocity="$0.50/min")
        b._velocity_warn_fired = True
        b._velocity_window.append((time.monotonic(), 0.30))
        b.reset()
        assert b._velocity_warn_fired is False
        assert len(b._velocity_window) == 0

    def test_budget_with_all_features(self) -> None:
        b = make_budget(
            max_usd=5.0,
            max_velocity="$1.00/min",
            warn_velocity="$0.70/min",
            warn_only=False,
            loop_guard=True,
        )
        assert b.max_usd == pytest.approx(5.0)
        assert b._velocity_limit_usd == pytest.approx(1.00)
        assert b._warn_velocity_limit_usd == pytest.approx(0.70)
        assert b.loop_guard is True
