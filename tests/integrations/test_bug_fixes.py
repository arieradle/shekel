"""Tests for v0.2.4 bug fixes applied to Langfuse integration branch.

Bug 1: _check_limit/_check_warn used self.max_usd instead of self._effective_limit.
        Auto-capped children (effective_limit < max_usd) were not enforced correctly.

Bug 2: _emit_budget_exceeded_event reported self.max_usd as limit instead of effective_limit.
        Event data was wrong for auto-capped nested budgets.
"""

from __future__ import annotations

import pytest

from shekel import BudgetExceededError, budget, with_budget
from shekel.integrations import AdapterRegistry, ObservabilityAdapter


class CollectingAdapter(ObservabilityAdapter):
    def __init__(self) -> None:
        self.cost_updates: list[dict] = []
        self.budget_exceeded_events: list[dict] = []
        self.fallback_events: list[dict] = []

    def on_cost_update(self, data: dict) -> None:
        self.cost_updates.append(data.copy())

    def on_budget_exceeded(self, data: dict) -> None:
        self.budget_exceeded_events.append(data.copy())

    def on_fallback_activated(self, data: dict) -> None:
        self.fallback_events.append(data.copy())


# ---------------------------------------------------------------------------
# Bug 1: effective_limit enforcement in _check_limit
# ---------------------------------------------------------------------------


class TestAutoCapEnforcement:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_auto_capped_child_raises_at_effective_limit(self) -> None:
        """Child capped to $3 must raise BudgetExceededError at $3, not at max_usd ($5)."""
        with budget(max_usd=10.00, name="parent") as parent:
            parent._spent = 7.00  # parent has $3 remaining -> child capped to $3

            with pytest.raises(BudgetExceededError) as exc_info:
                with budget(max_usd=5.00, name="child") as child:
                    assert child.limit == 3.00  # confirmed capped
                    # Record $3.50 — exceeds effective_limit ($3) but not max_usd ($5)
                    child._record_spend(3.50, "gpt-4o", {"input": 100, "output": 50})

            # Error should reference $3 (effective limit), not $5 (max_usd)
            assert exc_info.value.limit == 3.00

    def test_uncapped_child_still_enforces_max_usd(self) -> None:
        """Non-capped child enforces max_usd as before."""
        with budget(max_usd=20.00, name="parent"):
            with pytest.raises(BudgetExceededError) as exc_info:
                with budget(max_usd=5.00, name="child") as child:
                    child._record_spend(6.00, "gpt-4o", {"input": 100, "output": 50})

            assert exc_info.value.limit == 5.00


# ---------------------------------------------------------------------------
# Bug 1b: effective_limit enforcement in _check_warn
# ---------------------------------------------------------------------------


class TestAutoCapWarnAt:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_warn_fires_at_effective_limit_threshold(self) -> None:
        """warn_at fires based on effective_limit ($3), not max_usd ($5)."""
        fired: list[tuple[float, float]] = []

        with budget(max_usd=10.00, name="parent") as parent:
            parent._spent = 7.00  # child will be capped to $3

            with budget(
                max_usd=5.00,
                warn_at=0.5,
                on_exceed=lambda s, l: fired.append((s, l)),
                name="child",
            ) as child:
                assert child.limit == 3.00
                # $1.60 > 50% of $3 ($1.50), so warn should fire
                child._record_spend(1.60, "gpt-4o", {"input": 100, "output": 50})

        assert len(fired) == 1
        _spent, limit = fired[0]
        assert limit == 3.00, f"Expected warn against $3 effective limit, got ${limit}"

    def test_warn_does_not_fire_below_effective_threshold(self) -> None:
        """warn_at must NOT fire if spend is below effective threshold."""
        fired: list[tuple[float, float]] = []

        with budget(max_usd=10.00, name="parent") as parent:
            parent._spent = 7.00  # child capped to $3

            with budget(
                max_usd=5.00,
                warn_at=0.5,
                on_exceed=lambda s, l: fired.append((s, l)),
                name="child",
            ) as child:
                assert child.limit == 3.00
                # $1.40 < 50% of $3 ($1.50) — should NOT fire
                child._record_spend(1.40, "gpt-4o", {"input": 100, "output": 50})

        assert len(fired) == 0


