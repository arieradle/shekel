"""Temporal (rolling-window) budget enforcement for Shekel.

NOTE: InMemoryBackend is intentionally NOT thread-safe. For multi-threaded
use, provide a custom backend with appropriate locking.
"""

from __future__ import annotations

import re
import time
from typing import Any, Protocol, runtime_checkable

from shekel._budget import Budget
from shekel.exceptions import BudgetExceededError

_UNIT_SECONDS: dict[str, int] = {"s": 1, "sec": 1, "min": 60, "hr": 3600, "h": 3600}
_CALENDAR_UNITS = {"day", "days", "week", "weeks", "month", "months"}
_SPEC_RE = re.compile(
    r"^\$?(?P<amount>[\d.]+)\s*(?:per\s+)?(?P<count>[\d.]*)\s*(?P<unit>\w+)$",
    re.IGNORECASE,
)


def _parse_spec(spec: str) -> tuple[float, float]:
    """Parse "$5/hr" or "$5 per 30min" -> (max_usd, window_seconds)."""
    normalized = spec.strip().replace("/", " ")
    m = _SPEC_RE.match(normalized)
    if not m:
        raise ValueError(f"Cannot parse temporal budget spec: {spec!r}")
    amount = float(m.group("amount"))
    if amount <= 0:
        raise ValueError(f"Budget amount must be > 0, got {amount}")
    unit = m.group("unit").lower()
    if unit in _CALENDAR_UNITS:
        raise ValueError(f"Calendar unit {unit!r} not supported. Use 's', 'min', or 'hr'.")
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"Unknown time unit: {unit!r}")
    count_str = m.group("count")
    count = float(count_str) if count_str else 1.0
    return amount, count * _UNIT_SECONDS[unit]


@runtime_checkable
class TemporalBudgetBackend(Protocol):
    def get_state(self, budget_name: str) -> tuple[float, float | None]:
        """Return (spent_usd, window_start_monotonic) for the named budget."""
        pass

    def check_and_add(
        self,
        budget_name: str,
        amount: float,
        max_usd: float,
        window_seconds: float,
    ) -> bool:
        """Atomically check limit and add amount. Returns False if it would exceed."""
        pass

    def reset(self, budget_name: str) -> None:
        """Reset the window state for the given budget name."""
        pass


class InMemoryBackend:
    """Simple in-process rolling-window backend.

    NOT thread-safe — each thread/task should use its own budget instance.
    """

    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float | None]] = {}

    def get_state(self, budget_name: str) -> tuple[float, float | None]:
        return self._state.get(budget_name, (0.0, None))

    def check_and_add(
        self,
        budget_name: str,
        amount: float,
        max_usd: float,
        window_seconds: float,
    ) -> bool:
        spent, window_start = self.get_state(budget_name)
        now = time.monotonic()
        # If window has expired, reset it
        if window_start is not None and (now - window_start) >= window_seconds:
            spent = 0.0
            window_start = None
        if spent + amount > max_usd:
            return False
        self._state[budget_name] = (
            spent + amount,
            window_start if window_start is not None else now,
        )
        return True

    def reset(self, budget_name: str) -> None:
        self._state.pop(budget_name, None)


class TemporalBudget(Budget):
    """Rolling-window budget that resets after each window_seconds period."""

    def __init__(
        self,
        max_usd: float,
        window_seconds: float,
        *,
        name: str,
        backend: TemporalBudgetBackend | None = None,
        **kwargs: Any,
    ) -> None:
        if not name:
            raise ValueError("TemporalBudget requires a non-empty name=")
        super().__init__(max_usd=max_usd, name=name, **kwargs)
        self._window_seconds = window_seconds
        self._backend: TemporalBudgetBackend = backend or InMemoryBackend()

    def _check_temporal_ancestor(self) -> None:
        """Raise ValueError if any ancestor budget in the current stack is a TemporalBudget."""
        from shekel import _context

        current = _context.get_active_budget()
        while current is not None:
            if isinstance(current, TemporalBudget):
                raise ValueError(
                    f"TemporalBudget '{self.name}' cannot be nested inside another "
                    f"TemporalBudget '{current.name}'. Temporal budgets must not be nested."
                )
            current = current.parent

    def _lazy_window_reset(self) -> None:
        """If window has expired, emit on_window_reset event."""
        budget_name = self.name or "unnamed"
        spent, window_start = self._backend.get_state(budget_name)
        if window_start is None:
            return
        now = time.monotonic()
        if (now - window_start) >= self._window_seconds:
            try:
                from shekel.integrations import AdapterRegistry

                AdapterRegistry.emit_event(
                    "on_window_reset",
                    {
                        "budget_name": self.name,
                        "window_seconds": self._window_seconds,
                        "previous_spent": spent,
                    },
                )
            except Exception:  # noqa: BLE001 — adapter must never crash user code
                pass

    def _record_spend(self, cost: float, model: str, tokens: dict[str, int]) -> None:
        """Override to enforce rolling-window spend before calling parent."""
        budget_name = self.name or "unnamed"
        max_usd = self._effective_limit
        if max_usd is not None:
            now = time.monotonic()
            current_spent, window_start = self._backend.get_state(budget_name)
            # Compute window-aware current spend (for error payload)
            if window_start is not None and (now - window_start) >= self._window_seconds:
                # Window has expired — treat as fresh
                current_spent = 0.0
                window_start = None

            accepted = self._backend.check_and_add(budget_name, cost, max_usd, self._window_seconds)
            if not accepted:
                # Compute retry_after: time remaining in current window
                retry_after: float | None = None
                if window_start is not None:
                    elapsed = now - window_start
                    retry_after = max(0.0, self._window_seconds - elapsed)
                raise BudgetExceededError(
                    spent=current_spent + cost,
                    limit=max_usd,
                    model=model,
                    tokens=tokens,
                    retry_after=retry_after,
                    window_spent=current_spent,
                )
        super()._record_spend(cost, model, tokens)

    def __enter__(self) -> TemporalBudget:
        self._check_temporal_ancestor()
        self._lazy_window_reset()
        return super().__enter__()  # type: ignore[return-value]

    async def __aenter__(self) -> TemporalBudget:
        self._check_temporal_ancestor()
        self._lazy_window_reset()
        return await super().__aenter__()  # type: ignore[return-value]
