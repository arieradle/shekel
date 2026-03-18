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

# Maps spec-string type tokens → internal counter names.
# Checked case-insensitively after lowercasing.
_CAP_TYPE_MAP: dict[str, str] = {
    "usd": "usd",
    "call": "llm_calls",
    "calls": "llm_calls",
    "tool": "tool_calls",
    "tools": "tool_calls",
    "token": "tokens",
    "tokens": "tokens",
}

# Matches one cap term, e.g.: "$5/hr", "5 usd/hr", "100 calls/30min", "20 tools/1hr"
# Groups: usd_dollar (from $N), gen_num + gen_type (from N calls/tools/etc.),
#         window_count (optional multiplier), unit
_CAP_TERM_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"  \$(?P<usd_dollar>[\d.]+)"
    r"  |(?P<gen_num>[\d.]+)\s+(?P<gen_type>usd|calls?|tools?|tokens?)"
    r")"
    r"\s*(?:/\s*|\s+per\s+|\s+)"
    r"(?P<window_count>[\d.]*)\s*"
    r"(?P<unit>sec|min|hr|h|s)\b"
    r"\s*$",
    re.IGNORECASE | re.VERBOSE,
)

# Legacy single-cap regex kept for _parse_spec backward compat.
_SPEC_RE = re.compile(
    r"^\$?(?P<amount>[\d.]+)\s*(?:per\s+)?(?P<count>[\d.]*)\s*(?P<unit>\w+)$",
    re.IGNORECASE,
)

# Ordered check sequence: usd is checked before llm_calls before tool_calls.
_CHECK_ORDER = ("usd", "llm_calls", "tool_calls", "tokens")


def _parse_one_cap_term(term: str) -> tuple[str, float | None, float]:
    """Parse a single cap term like '$5/hr' or '100 calls/30min'.

    Returns:
        (counter_name, limit, window_seconds)
    """
    m = _CAP_TERM_RE.match(term.strip())
    if not m:
        raise ValueError(f"Cannot parse cap term: {term!r}")

    if m.group("usd_dollar") is not None:
        counter = "usd"
        amount = float(m.group("usd_dollar"))
    else:
        gen_type = m.group("gen_type").lower()
        # strip trailing 's' handled by the map
        mapped = _CAP_TYPE_MAP.get(gen_type)
        if mapped is None:  # pragma: no cover — regex restricts gen_type to known tokens
            raise ValueError(f"Unknown cap type: {m.group('gen_type')!r}")
        counter = mapped
        amount = float(m.group("gen_num"))

    if amount <= 0:
        raise ValueError(f"Cap amount must be > 0, got {amount}")

    unit = m.group("unit").lower()
    if unit in _CALENDAR_UNITS:  # pragma: no cover — regex restricts unit to known tokens
        raise ValueError(f"Calendar unit {unit!r} not supported. Use 's', 'min', or 'hr'.")
    if unit not in _UNIT_SECONDS:  # pragma: no cover — regex restricts unit to known tokens
        raise ValueError(f"Unknown time unit: {unit!r}")

    count_str = m.group("window_count")
    count = float(count_str) if count_str else 1.0
    window_s = count * _UNIT_SECONDS[unit]
    return counter, amount, window_s


def _parse_cap_spec(spec: str) -> list[tuple[str, float | None, float]]:
    """Parse a (possibly multi-cap) spec string into a list of cap tuples.

    Examples::

        _parse_cap_spec("$5/hr")                     # [("usd", 5.0, 3600.0)]
        _parse_cap_spec("100 calls/hr")               # [("llm_calls", 100.0, 3600.0)]
        _parse_cap_spec("$5/hr + 100 calls/30min")    # two caps, different windows

    Returns:
        List of (counter_name, limit, window_seconds) tuples.
    """
    terms = [t.strip() for t in spec.split("+")]
    return [_parse_one_cap_term(t) for t in terms if t]


