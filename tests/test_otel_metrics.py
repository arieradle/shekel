"""Tests for OpenTelemetry metrics integration (ShekelMeter / _OtelMetricsAdapter).

Groups:
  A — No-op safety (OTel absent)
  B — ShekelMeter construction
  C — New base events no-ops
  D — _budget.py emits on_budget_exit
  E — _patch.py token payload
  F — Tier 2 per-call metrics
  G — Tier 1 budget lifecycle metrics (P0)
  H — Tier 1 P1 metrics
  I — Tier 1 P2 metrics
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from shekel._budget import Budget
from shekel.integrations import AdapterRegistry
from shekel.integrations.base import ObservabilityAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meter() -> MagicMock:
    """Return a mock opentelemetry Meter with distinct instruments per call."""
    meter = MagicMock()
    meter.create_counter.side_effect = lambda *a, **kw: MagicMock()
    meter.create_up_down_counter.side_effect = lambda *a, **kw: MagicMock()
    meter.create_histogram.side_effect = lambda *a, **kw: MagicMock()
    return meter


def _make_provider(meter: MagicMock | None = None) -> MagicMock:
    provider = MagicMock()
    provider.get_meter.return_value = meter or _make_meter()
    return provider


# ---------------------------------------------------------------------------
# Group A — No-op safety
# ---------------------------------------------------------------------------


class TestNoOpSafety:
    def test_shekel_meter_importable_without_otel(self) -> None:
        """ShekelMeter can be imported even when opentelemetry.* is missing."""
        # Hide opentelemetry from the import system
        saved: dict[str, object] = {}
        to_hide = [k for k in list(sys.modules) if k.startswith("opentelemetry")]
        for k in to_hide:
            saved[k] = sys.modules.pop(k)

        # Also temporarily block fresh imports by inserting a fake that raises ImportError
        blocker = types.ModuleType("opentelemetry")
        blocker.__spec__ = None  # type: ignore[attr-defined]

        sys.modules["opentelemetry"] = blocker  # type: ignore[assignment]
        sys.modules["opentelemetry.metrics"] = None  # type: ignore[assignment]

        # Remove cached shekel.otel module so it re-evaluates the guard
        shekel_otel_saved = sys.modules.pop("shekel.otel", None)
        otel_metrics_saved = sys.modules.pop("shekel.integrations.otel_metrics", None)

        try:
            import importlib

            import shekel.otel  # noqa: F401

            importlib.reload(shekel.otel)
        except ImportError:
            pytest.fail("ShekelMeter raised ImportError when opentelemetry absent")
        finally:
            # Restore
            for k, v in saved.items():
                sys.modules[k] = v  # type: ignore[assignment]
            sys.modules.pop("opentelemetry", None)
            sys.modules.pop("opentelemetry.metrics", None)
            if shekel_otel_saved is not None:
                sys.modules["shekel.otel"] = shekel_otel_saved
            if otel_metrics_saved is not None:
                sys.modules["shekel.integrations.otel_metrics"] = otel_metrics_saved

    def test_shekel_meter_is_noop_when_otel_absent(self) -> None:
        """When OTel unavailable, ShekelMeter.is_noop is True and budgets work fine."""
        import shekel.otel as otel_mod

        original_flag = otel_mod._OTEL_AVAILABLE  # type: ignore[attr-defined]
        otel_mod._OTEL_AVAILABLE = False  # type: ignore[attr-defined]
        try:
            from shekel.otel import ShekelMeter

            meter = ShekelMeter()
            assert meter.is_noop is True
            # Running a budget should not raise
            b = Budget(max_usd=1.0, name="test")
            with b:
                pass
        finally:
            otel_mod._OTEL_AVAILABLE = original_flag  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Group B — ShekelMeter construction
# ---------------------------------------------------------------------------


class TestShekelMeterConstruction:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def teardown_method(self) -> None:
        AdapterRegistry.clear()

    def test_shekel_meter_accepts_meter_provider(self) -> None:
        from shekel.otel import ShekelMeter

        provider = _make_provider()
        m = ShekelMeter(meter_provider=provider)
        assert m.is_noop is False
        provider.get_meter.assert_called_once()

    def test_shekel_meter_emit_tokens_flag(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter
        from shekel.otel import ShekelMeter

        provider = _make_provider()
        m = ShekelMeter(meter_provider=provider, emit_tokens=True)
        assert m.is_noop is False
        # The adapter should have token counters
        assert isinstance(m._adapter, _OtelMetricsAdapter)
        assert m._adapter._tokens_in is not None
        assert m._adapter._tokens_out is not None

    def test_shekel_meter_uses_global_provider_when_none_given(self) -> None:
        import shekel.otel as otel_mod
        from shekel.otel import ShekelMeter

        provider = _make_provider()
        mock_otel_metrics = MagicMock()
        mock_otel_metrics.get_meter_provider.return_value = provider

        orig = otel_mod._otel_metrics  # type: ignore[attr-defined]
        otel_mod._otel_metrics = mock_otel_metrics  # type: ignore[attr-defined]
        try:
            m = ShekelMeter()
        finally:
            otel_mod._otel_metrics = orig  # type: ignore[attr-defined]

        assert m.is_noop is False
        mock_otel_metrics.get_meter_provider.assert_called_once()
        provider.get_meter.assert_called_once()

    def test_shekel_meter_unregister_removes_adapter(self) -> None:
        from shekel.otel import ShekelMeter

        provider = _make_provider()
        m = ShekelMeter(meter_provider=provider)
        before = len(AdapterRegistry._adapters)
        m.unregister()
        after = len(AdapterRegistry._adapters)
        assert after == before - 1


# ---------------------------------------------------------------------------
# Group C — New base events no-ops
# ---------------------------------------------------------------------------


class TestBaseEventNoOps:
    def test_on_budget_exit_noop_in_base(self) -> None:
        adapter = ObservabilityAdapter()
        adapter.on_budget_exit({})  # must not raise

    def test_on_autocap_noop_in_base(self) -> None:
        adapter = ObservabilityAdapter()
        adapter.on_autocap({})  # must not raise


# ---------------------------------------------------------------------------
# Group D — _budget.py emits on_budget_exit
# ---------------------------------------------------------------------------


class TestBudgetExitEvent:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def teardown_method(self) -> None:
        AdapterRegistry.clear()

    def _capture_exit_events(self) -> list[dict]:  # type: ignore[type-arg]
        captured: list[dict] = []  # type: ignore[type-arg]

        class Capture(ObservabilityAdapter):
            def on_budget_exit(self, data: dict) -> None:  # type: ignore[type-arg, override]
                captured.append(data)

        AdapterRegistry.register(Capture())
        return captured

    def test_budget_exit_event_emitted_on_normal_exit(self) -> None:
        captured = self._capture_exit_events()
        b = Budget(max_usd=1.0, name="test")
        with b:
            pass
        assert len(captured) == 1
        assert captured[0]["status"] == "completed"

    def test_budget_exit_event_emitted_on_exceeded(self) -> None:
        from shekel.exceptions import BudgetExceededError

        captured = self._capture_exit_events()
        b = Budget(max_usd=0.0001, name="test")
        try:
            with b:
                b._record_spend(0.001, "gpt-4o", {"input": 100, "output": 50})
        except BudgetExceededError:
            pass
        assert len(captured) == 1
        assert captured[0]["status"] == "exceeded"

    def test_budget_exit_event_emitted_on_warned(self) -> None:
        captured = self._capture_exit_events()
        b = Budget(max_usd=1.0, warn_at=0.5, name="test")
        with b:
            b._spent = 0.6  # manually trigger warn state
            b._warn_fired = True
        assert len(captured) == 1
        assert captured[0]["status"] == "warned"

    def test_budget_exit_event_includes_duration(self) -> None:
        captured = self._capture_exit_events()
        b = Budget(max_usd=1.0, name="test")
        with b:
            pass
        assert captured[0]["duration_seconds"] >= 0.0

    def test_budget_exit_event_includes_utilization(self) -> None:
        captured = self._capture_exit_events()
        b = Budget(max_usd=1.0, name="test")
        with b:
            b._spent = 0.5
            b._effective_limit = 1.0
        assert captured[0]["utilization"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_budget_exit_event_async(self) -> None:
        captured = self._capture_exit_events()
        b = Budget(max_usd=1.0, name="test")
        async with b:
            pass
        assert len(captured) == 1
        assert captured[0]["status"] == "completed"
        assert captured[0]["duration_seconds"] >= 0.0

    def test_budget_autocap_event_emitted(self) -> None:
        """on_autocap fires when child budget is capped by parent remaining."""
        autocap_events: list[dict] = []  # type: ignore[type-arg]

        class CapCapture(ObservabilityAdapter):
            def on_autocap(self, data: dict) -> None:  # type: ignore[type-arg, override]
                autocap_events.append(data)

        AdapterRegistry.register(CapCapture())

        parent = Budget(max_usd=0.5, name="parent")
        child = Budget(max_usd=2.0, name="child")  # will be capped to 0.5
        with parent:
            with child:
                pass

        assert len(autocap_events) == 1
        assert autocap_events[0]["child_name"] == "child"
        assert autocap_events[0]["parent_name"] == "parent"
        assert autocap_events[0]["original_limit"] == 2.0
        assert autocap_events[0]["effective_limit"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Group E — _patch.py token payload
# ---------------------------------------------------------------------------


class TestPatchTokenPayload:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def teardown_method(self) -> None:
        AdapterRegistry.clear()

    def test_cost_update_event_includes_tokens(self) -> None:
        events: list[dict] = []  # type: ignore[type-arg]

        class Capture(ObservabilityAdapter):
            def on_cost_update(self, data: dict) -> None:  # type: ignore[type-arg, override]
                events.append(data)

        AdapterRegistry.register(Capture())

        from shekel._patch import _record

        b = Budget(max_usd=1.0, name="tok_test")
        with b:
            _record(100, 50, "gpt-4o")

        assert len(events) == 1
        assert "input_tokens" in events[0]
        assert "output_tokens" in events[0]
        assert events[0]["input_tokens"] == 100
        assert events[0]["output_tokens"] == 50


# ---------------------------------------------------------------------------
# Group F — Tier 2 per-call metrics
# ---------------------------------------------------------------------------


class TestTier2PerCallMetrics:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def teardown_method(self) -> None:
        AdapterRegistry.clear()

    def _make_adapter(self, emit_tokens: bool = False) -> tuple[MagicMock, object]:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=emit_tokens)
        return meter, adapter

    def test_llm_cost_usd_emitted_per_call(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)

        data = {
            "model": "gpt-4o",
            "name": "mybudget",
            "full_name": "mybudget",
            "call_cost": 0.05,
            "input_tokens": 100,
            "output_tokens": 50,
        }
        adapter.on_cost_update(data)

        adapter._llm_cost.add.assert_called_once()
        call_args = adapter._llm_cost.add.call_args
        assert call_args[0][0] == pytest.approx(0.05)
        attrs = call_args[0][1]
        assert attrs["gen_ai.system"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        assert attrs["budget_name"] == "mybudget"

    def test_llm_calls_total_incremented(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)

        data = {
            "model": "claude-3-haiku-20240307",
            "name": "b",
            "full_name": "b",
            "call_cost": 0.01,
            "input_tokens": 10,
            "output_tokens": 5,
        }
        adapter.on_cost_update(data)
        adapter._llm_calls.add.assert_called_once_with(
            1,
            {
                "gen_ai.system": "anthropic",
                "gen_ai.request.model": "claude-3-haiku-20240307",
                "budget_name": "b",
            },
        )

    def test_llm_tokens_not_emitted_by_default(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        assert adapter._tokens_in is None
        assert adapter._tokens_out is None

        data = {
            "model": "gpt-4o",
            "name": "b",
            "full_name": "b",
            "call_cost": 0.01,
            "input_tokens": 100,
            "output_tokens": 50,
        }
        adapter.on_cost_update(data)
        # No token counter methods should have been called
        # (they don't exist as MagicMocks on meter since tokens are None)

    def test_llm_tokens_emitted_when_opted_in(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=True)
        assert adapter._tokens_in is not None
        assert adapter._tokens_out is not None

        data = {
            "model": "gpt-4o",
            "name": "b",
            "full_name": "b",
            "call_cost": 0.01,
            "input_tokens": 100,
            "output_tokens": 50,
        }
        adapter.on_cost_update(data)

        adapter._tokens_in.add.assert_called_once()
        adapter._tokens_out.add.assert_called_once()
        assert adapter._tokens_in.add.call_args[0][0] == 100
        assert adapter._tokens_out.add.call_args[0][0] == 50


# ---------------------------------------------------------------------------
# Group G — Tier 1 budget lifecycle metrics (P0)
# ---------------------------------------------------------------------------


class TestTier1P0Metrics:
    def test_budget_exits_total_completed(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)

        data = {
            "budget_name": "wf",
            "budget_full_name": "wf",
            "status": "completed",
            "spent_usd": 0.1,
            "limit_usd": 1.0,
            "utilization": 0.1,
            "duration_seconds": 2.0,
            "calls_made": 3,
            "model_switched": False,
            "from_model": None,
            "to_model": None,
        }
        adapter.on_budget_exit(data)

        adapter._budget_exits.add.assert_called_once()
        call_args = adapter._budget_exits.add.call_args
        assert call_args[0][0] == 1
        assert call_args[0][1]["status"] == "completed"

    def test_budget_exits_total_exceeded(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)

        data = {
            "budget_name": "wf",
            "budget_full_name": "wf",
            "status": "exceeded",
            "spent_usd": 1.5,
            "limit_usd": 1.0,
            "utilization": 1.5,
            "duration_seconds": 5.0,
            "calls_made": 10,
            "model_switched": False,
            "from_model": None,
            "to_model": None,
        }
        adapter.on_budget_exit(data)

        call_args = adapter._budget_exits.add.call_args
        assert call_args[0][1]["status"] == "exceeded"

    def test_budget_cost_usd_updown_incremented(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)

        data = {
            "model": "gpt-4o",
            "name": "mybudget",
            "full_name": "mybudget",
            "call_cost": 0.123,
            "input_tokens": 100,
            "output_tokens": 50,
        }
        adapter.on_cost_update(data)

        adapter._budget_cost.add.assert_called_once()
        call_args = adapter._budget_cost.add.call_args
        assert call_args[0][0] == pytest.approx(0.123)


# ---------------------------------------------------------------------------
# Group H — Tier 1 P1 metrics
# ---------------------------------------------------------------------------


class TestTier1P1Metrics:
    def _make_exit_data(self, **overrides: object) -> dict:  # type: ignore[type-arg]
        base: dict = {  # type: ignore[type-arg]
            "budget_name": "wf",
            "budget_full_name": "wf",
            "status": "completed",
            "spent_usd": 0.75,
            "limit_usd": 1.0,
            "utilization": 0.75,
            "duration_seconds": 3.0,
            "calls_made": 5,
            "model_switched": False,
            "from_model": None,
            "to_model": None,
        }
        base.update(overrides)
        return base

    def test_budget_utilization_histogram_on_exit(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_budget_exit(self._make_exit_data(utilization=0.75))
        adapter._budget_util.record.assert_called_once()
        call_args = adapter._budget_util.record.call_args
        assert call_args[0][0] == pytest.approx(0.75)

    def test_budget_utilization_not_emitted_without_limit(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_budget_exit(self._make_exit_data(utilization=None))
        adapter._budget_util.record.assert_not_called()

    def test_budget_utilization_clamped_to_one(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_budget_exit(self._make_exit_data(utilization=1.8))
        call_args = adapter._budget_util.record.call_args
        assert call_args[0][0] == pytest.approx(1.0)

    def test_budget_fallbacks_total_emitted(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_budget_exit(
            self._make_exit_data(model_switched=True, from_model="gpt-4o", to_model="gpt-4o-mini")
        )
        adapter._budget_fallbacks.add.assert_called_once()
        call_args = adapter._budget_fallbacks.add.call_args
        assert call_args[0][1]["from_model"] == "gpt-4o"
        assert call_args[0][1]["to_model"] == "gpt-4o-mini"

    def test_budget_fallbacks_total_not_emitted_without_switch(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_budget_exit(self._make_exit_data(model_switched=False))
        adapter._budget_fallbacks.add.assert_not_called()


# ---------------------------------------------------------------------------
# Group I — Tier 1 P2 metrics
# ---------------------------------------------------------------------------


class TestTier1P2Metrics:
    def _make_exit_data(self, **overrides: object) -> dict:  # type: ignore[type-arg]
        base: dict = {  # type: ignore[type-arg]
            "budget_name": "wf",
            "budget_full_name": "wf",
            "status": "completed",
            "spent_usd": 0.5,
            "limit_usd": 1.0,
            "utilization": 0.5,
            "duration_seconds": 2.5,
            "calls_made": 5,
            "model_switched": False,
            "from_model": None,
            "to_model": None,
        }
        base.update(overrides)
        return base

    def test_budget_spend_rate_histogram(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_budget_exit(self._make_exit_data(duration_seconds=2.5, spent_usd=0.50))
        adapter._budget_rate.record.assert_called_once()
        call_args = adapter._budget_rate.record.call_args
        assert call_args[0][0] == pytest.approx(0.20)  # 0.50 / 2.5

    def test_budget_spend_rate_zero_duration_safe(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        # Should not raise ZeroDivisionError
        adapter.on_budget_exit(self._make_exit_data(duration_seconds=0.0, spent_usd=0.5))
        call_args = adapter._budget_rate.record.call_args
        assert call_args[0][0] == pytest.approx(0.0)

    def test_budget_autocaps_total_emitted(self) -> None:
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        adapter.on_autocap(
            {
                "child_name": "child",
                "parent_name": "parent",
                "original_limit": 2.0,
                "effective_limit": 0.5,
            }
        )
        adapter._budget_autocaps.add.assert_called_once()
        call_args = adapter._budget_autocaps.add.call_args
        assert call_args[0][1]["child_name"] == "child"
        assert call_args[0][1]["parent_name"] == "parent"

    def test_budget_autocaps_total_not_emitted_when_no_cap(self) -> None:
        """No on_autocap event means no counter increment."""
        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        meter = _make_meter()
        adapter = _OtelMetricsAdapter(meter, emit_tokens=False)
        # Don't call on_autocap at all
        adapter._budget_autocaps.add.assert_not_called()
