"""Tests for temporal (rolling-window) budget enforcement.

Domain: temporal budgets — window-based spend tracking and enforcement.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Group A — String parser
# ---------------------------------------------------------------------------


def test_parse_dollar_per_hr():
    from shekel._temporal import _parse_spec

    assert _parse_spec("$5/hr") == (5.0, 3600.0)


def test_parse_dollar_per_1hr():
    from shekel._temporal import _parse_spec

    assert _parse_spec("$5 per 1hr") == (5.0, 3600.0)


def test_parse_dollar_per_30min():
    from shekel._temporal import _parse_spec

    assert _parse_spec("$10/30min") == (10.0, 1800.0)


def test_parse_dollar_per_60s():
    from shekel._temporal import _parse_spec

    assert _parse_spec("$1/60s") == (1.0, 60.0)


def test_parse_rejects_day():
    from shekel._temporal import _parse_spec

    with pytest.raises(ValueError):
        _parse_spec("$5/day")


def test_parse_rejects_month():
    from shekel._temporal import _parse_spec

    with pytest.raises(ValueError):
        _parse_spec("$5/month")


def test_parse_rejects_week():
    from shekel._temporal import _parse_spec

    with pytest.raises(ValueError):
        _parse_spec("$10/week")


def test_parse_rejects_garbage():
    from shekel._temporal import _parse_spec

    with pytest.raises(ValueError):
        _parse_spec("hello")


def test_parse_rejects_unknown_unit():
    from shekel._temporal import _parse_spec

    # Non-calendar, non-recognized unit hits line 37
    with pytest.raises(ValueError, match="Unknown time unit"):
        _parse_spec("$5/xyz")


def test_parse_rejects_zero_amount():
    from shekel._temporal import _parse_spec

    with pytest.raises(ValueError):
        _parse_spec("$0/hr")


# ---------------------------------------------------------------------------
# Group B — budget() factory function
# ---------------------------------------------------------------------------


def test_budget_factory_string_returns_temporal():
    from shekel import budget
    from shekel._temporal import TemporalBudget

    b = budget("$5/hr", name="x")
    assert isinstance(b, TemporalBudget)


def test_budget_factory_kwargs_returns_budget():
    from shekel import budget
    from shekel._budget import Budget
    from shekel._temporal import TemporalBudget

    b = budget(max_usd=5.0)
    assert isinstance(b, Budget)
    assert not isinstance(b, TemporalBudget)


def test_budget_factory_temporal_kwargs_returns_temporal():
    from shekel import budget
    from shekel._temporal import TemporalBudget

    b = budget(max_usd=5.0, window_seconds=3600, name="x")
    assert isinstance(b, TemporalBudget)


def test_budget_factory_string_requires_name():
    from shekel import budget

    with pytest.raises(ValueError):
        budget("$5/hr")


def test_budget_factory_window_seconds_requires_name():
    from shekel import budget

    # window_seconds without name= hits __init__.py:43
    with pytest.raises(ValueError, match="name"):
        budget(max_usd=5.0, window_seconds=3600)


# ---------------------------------------------------------------------------
# Group C — BudgetExceededError enrichment
# ---------------------------------------------------------------------------


def test_budget_exceeded_error_has_retry_after():
    from shekel.exceptions import BudgetExceededError

    err = BudgetExceededError(spent=6.0, limit=5.0, retry_after=1800.0)
    assert err.retry_after == 1800.0


def test_budget_exceeded_error_has_window_spent():
    from shekel.exceptions import BudgetExceededError

    err = BudgetExceededError(spent=6.0, limit=5.0, retry_after=1800.0, window_spent=6.0)
    assert err.window_spent == 6.0


def test_budget_exceeded_error_retry_after_defaults_none():
    from shekel.exceptions import BudgetExceededError

    err = BudgetExceededError(spent=6.0, limit=5.0)
    assert err.retry_after is None


# ---------------------------------------------------------------------------
# Group D — InMemoryBackend
# ---------------------------------------------------------------------------


def test_in_memory_backend_get_state_fresh():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    assert backend.get_state("new_key") == (0.0, None)


def test_in_memory_backend_check_and_add_within_limit():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    result = backend.check_and_add("budget1", 2.0, 5.0, 3600.0)
    assert result is True
    spent, window_start = backend.get_state("budget1")
    assert spent == 2.0
    assert window_start is not None


def test_in_memory_backend_check_and_add_exceeds_limit():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    result = backend.check_and_add("budget1", 6.0, 5.0, 3600.0)
    assert result is False
    # State should remain unchanged (0.0, None) since we never accepted it
    spent, window_start = backend.get_state("budget1")
    assert spent == 0.0
    assert window_start is None


def test_in_memory_backend_reset_clears_state():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    backend.check_and_add("budget1", 2.0, 5.0, 3600.0)
    backend.reset("budget1")
    assert backend.get_state("budget1") == (0.0, None)


def test_in_memory_backend_window_start_set_on_first_add():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    backend.check_and_add("budget1", 1.0, 5.0, 3600.0)
    _, window_start = backend.get_state("budget1")
    assert window_start is not None


def test_in_memory_backend_window_expires_resets():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    t0 = 1000.0

    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("budget1", 4.0, 5.0, 3600.0)

    # Advance time past window
    with patch("time.monotonic", return_value=t0 + 3601.0):
        result = backend.check_and_add("budget1", 4.0, 5.0, 3600.0)
        assert result is True  # fresh window, 4.0 < 5.0 so should succeed
        spent, _ = backend.get_state("budget1")
        assert spent == 4.0  # fresh window


# ---------------------------------------------------------------------------
# Group E — TemporalBudget basic behavior
# ---------------------------------------------------------------------------


def test_temporal_budget_requires_name():
    from shekel._temporal import TemporalBudget

    # Omitting name= is a user error; Python may raise TypeError (missing arg)
    # or ValueError (empty string). Both indicate the required name is absent.
    with pytest.raises((ValueError, TypeError)):
        TemporalBudget(max_usd=5.0, window_seconds=3600)


def test_temporal_budget_empty_name_raises():
    from shekel._temporal import TemporalBudget

    # Empty string name hits line 108 (ValueError branch)
    with pytest.raises(ValueError, match="name"):
        TemporalBudget(max_usd=5.0, window_seconds=3600, name="")


def test_temporal_budget_window_resets_after_expiry():
    from shekel._temporal import InMemoryBackend, TemporalBudget

    backend = InMemoryBackend()
    TemporalBudget(max_usd=5.0, window_seconds=3600, name="test", backend=backend)
    t0 = 1000.0

    # Fill the window
    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("test", 4.5, 5.0, 3600.0)

    # After window expires, should be able to spend again
    with patch("time.monotonic", return_value=t0 + 3601.0):
        result = backend.check_and_add("test", 3.0, 5.0, 3600.0)
        assert result is True


def test_temporal_budget_retry_after_in_error():
    from shekel._temporal import InMemoryBackend, TemporalBudget
    from shekel.exceptions import BudgetExceededError

    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="test_retry", backend=backend)
    t0 = 1000.0

    with patch("time.monotonic", return_value=t0):
        # Set up state: window started, nearly full
        backend.check_and_add("test_retry", 4.5, 5.0, 3600.0)

    with patch("time.monotonic", return_value=t0 + 100.0):
        with pytest.raises(BudgetExceededError) as exc_info:
            tb._record_spend(1.0, "test-model", {"input": 100, "output": 100})
        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after > 0


def test_temporal_budget_window_spent_in_error():
    from shekel._temporal import InMemoryBackend, TemporalBudget
    from shekel.exceptions import BudgetExceededError

    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="test_ws", backend=backend)
    t0 = 1000.0

    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("test_ws", 4.5, 5.0, 3600.0)

    with patch("time.monotonic", return_value=t0 + 100.0):
        with pytest.raises(BudgetExceededError) as exc_info:
            tb._record_spend(1.0, "test-model", {"input": 100, "output": 100})
        assert exc_info.value.window_spent == 4.5


def test_record_spend_window_expired_mid_context():
    from shekel._temporal import InMemoryBackend, TemporalBudget
    from shekel.exceptions import BudgetExceededError

    # Window expires between __enter__ and _record_spend (lines 158-159)
    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="mid_expiry", backend=backend)
    t0 = 1000.0

    # Seed backend with state (window started at t0)
    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("mid_expiry", 3.0, 5.0, 3600.0)

    # At t0+3601 window has expired; attempt to add more than limit → raises
    with patch("time.monotonic", return_value=t0 + 3601.0):
        with pytest.raises(BudgetExceededError) as exc_info:
            tb._record_spend(6.0, "test-model", {"input": 10, "output": 10})
        # window_spent should reflect fresh window (0.0) since window expired
        assert exc_info.value.window_spent == 0.0
        assert exc_info.value.retry_after is None


def test_record_spend_within_limit_calls_super():
    from shekel._temporal import InMemoryBackend, TemporalBudget

    # Spend accepted → super()._record_spend() is called (line 176)
    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="within_limit", backend=backend)

    with patch("shekel._budget.Budget._record_spend") as mock_super:
        tb._record_spend(1.0, "test-model", {"input": 10, "output": 10})
        mock_super.assert_called_once_with(1.0, "test-model", {"input": 10, "output": 10})


def test_lazy_window_reset_emit_guard():
    from shekel._temporal import InMemoryBackend, TemporalBudget

    # emit_event raises → except Exception: pass guard (lines 145-146)
    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="guard_test", backend=backend)
    t0 = 1000.0

    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("guard_test", 2.0, 5.0, 3600.0)

    with patch(
        "shekel.integrations.registry.AdapterRegistry.emit_event",
        side_effect=RuntimeError("boom"),
    ):
        with patch("time.monotonic", return_value=t0 + 3601.0):
            # Should not raise despite emit_event failing
            tb._lazy_window_reset()


# ---------------------------------------------------------------------------
# Group F — Temporal nesting guard
# ---------------------------------------------------------------------------


def test_temporal_in_temporal_raises_immediately():
    from shekel._temporal import TemporalBudget

    outer = TemporalBudget(max_usd=10.0, window_seconds=3600, name="outer")
    inner = TemporalBudget(max_usd=5.0, window_seconds=3600, name="inner")

    outer.__enter__()
    try:
        with pytest.raises(ValueError, match="[Tt]emporal"):
            inner.__enter__()
    finally:
        outer.__exit__(None, None, None)


def test_temporal_in_regular_in_temporal_raises():
    from shekel._budget import Budget
    from shekel._temporal import TemporalBudget

    outer = TemporalBudget(max_usd=10.0, window_seconds=3600, name="outer")
    middle = Budget(max_usd=8.0, name="middle")
    inner = TemporalBudget(max_usd=5.0, window_seconds=3600, name="inner")

    outer.__enter__()
    try:
        middle.__enter__()
        try:
            with pytest.raises(ValueError, match="[Tt]emporal"):
                inner.__enter__()
        finally:
            middle.__exit__(None, None, None)
    finally:
        outer.__exit__(None, None, None)


def test_temporal_in_regular_ok():
    from shekel._budget import Budget
    from shekel._temporal import TemporalBudget

    outer = Budget(max_usd=10.0, name="outer")
    inner = TemporalBudget(max_usd=5.0, window_seconds=3600, name="inner")

    outer.__enter__()
    try:
        # Should NOT raise
        inner.__enter__()
        inner.__exit__(None, None, None)
    finally:
        outer.__exit__(None, None, None)


def test_regular_in_temporal_ok():
    from shekel._budget import Budget
    from shekel._temporal import TemporalBudget

    outer = TemporalBudget(max_usd=10.0, window_seconds=3600, name="outer")
    inner = Budget(max_usd=5.0, name="inner")

    outer.__enter__()
    try:
        # Should NOT raise
        inner.__enter__()
        inner.__exit__(None, None, None)
    finally:
        outer.__exit__(None, None, None)


def test_deeply_nested_temporal_detected():
    from shekel._budget import Budget
    from shekel._temporal import TemporalBudget

    l1 = TemporalBudget(max_usd=10.0, window_seconds=3600, name="l1")
    l2 = Budget(max_usd=9.0, name="l2")
    l3 = Budget(max_usd=8.0, name="l3")
    l4 = Budget(max_usd=7.0, name="l4")
    l5 = TemporalBudget(max_usd=5.0, window_seconds=3600, name="l5")

    l1.__enter__()
    try:
        l2.__enter__()
        try:
            l3.__enter__()
            try:
                l4.__enter__()
                try:
                    with pytest.raises(ValueError, match="[Tt]emporal"):
                        l5.__enter__()
                finally:
                    l4.__exit__(None, None, None)
            finally:
                l3.__exit__(None, None, None)
        finally:
            l2.__exit__(None, None, None)
    finally:
        l1.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Group G — on_window_reset adapter event
# ---------------------------------------------------------------------------


def test_on_window_reset_noop_in_base():
    from shekel.integrations.base import ObservabilityAdapter

    adapter = ObservabilityAdapter()
    # Should not raise
    adapter.on_window_reset({})


def test_window_reset_event_emitted():
    from shekel._temporal import InMemoryBackend, TemporalBudget
    from shekel.integrations import AdapterRegistry

    AdapterRegistry.clear()
    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="test_emit", backend=backend)

    t0 = 1000.0
    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("test_emit", 2.0, 5.0, 3600.0)

    with patch.object(AdapterRegistry, "emit_event") as mock_emit:
        with patch("time.monotonic", return_value=t0 + 3601.0):
            tb.__enter__()
            tb.__exit__(None, None, None)

        event_calls = [c for c in mock_emit.call_args_list if c[0][0] == "on_window_reset"]
        assert len(event_calls) >= 1


def test_window_reset_event_payload():
    from shekel._temporal import InMemoryBackend, TemporalBudget
    from shekel.integrations import AdapterRegistry

    AdapterRegistry.clear()
    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="test_payload", backend=backend)

    t0 = 1000.0
    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("test_payload", 2.0, 5.0, 3600.0)

    with patch.object(AdapterRegistry, "emit_event") as mock_emit:
        with patch("time.monotonic", return_value=t0 + 3601.0):
            tb.__enter__()
            tb.__exit__(None, None, None)

        reset_calls = [c for c in mock_emit.call_args_list if c[0][0] == "on_window_reset"]
        assert reset_calls
        payload = reset_calls[0][0][1]
        assert "budget_name" in payload
        assert "window_seconds" in payload
        assert "previous_spent" in payload
        assert payload["budget_name"] == "test_payload"
        assert payload["window_seconds"] == 3600.0


def test_async_aenter_aexit():
    from shekel._temporal import TemporalBudget

    # Covers lines 184-186 (__aenter__ / __aexit__)
    async def _run():
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="async_test")
        async with tb:
            pass

    asyncio.run(_run())


def test_window_reset_not_emitted_fresh_window():
    from shekel._temporal import InMemoryBackend, TemporalBudget
    from shekel.integrations import AdapterRegistry

    AdapterRegistry.clear()
    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="fresh_budget", backend=backend)

    with patch.object(AdapterRegistry, "emit_event") as mock_emit:
        tb.__enter__()
        tb.__exit__(None, None, None)

        reset_calls = [c for c in mock_emit.call_args_list if c[0][0] == "on_window_reset"]
        assert len(reset_calls) == 0


# ---------------------------------------------------------------------------
# Group H — OTel window_resets_total counter
# ---------------------------------------------------------------------------


def test_otel_window_resets_counter_incremented():
    from shekel.integrations.otel_metrics import _OtelMetricsAdapter

    mock_meter = MagicMock()
    mock_meter.create_counter.return_value = MagicMock()
    mock_meter.create_up_down_counter.return_value = MagicMock()
    mock_meter.create_histogram.return_value = MagicMock()

    # Make the window_resets_total counter trackable
    window_resets_counter = MagicMock()

    def create_counter_side_effect(name, **kwargs):
        if name == "shekel.budget.window_resets_total":
            return window_resets_counter
        return MagicMock()

    mock_meter.create_counter.side_effect = create_counter_side_effect

    adapter = _OtelMetricsAdapter(mock_meter)
    adapter.on_window_reset({"budget_name": "test"})

    window_resets_counter.add.assert_called_once_with(1, {"budget_name": "test"})


def test_otel_window_resets_emit_guard():
    from shekel.integrations.otel_metrics import _OtelMetricsAdapter

    # Counter raises → except Exception: pass guard (lines 164-165)
    mock_meter = MagicMock()
    failing_counter = MagicMock()
    failing_counter.add.side_effect = RuntimeError("boom")
    mock_meter.create_counter.return_value = failing_counter
    mock_meter.create_up_down_counter.return_value = MagicMock()
    mock_meter.create_histogram.return_value = MagicMock()

    adapter = _OtelMetricsAdapter(mock_meter)
    # Should not raise
    adapter.on_window_reset({"budget_name": "test"})