def _parse_spec(spec: str) -> tuple[float, float]:
    """Parse "$5/hr" or "$5 per 30min" -> (max_usd, window_seconds).

    Backward-compatible single-USD-cap parser.
    For multi-cap specs, use _parse_cap_spec() directly.
    """
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
    """Generic named-counter backend protocol for rolling-window budgets.

    The backend is unaware of USD vs. calls — it manages named counters
    with per-counter limits and windows.  All-or-nothing atomicity: if any
    counter would exceed its limit, none are incremented.
    """

    def check_and_add(
        self,
        budget_name: str,
        amounts: dict[str, float],
        limits: dict[str, float | None],
        windows: dict[str, float],
    ) -> tuple[bool, str | None]:
        """Atomically check limits and add amounts.

        Args:
            budget_name: Unique identifier for this budget.
            amounts: Counter increments for this call, e.g. {"usd": 0.03, "llm_calls": 1}.
            limits: Per-counter caps; None means tracked but uncapped.
            windows: Per-counter window durations in seconds.

        Returns:
            (allowed, exceeded_counter_name_or_None).
            If allowed is False, exceeded_counter names the first counter that
            would have exceeded (checked in deterministic order).
        """
        pass

    def get_state(self, budget_name: str) -> dict[str, float]:
        """Return current-window spend for each counter."""
        pass

    def reset(self, budget_name: str) -> None:
        """Reset all counters for the given budget name."""
        pass


class InMemoryBackend:
    """Simple in-process rolling-window backend.

    NOT thread-safe — each thread/task should use its own budget instance.
    Implements the generic TemporalBudgetBackend protocol.
    """

    def __init__(self) -> None:
        # {budget_name: {counter: (spent, window_start_monotonic | None)}}
        self._state: dict[str, dict[str, tuple[float, float | None]]] = {}

    def check_and_add(
        self,
        budget_name: str,
        amounts: dict[str, float],
        limits: dict[str, float | None],
        windows: dict[str, float],
    ) -> tuple[bool, str | None]:
        """Atomically check limits and add amounts (all-or-nothing)."""
        now = time.monotonic()
        counters = self._state.setdefault(budget_name, {})

        # Phase 1: compute effective current spend (apply window resets to a temp view).
        effective: dict[str, float] = {}
        for counter in amounts:
            spent, window_start = counters.get(counter, (0.0, None))
            window_s = windows[counter]
            if window_start is not None and (now - window_start) >= window_s:
                spent = 0.0
            effective[counter] = spent

        # Phase 2: check limits in deterministic order.
        for counter in _CHECK_ORDER:
            if counter not in amounts:
                continue
            limit = limits.get(counter)
            if limit is not None and effective[counter] + amounts[counter] > limit:
                return False, counter

        # Phase 3: commit — increment all counters.
        for counter, amount in amounts.items():
            prev_spent, window_start = counters.get(counter, (0.0, None))
            window_s = windows[counter]
            # Apply window reset if expired.
            if window_start is not None and (now - window_start) >= window_s:
                prev_spent = 0.0
                window_start = None
            new_window_start = window_start if window_start is not None else now
            counters[counter] = (prev_spent + amount, new_window_start)

        return True, None

    def get_state(self, budget_name: str) -> dict[str, float]:
        """Return current-window spent amount for each counter."""
        counters = self._state.get(budget_name, {})
        result: dict[str, float] = {}
        for counter, (spent, _window_start) in counters.items():
            result[counter] = spent
        return result

    def get_window_info(self, budget_name: str) -> dict[str, tuple[float, float | None]]:
        """Return {counter: (spent, window_start)} for observability."""
        return dict(self._state.get(budget_name, {}))

    def reset(self, budget_name: str) -> None:
        self._state.pop(budget_name, None)


