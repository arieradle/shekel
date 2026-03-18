"""Integration tests for temporal (rolling-window) budget enforcement.

These tests exercise TemporalBudget end-to-end through the full shekel stack:
_record() → budget enforcement → adapter events → error enrichment.

No real API calls are made — LLM costs are simulated via _record()/_record_spend().
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from shekel import budget
from shekel._budget import Budget
from shekel._temporal import InMemoryBackend, TemporalBudget, _parse_spec
from shekel.exceptions import BudgetExceededError
from shekel.integrations import AdapterRegistry, ObservabilityAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EventCollector(ObservabilityAdapter):
    """Collects all adapter events for assertion."""

    def __init__(self) -> None:
        self.cost_updates: list[dict] = []
        self.budget_exits: list[dict] = []
        self.window_resets: list[dict] = []
        self.budget_exceeded: list[dict] = []
        self.autocaps: list[dict] = []

    def on_cost_update(self, data: dict) -> None:
        self.cost_updates.append(data.copy())

    def on_budget_exit(self, data: dict) -> None:
        self.budget_exits.append(data.copy())

    def on_window_reset(self, data: dict) -> None:
        self.window_resets.append(data.copy())

    def on_budget_exceeded(self, data: dict) -> None:
        self.budget_exceeded.append(data.copy())

    def on_autocap(self, data: dict) -> None:
        self.autocaps.append(data.copy())


def record(input_tokens: int = 100, output_tokens: int = 50, model: str = "gpt-4o-mini") -> None:
    """Simulate an LLM call by directly invoking _record."""
    from shekel._patch import _record

    _record(input_tokens=input_tokens, output_tokens=output_tokens, model=model)


# ---------------------------------------------------------------------------
# Group A — end-to-end cost recording inside TemporalBudget
# ---------------------------------------------------------------------------


class TestTemporalBudgetCostRecording:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_cost_recorded_within_window(self) -> None:
        """LLM cost is tracked and spend accumulates in backend."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="recording", backend=backend)

        with tb:
            record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        state = backend.get_state("recording")
        assert state.get("usd", 0.0) > 0

    def test_spend_accumulates_across_entries(self) -> None:
        """Window spend accumulates across multiple context entries."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="accum", backend=backend)

        with tb:
            record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        spent_after_first = backend.get_state("accum").get("usd", 0.0)

        with tb:
            record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        spent_after_second = backend.get_state("accum").get("usd", 0.0)
        assert spent_after_second > spent_after_first

    def test_budget_spent_property_matches_cost(self) -> None:
        """Budget.spent reflects cost of calls made inside the context."""
        tb = budget("$5/hr", name="spent_prop")

        with tb as b:
            record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        assert b.spent > 0

    def test_window_limit_raises_budget_exceeded_error(self) -> None:
        """Exceeding the window limit raises BudgetExceededError."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=0.001, window_seconds=3600, name="tiny", backend=backend)

        with pytest.raises(BudgetExceededError):
            with tb:
                record(input_tokens=10000, output_tokens=5000, model="gpt-4o")

    def test_error_has_retry_after(self) -> None:
        """BudgetExceededError from TemporalBudget includes retry_after."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=0.001, window_seconds=3600, name="retry", backend=backend)

        # Pre-fill window so retry_after is meaningful
        t0 = 1000.0
        with patch("time.monotonic", return_value=t0):
            backend.check_and_add("retry", {"usd": 0.0009}, {"usd": 0.001}, {"usd": 3600.0})

        with patch("time.monotonic", return_value=t0 + 100.0):
            with pytest.raises(BudgetExceededError) as exc_info:
                with tb:
                    tb._record_spend(0.0005, "gpt-4o-mini", {"input": 100, "output": 50})

        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after > 0

    def test_error_has_window_spent(self) -> None:
        """BudgetExceededError includes window_spent showing current window total."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=0.001, window_seconds=3600, name="ws_err", backend=backend)

        t0 = 1000.0
        with patch("time.monotonic", return_value=t0):
            backend.check_and_add("ws_err", {"usd": 0.0009}, {"usd": 0.001}, {"usd": 3600.0})

        with patch("time.monotonic", return_value=t0 + 100.0):
            with pytest.raises(BudgetExceededError) as exc_info:
                tb._record_spend(0.0005, "gpt-4o-mini", {"input": 100, "output": 50})

        assert exc_info.value.window_spent == pytest.approx(0.0009, abs=1e-6)

    def test_regular_budget_error_has_no_retry_after(self) -> None:
        """BudgetExceededError from regular Budget has retry_after=None."""
        with pytest.raises(BudgetExceededError) as exc_info:
            with budget(max_usd=0.001, name="regular"):
                record(input_tokens=10000, output_tokens=5000, model="gpt-4o")

        assert exc_info.value.retry_after is None
        assert exc_info.value.window_spent is None