# ---------------------------------------------------------------------------
# Bug 2: _emit_budget_exceeded_event uses effective_limit
# ---------------------------------------------------------------------------


class TestBudgetExceededEventLimit:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_exceeded_event_reports_effective_limit(self) -> None:
        """on_budget_exceeded event should report effective_limit, not max_usd."""
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        with budget(max_usd=10.00, name="parent") as parent:
            parent._spent = 7.00  # child will be capped to $3

            try:
                with budget(max_usd=5.00, name="child") as child:
                    assert child.limit == 3.00
                    child._record_spend(4.00, "gpt-4o", {"input": 100, "output": 50})
            except BudgetExceededError:
                pass

        assert len(adapter.budget_exceeded_events) >= 1
        event = adapter.budget_exceeded_events[0]
        assert event["limit"] == 3.00, f"Expected limit=3.00 in event, got {event['limit']}"
        assert event["overage"] == pytest.approx(1.00), f"Expected overage=1.00, got {event['overage']}"

    def test_exceeded_event_uncapped_reports_max_usd(self) -> None:
        """For non-capped budgets, event limit equals max_usd."""
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)

        try:
            with budget(max_usd=5.00, name="root") as b:
                b._record_spend(6.00, "gpt-4o", {"input": 100, "output": 50})
        except BudgetExceededError:
            pass

        assert len(adapter.budget_exceeded_events) >= 1
        event = adapter.budget_exceeded_events[0]
        assert event["limit"] == 5.00


# ---------------------------------------------------------------------------
# AdapterRegistry.unregister()
# ---------------------------------------------------------------------------


class TestAdapterUnregister:
    def setup_method(self) -> None:
        AdapterRegistry.clear()

    def test_unregister_removes_adapter(self) -> None:
        adapter = CollectingAdapter()
        AdapterRegistry.register(adapter)
        result = AdapterRegistry.unregister(adapter)
        assert result is True

        # Events should no longer reach the adapter
        with budget(max_usd=5.00) as b:
            from shekel._patch import _record
            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert len(adapter.cost_updates) == 0

    def test_unregister_returns_false_if_not_registered(self) -> None:
        adapter = CollectingAdapter()
        result = AdapterRegistry.unregister(adapter)
        assert result is False

    def test_unregister_only_removes_specific_instance(self) -> None:
        a1 = CollectingAdapter()
        a2 = CollectingAdapter()
        AdapterRegistry.register(a1)
        AdapterRegistry.register(a2)
        AdapterRegistry.unregister(a1)

        with budget(max_usd=5.00) as b:
            from shekel._patch import _record
            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert len(a1.cost_updates) == 0  # removed
        assert len(a2.cost_updates) == 1  # still registered


# ---------------------------------------------------------------------------
# with_budget name parameter
# ---------------------------------------------------------------------------


class TestWithBudgetName:
    def test_with_budget_accepts_name(self) -> None:
        """with_budget should pass name to Budget, enabling nested use."""
        called = []

        @with_budget(max_usd=5.00, name="outer")
        def run() -> None:
            from shekel import _context
            b = _context.get_active_budget()
            assert b is not None
            assert b.name == "outer"
            called.append(True)

        run()
        assert called

    def test_with_budget_name_enables_nesting(self) -> None:
        """Named with_budget decorator can serve as named parent for nested budgets."""
        names_seen: list[str] = []

        @with_budget(max_usd=10.00, name="workflow")
        def run_workflow() -> None:
            with budget(max_usd=3.00, name="step") as child:
                names_seen.append(child.full_name)

        run_workflow()
        assert names_seen == ["workflow.step"]