class TemporalBudget(Budget):
    """Rolling-window budget that resets after each window_seconds period.

    Supports multiple simultaneous caps (usd, llm_calls, tool_calls) each
    with their own independent rolling window.

    Two configuration forms — never mixed:

    Spec string (per-cap windows)::

        budget("$5/hr + 100 calls/hr", name="api")

    Kwargs (single shared window)::

        budget(max_usd=5.0, max_llm_calls=100, window_seconds=3600, name="api")
    """

    def __init__(
        self,
        max_usd: float | None = None,
        window_seconds: float | None = None,
        *,
        name: str,
        backend: TemporalBudgetBackend | None = None,
        caps: list[tuple[str, float | None, float]] | None = None,
        **kwargs: Any,
    ) -> None:
        if not name:
            raise ValueError("TemporalBudget requires a non-empty name=")

        # Extract multi-cap kwargs that should NOT be passed to Budget
        # (Budget enforces them cumulatively; TemporalBudget enforces via backend).
        max_llm_calls: int | None = kwargs.pop("max_llm_calls", None)
        max_tool_calls: int | None = kwargs.pop("max_tool_calls", None)

        # Resolve effective max_usd from caps if not explicitly provided,
        # so parent Budget.max_usd is set correctly without post-init override.
        effective_max_usd = max_usd
        if effective_max_usd is None and caps is not None:
            for counter, limit, _ in caps:
                if counter == "usd" and limit is not None:
                    effective_max_usd = limit
                    break

        # Pass max_usd to parent for .spent / .remaining / .limit property tracking.
        super().__init__(max_usd=effective_max_usd, name=name, **kwargs)
        self._backend: TemporalBudgetBackend = backend or InMemoryBackend()

        if caps is not None:
            # Structured caps from factory (spec-string form).
            self._caps: dict[str, tuple[float | None, float]] = {
                counter: (limit, window_s) for counter, limit, window_s in caps
            }
            # Note: effective_max_usd already passed to super().__init__() above
        else:
            # Build caps from kwargs.
            if window_seconds is None:
                raise ValueError("TemporalBudget requires window_seconds (or use spec-string form)")
            self._caps = {}
            if max_usd is not None:
                self._caps["usd"] = (max_usd, window_seconds)
            if max_llm_calls is not None:
                self._caps["llm_calls"] = (float(max_llm_calls), window_seconds)
            if max_tool_calls is not None:
                self._caps["tool_calls"] = (float(max_tool_calls), window_seconds)
            if not self._caps:
                raise ValueError(
                    "TemporalBudget requires at least one cap (max_usd, max_llm_calls, etc.)"
                )

        # Longest window in caps — used for legacy _window_seconds attribute.
        self._window_seconds: float = (
            max(v[1] for v in self._caps.values()) if self._caps else (window_seconds or 3600.0)
        )

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
        """If the primary window has expired since last entry, emit on_window_reset."""
        budget_name = self.name or "unnamed"

        # Use get_window_info if available (InMemoryBackend exposes it).
        if not hasattr(self._backend, "get_window_info"):
            return

        info = self._backend.get_window_info(budget_name)
        if not info:
            return

        now = time.monotonic()
        # Check primary cap (usd if present, else first cap).
        primary = "usd" if "usd" in info else next(iter(info))
        spent, window_start = info[primary]
        _, primary_window_s = self._caps.get(primary, (None, self._window_seconds))

        if window_start is None:
            return
        if (now - window_start) < primary_window_s:
            return

        try:
            from shekel.integrations import AdapterRegistry

            AdapterRegistry.emit_event(
                "on_window_reset",
                {
                    "budget_name": self.name,
                    "window_seconds": primary_window_s,
                    "previous_spent": spent,
                },
            )
        except Exception:  # noqa: BLE001 — adapter must never crash user code
            pass

    def _record_spend(self, cost: float, model: str, tokens: dict[str, int]) -> None:
        """Override to enforce rolling-window spend via backend before calling parent."""
        budget_name = self.name or "unnamed"

        # Build amounts/limits/windows for backend call.
        # Only include LLM-relevant counters (usd + llm_calls).
        amounts: dict[str, float] = {}
        limits: dict[str, float | None] = {}
        windows: dict[str, float] = {}

        for counter, (limit, window_s) in self._caps.items():
            if counter == "usd":
                amounts[counter] = cost
                limits[counter] = limit
                windows[counter] = window_s
            elif counter == "llm_calls":
                amounts[counter] = 1.0
                limits[counter] = limit
                windows[counter] = window_s
            # tool_calls are handled separately via _record_tool_call / _check_tool_limit

        if amounts:
            # Gather pre-call state for error payload (window_spent, retry_after).
            now = time.monotonic()
            pre_state: dict[str, tuple[float, float | None]] = {}
            if hasattr(self._backend, "get_window_info"):
                pre_state = self._backend.get_window_info(budget_name)

            allowed, exceeded = self._backend.check_and_add(budget_name, amounts, limits, windows)
            if not allowed:
                # Compute retry_after and window_spent for the exceeded counter.
                retry_after: float | None = None
                window_spent: float | None = None
                if exceeded and exceeded in pre_state:
                    prev_spent, window_start = pre_state[exceeded]
                    window_s = windows.get(exceeded, self._window_seconds)
                    # Check if window had already expired before this call.
                    if window_start is not None and (now - window_start) < window_s:
                        elapsed = now - window_start
                        retry_after = max(0.0, window_s - elapsed)
                        window_spent = prev_spent
                    else:
                        window_spent = 0.0  # fresh window

                exc_limit = limits.get(exceeded or "usd") or 0.0
                exc_spent = (
                    pre_state.get(exceeded or "usd", (0.0, None))[0] if exceeded else 0.0
                ) + (amounts.get(exceeded or "usd", 0.0))
                raise BudgetExceededError(
                    spent=exc_spent,
                    limit=exc_limit,
                    model=model,
                    tokens=tokens,
                    retry_after=retry_after,
                    window_spent=window_spent,
                    exceeded_counter=exceeded,
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