# ---------------------------------------------------------------------------
# Group B — rolling window reset behaviour
# ---------------------------------------------------------------------------


class TestRollingWindowReset:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_window_resets_after_expiry(self) -> None:
        """After window expires, spend resets and new calls are accepted."""
        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=0.001, window_seconds=3600, name="reset", backend=backend)
        t0 = 1000.0

        # Fill the window to the brim
        with patch("time.monotonic", return_value=t0):
            backend.check_and_add("reset", {"usd": 0.0009}, {"usd": 0.001}, {"usd": 3600.0})

        # After window expires, the next entry starts fresh
        with patch("shekel._temporal.time.monotonic", return_value=t0 + 3601.0):
            with patch("shekel._budget.time.monotonic", return_value=t0 + 3601.0):
                # Should not raise even though the old window was near limit
                with tb:
                    pass  # no LLM call, just test entry succeeds

    def test_window_reset_emits_adapter_event(self) -> None:
        """on_window_reset event is emitted when window expires at entry."""
        collector = EventCollector()
        AdapterRegistry.register(collector)

        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="evt_reset", backend=backend)
        t0 = 1000.0

        with patch("time.monotonic", return_value=t0):
            backend.check_and_add("evt_reset", {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})

        with patch("time.monotonic", return_value=t0 + 3601.0):
            with tb:
                pass

        assert len(collector.window_resets) == 1
        evt = collector.window_resets[0]
        assert evt["budget_name"] == "evt_reset"
        assert evt["window_seconds"] == 3600.0
        assert evt["previous_spent"] == pytest.approx(2.0)

    def test_no_window_reset_event_on_fresh_budget(self) -> None:
        """on_window_reset is NOT emitted on first use (no previous window)."""
        collector = EventCollector()
        AdapterRegistry.register(collector)

        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="fresh")
        with tb:
            pass

        assert len(collector.window_resets) == 0

    def test_window_resets_allow_spend_again(self) -> None:
        """After window reset, spend is accepted from zero."""
        backend = InMemoryBackend()
        t0 = 1000.0

        with patch("time.monotonic", return_value=t0):
            allowed, _ = backend.check_and_add(
                "reuse", {"usd": 0.001}, {"usd": 0.001}, {"usd": 3600.0}
            )
            assert allowed is True

        # New window — same amount should be accepted again
        with patch("time.monotonic", return_value=t0 + 3601.0):
            allowed2, _ = backend.check_and_add(
                "reuse", {"usd": 0.001}, {"usd": 0.001}, {"usd": 3600.0}
            )
            assert allowed2 is True
            state = backend.get_state("reuse")
            assert state["usd"] == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# Group C — adapter event integration
# ---------------------------------------------------------------------------


class TestAdapterEventIntegration:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_on_cost_update_emitted_inside_temporal_budget(self) -> None:
        """on_cost_update fires for each LLM call inside TemporalBudget."""
        collector = EventCollector()
        AdapterRegistry.register(collector)

        with budget("$5/hr", name="evt_cost"):
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            record(input_tokens=200, output_tokens=100, model="gpt-4o-mini")

        assert len(collector.cost_updates) == 2

    def test_on_budget_exit_emitted_on_context_exit(self) -> None:
        """on_budget_exit fires when TemporalBudget context exits."""
        collector = EventCollector()
        AdapterRegistry.register(collector)

        with budget("$5/hr", name="exit_evt"):
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert len(collector.budget_exits) == 1
        evt = collector.budget_exits[0]
        assert evt["budget_name"] == "exit_evt"
        assert evt["status"] == "completed"
        assert evt["spent_usd"] > 0

    def test_on_budget_exit_fires_even_on_window_exceeded(self) -> None:
        """on_budget_exit still fires when TemporalBudget window limit is hit.

        Note: status is "completed" here because TemporalBudget raises before
        super()._record_spend() updates self._spent — the base budget never
        sees a spend that exceeds its _effective_limit. The window-level
        enforcement is handled by the TemporalBudget layer, not the base layer.
        """
        collector = EventCollector()
        AdapterRegistry.register(collector)

        tb = budget("$0.001/hr", name="exceed_evt")
        try:
            with tb:
                record(input_tokens=10000, output_tokens=5000, model="gpt-4o")
        except BudgetExceededError:
            pass  # expected — we intentionally exceed the budget to test the event

        # Budget exit should still fire even on exception
        exit_evts = [e for e in collector.budget_exits if e.get("budget_name") == "exceed_evt"]
        assert len(exit_evts) >= 1
        # status is "completed" — base budget's _spent wasn't updated by the blocked call
        assert exit_evts[0]["status"] in ("completed", "exceeded")

    def test_adapter_errors_do_not_break_temporal_enforcement(self) -> None:
        """A broken adapter must not prevent TemporalBudget from raising."""

        class BrokenAdapter(ObservabilityAdapter):
            def on_cost_update(self, data: dict) -> None:
                raise RuntimeError("adapter broken")

        AdapterRegistry.register(BrokenAdapter())

        with pytest.raises(BudgetExceededError):
            with budget("$0.001/hr", name="broken_adapt"):
                record(input_tokens=10000, output_tokens=5000, model="gpt-4o")

    def test_multiple_adapters_all_receive_window_reset(self) -> None:
        """All registered adapters receive on_window_reset events."""
        c1, c2 = EventCollector(), EventCollector()
        AdapterRegistry.register(c1)
        AdapterRegistry.register(c2)

        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="multi_adapt", backend=backend)
        t0 = 1000.0

        with patch("time.monotonic", return_value=t0):
            backend.check_and_add("multi_adapt", {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})

        with patch("time.monotonic", return_value=t0 + 3601.0):
            with tb:
                pass

        assert len(c1.window_resets) == 1
        assert len(c2.window_resets) == 1


# ---------------------------------------------------------------------------
# Group D — nesting with regular budgets
# ---------------------------------------------------------------------------


class TestNestingIntegration:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_temporal_inside_regular_budget_works(self) -> None:
        """TemporalBudget nested inside regular Budget enforces both limits."""
        with budget(max_usd=10.0, name="outer") as outer:
            with budget("$5/hr", name="inner") as inner:
                record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        assert outer.spent > 0
        assert inner.spent > 0
        assert outer.spent == pytest.approx(inner.spent, rel=1e-6)

    def test_regular_budget_inside_temporal_works(self) -> None:
        """Regular Budget nested inside TemporalBudget enforces both limits."""
        with budget("$5/hr", name="temporal_outer") as outer:
            with budget(max_usd=2.0, name="regular_inner") as inner:
                record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        assert inner.spent > 0
        assert outer.spent == pytest.approx(inner.spent, rel=1e-6)

    def test_parent_regular_budget_autocaps_temporal_child(self) -> None:
        """Regular parent's remaining balance auto-caps temporal child's limit."""
        collector = EventCollector()
        AdapterRegistry.register(collector)

        with budget(max_usd=1.0, name="parent") as parent:
            parent._spent = 0.8  # simulate $0.80 already spent — $0.20 remaining

            tb = budget("$5/hr", name="capped_child")
            with tb as child:
                # Child requested $5/hr but parent only has $0.20 left
                assert child.limit is not None
                assert child.limit <= 0.20 + 1e-9

        assert len(collector.autocaps) >= 1

    def test_temporal_inside_temporal_raises(self) -> None:
        """TemporalBudget nested directly inside TemporalBudget raises ValueError."""
        outer = budget("$10/hr", name="t_outer")
        inner = budget("$5/hr", name="t_inner")

        with outer:
            with pytest.raises(ValueError, match="[Tt]emporal"):
                with inner:
                    pass

    def test_deeply_nested_temporal_detected(self) -> None:
        """Temporal-in-temporal guard fires even through 3 levels of regular budgets."""
        outer = budget("$10/hr", name="deep_outer")
        mid1 = budget(max_usd=9.0, name="m1")
        mid2 = budget(max_usd=8.0, name="m2")
        mid3 = budget(max_usd=7.0, name="m3")
        inner = budget("$5/hr", name="deep_inner")

        outer.__enter__()
        try:
            mid1.__enter__()
            try:
                mid2.__enter__()
                try:
                    mid3.__enter__()
                    try:
                        with pytest.raises(ValueError, match="[Tt]emporal"):
                            inner.__enter__()
                    finally:
                        mid3.__exit__(None, None, None)
                finally:
                    mid2.__exit__(None, None, None)
            finally:
                mid1.__exit__(None, None, None)
        finally:
            outer.__exit__(None, None, None)

    def test_spend_propagates_to_regular_parent(self) -> None:
        """Spend inside TemporalBudget propagates up to enclosing regular Budget."""
        with budget(max_usd=10.0, name="reg_parent") as parent:
            with budget("$5/hr", name="temp_child") as child:
                record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        assert parent.spent == pytest.approx(child.spent, rel=1e-6)
        assert parent.spent > 0


# ---------------------------------------------------------------------------
# Group E — async context manager
# ---------------------------------------------------------------------------


class TestAsyncTemporalBudget:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_async_within_window_passes(self) -> None:
        async def _run():
            tb = budget("$5/hr", name="async_pass")
            async with tb as b:
                record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            return b.spent

        spent = asyncio.run(_run())
        assert spent > 0

    def test_async_exceeds_window_raises(self) -> None:
        async def _run():
            tb = budget("$0.001/hr", name="async_fail")
            async with tb:
                record(input_tokens=10000, output_tokens=5000, model="gpt-4o")

        with pytest.raises(BudgetExceededError):
            asyncio.run(_run())

    def test_async_error_has_retry_after(self) -> None:
        async def _run():
            backend = InMemoryBackend()
            tb = TemporalBudget(
                max_usd=0.001, window_seconds=3600, name="async_retry", backend=backend
            )
            t0 = 1000.0
            with patch("time.monotonic", return_value=t0):
                backend.check_and_add(
                    "async_retry", {"usd": 0.0009}, {"usd": 0.001}, {"usd": 3600.0}
                )

            with patch("time.monotonic", return_value=t0 + 100.0):
                async with tb:
                    tb._record_spend(0.0005, "gpt-4o-mini", {"input": 10, "output": 10})

        with pytest.raises(BudgetExceededError) as exc_info:
            asyncio.run(_run())

        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after > 0

    def test_async_window_reset_event_emitted(self) -> None:
        async def _run():
            collector = EventCollector()
            AdapterRegistry.register(collector)

            backend = InMemoryBackend()
            tb = TemporalBudget(
                max_usd=5.0, window_seconds=3600, name="async_reset", backend=backend
            )
            t0 = 1000.0
            with patch("time.monotonic", return_value=t0):
                backend.check_and_add("async_reset", {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})

            with patch("time.monotonic", return_value=t0 + 3601.0):
                async with tb:
                    pass

            return collector.window_resets

        events = asyncio.run(_run())
        assert len(events) == 1
        assert events[0]["budget_name"] == "async_reset"

    def test_concurrent_async_budgets_isolated(self) -> None:
        """Concurrent async tasks have isolated TemporalBudget contexts."""

        async def _task(name: str, tokens: int) -> float:
            tb = budget("$5/hr", name=name)
            async with tb as b:
                record(input_tokens=tokens, output_tokens=tokens // 2, model="gpt-4o-mini")
            return b.spent

        async def _run():
            results = await asyncio.gather(
                _task("concurrent_a", 100),
                _task("concurrent_b", 200),
                _task("concurrent_c", 300),
            )
            return results

        results = asyncio.run(_run())
        # All three tasks should have spent > 0, each isolated
        assert all(s > 0 for s in results)
        # They should have different costs proportional to tokens
        assert results[0] < results[1] < results[2]


# ---------------------------------------------------------------------------
# Group F — multi-tenant shared backend
# ---------------------------------------------------------------------------


class TestMultiTenantBackend:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_shared_backend_tracks_per_user_windows(self) -> None:
        """Multiple users share a backend but have independent windows."""
        shared_backend = InMemoryBackend()

        def make_budget(user_id: str) -> TemporalBudget:
            return TemporalBudget(
                max_usd=5.0,
                window_seconds=3600,
                name=f"user:{user_id}",
                backend=shared_backend,
            )

        with make_budget("alice"):
            record(input_tokens=1000, output_tokens=500, model="gpt-4o-mini")

        with make_budget("bob"):
            record(input_tokens=500, output_tokens=250, model="gpt-4o-mini")

        alice_spent = shared_backend.get_state("user:alice").get("usd", 0.0)
        bob_spent = shared_backend.get_state("user:bob").get("usd", 0.0)

        assert alice_spent > 0
        assert bob_spent > 0
        # Alice and Bob have independent windows
        assert alice_spent != bob_spent

    def test_user_window_exhaustion_does_not_affect_other_users(self) -> None:
        """One user hitting their limit doesn't block others."""
        shared_backend = InMemoryBackend()

        def make_budget(user_id: str) -> TemporalBudget:
            return TemporalBudget(
                max_usd=0.001,
                window_seconds=3600,
                name=f"user:{user_id}",
                backend=shared_backend,
            )

        # alice exhausts her window
        try:
            with make_budget("alice"):
                record(input_tokens=10000, output_tokens=5000, model="gpt-4o")
        except BudgetExceededError:
            pass  # expected — verifying alice's spend doesn't affect bob

        # bob can still make calls
        with make_budget("bob") as bob_b:
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert bob_b.spent > 0

    def test_window_reset_for_one_user_does_not_affect_others(self) -> None:
        """Window reset for one user leaves other users' windows intact."""
        shared_backend = InMemoryBackend()
        t0 = 1000.0

        with patch("time.monotonic", return_value=t0):
            shared_backend.check_and_add(
                "user:alice", {"usd": 0.0008}, {"usd": 0.001}, {"usd": 3600.0}
            )
            shared_backend.check_and_add(
                "user:bob", {"usd": 0.0005}, {"usd": 0.001}, {"usd": 3600.0}
            )

        # Alice's window expires; bob's is still active
        with patch("time.monotonic", return_value=t0 + 3601.0):
            # Alice's window reset: check_and_add should start fresh for alice
            result, _ = shared_backend.check_and_add(
                "user:alice", {"usd": 0.0008}, {"usd": 0.001}, {"usd": 3600.0}
            )
            assert result is True  # accepted in fresh window

        # Bob's window should still have his original spend
        bob_state = shared_backend.get_window_info("user:bob")
        bob_spent, bob_start = bob_state.get("usd", (0.0, None))
        assert bob_spent == pytest.approx(0.0005)
        assert bob_start == pytest.approx(t0)


# ---------------------------------------------------------------------------
# Group G — budget() factory function integration
# ---------------------------------------------------------------------------


class TestBudgetFactoryIntegration:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_string_spec_creates_working_temporal_budget(self) -> None:
        """budget('$X/unit') produces a fully functional TemporalBudget."""
        tb = budget("$5/hr", name="factory_test")
        assert isinstance(tb, TemporalBudget)

        with tb as b:
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert b.spent > 0

    def test_kwargs_with_window_seconds_creates_temporal(self) -> None:
        """budget(max_usd=X, window_seconds=Y) creates a TemporalBudget."""
        tb = budget(max_usd=5.0, window_seconds=3600, name="kwarg_temporal")
        assert isinstance(tb, TemporalBudget)

    def test_regular_budget_kwargs_unchanged(self) -> None:
        """budget(max_usd=X) still returns a plain Budget."""
        b = budget(max_usd=5.0)
        assert isinstance(b, Budget)
        assert not isinstance(b, TemporalBudget)

    def test_no_args_budget_is_tracking_only(self) -> None:
        """budget() with no args tracks spend without enforcing a limit."""
        with budget() as b:
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert b.spent > 0
        assert b.limit is None

    def test_parsed_window_seconds_match_spec(self) -> None:
        """String spec parses to correct max_usd and window_seconds."""
        max_usd, window_seconds = _parse_spec("$2.50/30min")
        assert max_usd == pytest.approx(2.50)
        assert window_seconds == pytest.approx(1800.0)

    def test_temporal_budget_is_reusable_across_sessions(self) -> None:
        """The same TemporalBudget instance can be reused (window persists)."""
        tb = budget("$5/hr", name="reusable")

        with tb:
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
        first_spent = tb.spent

        with tb:
            record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
        second_spent = tb.spent

        # spent on Budget reflects only last context; window backend accumulates
        assert first_spent > 0
        assert second_spent > 0


# ---------------------------------------------------------------------------
# Group H — OTel adapter receives window_resets_total
# ---------------------------------------------------------------------------


class TestOtelWindowResetsIntegration:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_otel_adapter_receives_window_reset_event(self) -> None:
        """_OtelMetricsAdapter.on_window_reset increments window_resets_total."""
        from unittest.mock import MagicMock

        from shekel.integrations.otel_metrics import _OtelMetricsAdapter

        mock_meter = MagicMock()
        reset_counter = MagicMock()
        mock_meter.create_counter.side_effect = lambda name, **kw: (
            reset_counter if name == "shekel.budget.window_resets_total" else MagicMock()
        )
        mock_meter.create_up_down_counter.return_value = MagicMock()
        mock_meter.create_histogram.return_value = MagicMock()

        adapter = _OtelMetricsAdapter(mock_meter)
        AdapterRegistry.register(adapter)

        backend = InMemoryBackend()
        tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="otel_reset", backend=backend)
        t0 = 1000.0

        with patch("time.monotonic", return_value=t0):
            backend.check_and_add("otel_reset", {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})

        with patch("time.monotonic", return_value=t0 + 3601.0):
            with tb:
                pass

        reset_counter.add.assert_called_with(1, {"budget_name": "otel_reset"})
