from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Callable, TypedDict

from shekel import _context, _patch
from shekel.exceptions import BudgetExceededError

if TYPE_CHECKING:
    pass


class CallRecord(TypedDict):
    model: str
    cost: float
    input_tokens: int
    output_tokens: int
    fallback: bool


class Budget:
    """LLM spend tracker and budget enforcer.

    Usage:
        with budget(max_usd=1.00, warn_at=0.8) as b:
            response = openai_client.chat.completions.create(...)
        print(f"Spent: ${b.spent:.4f}")

    Track-only mode (no enforcement):
        with budget() as b:
            response = openai_client.chat.completions.create(...)
        print(f"This run cost: ${b.spent:.4f}")

    Model fallback (v0.2):
        with budget(max_usd=1.00, fallback="gpt-4o-mini") as b:
            run_agent()  # switches to mini at $1.00, keeps running
        print(b.model_switched)   # True
        print(b.summary())

    Hard cap (v0.2) — absolute ceiling even for fallback model:
        # Default: hard_cap = max_usd * 2 (runaway protection, always active with fallback)
        with budget(max_usd=1.00, fallback="gpt-4o-mini", hard_cap=1.50) as b:
            run_agent()  # switches at $1.00, raises BudgetExceededError at $1.50

    Session (persistent) budget (v0.2):
        session = budget(max_usd=5.00, persistent=True)
        with session:
            respond(turn_1)
        with session:
            respond(turn_2)   # spend accumulates

    Note: Persistent budget objects are not thread-safe when shared across threads.
    Each thread should use its own budget instance.
    """

    def __init__(
        self,
        max_usd: float | None = None,
        warn_at: float | None = None,
        on_exceed: Callable[[float, float], None] | None = None,
        price_per_1k_tokens: dict[str, float] | None = None,
        # --- NEW in v0.2 ---
        fallback: str | None = None,
        on_fallback: Callable[[float, float, str], None] | None = None,
        persistent: bool = False,
        hard_cap: float | None = None,
    ) -> None:
        if warn_at is not None and not (0.0 <= warn_at <= 1.0):
            raise ValueError(f"warn_at must be a fraction between 0.0 and 1.0, got {warn_at}")
        if price_per_1k_tokens is not None:
            if "input" not in price_per_1k_tokens or "output" not in price_per_1k_tokens:
                raise ValueError(
                    "price_per_1k_tokens must have both 'input' and 'output' keys. "
                    f"Got: {list(price_per_1k_tokens.keys())}"
                )
        if on_fallback is not None and fallback is None:
            raise ValueError("on_fallback requires fallback to be set")
        if fallback is not None and fallback == "":
            raise ValueError("fallback must be a non-empty string if provided")
        if fallback is not None and max_usd is None:
            warnings.warn(
                "shekel: fallback has no effect without max_usd",
                stacklevel=2,
            )
        if hard_cap is not None and fallback is None:
            warnings.warn(
                "shekel: hard_cap has no effect without fallback",
                stacklevel=2,
            )
        if hard_cap is not None and max_usd is not None and hard_cap <= max_usd:
            raise ValueError(
                f"hard_cap (${hard_cap:.2f}) must be greater than max_usd (${max_usd:.2f})"
            )

        self.max_usd = max_usd
        self.warn_at = warn_at
        self.on_exceed = on_exceed
        self.price_per_1k_tokens = price_per_1k_tokens
        self.fallback: str | None = fallback
        self.on_fallback = on_fallback
        self.persistent: bool = persistent
        self.hard_cap: float | None = hard_cap

        self._ctx_token: object | None = None

        # All spend-tracking state lives here — reset on each __enter__ for non-persistent
        self._spent: float = 0.0
        self._warn_fired: bool = False
        self._last_model: str = "unknown"
        self._last_tokens: dict[str, int] = {"input": 0, "output": 0}
        self._using_fallback: bool = False
        self._fallback_spent: float = 0.0
        self._switched_at_usd: float | None = None
        self._calls: list[CallRecord] = []

    # ------------------------------------------------------------------
    # Internal state reset
    # ------------------------------------------------------------------

    def _reset_state(self) -> None:
        """Reset all spend tracking state. Called on __enter__ for non-persistent budgets."""
        self._spent = 0.0
        self._warn_fired = False
        self._last_model = "unknown"
        self._last_tokens = {"input": 0, "output": 0}
        self._using_fallback = False
        self._fallback_spent = 0.0
        self._switched_at_usd = None
        self._calls = []

    # ------------------------------------------------------------------
    # Sync context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Budget:
        if not self.persistent:
            self._reset_state()
        _patch.apply_patches()
        self._ctx_token = _context.set_active_budget(self)
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # Always clean up — even if BudgetExceededError is in flight
        _context.set_active_budget(None)
        _patch.remove_patches()
        # returning None (not False) — never suppress exceptions

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Budget:
        if not self.persistent:
            self._reset_state()
        _patch.apply_patches()
        self._ctx_token = _context.set_active_budget(self)
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        _context.set_active_budget(None)
        _patch.remove_patches()

    # ------------------------------------------------------------------
    # Public reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all spend tracking. Safe to call between with-blocks.

        Raises RuntimeError if called while the budget context is active
        (i.e. inside a with-block).
        """
        if _context.get_active_budget() is self:
            raise RuntimeError(
                "shekel: budget.reset() cannot be called inside an active with-block. "
                "Call reset() between with-blocks."
            )
        self._reset_state()

    # ------------------------------------------------------------------
    # Internal spend recording (called by _patch.py)
    # ------------------------------------------------------------------

    def _record_spend(self, cost: float, model: str, tokens: dict[str, int]) -> None:
        self._spent += cost
        if self._using_fallback:
            self._fallback_spent += cost
        self._last_model = model
        self._last_tokens = tokens
        # Record call for summary (F5)
        self._calls.append(
            CallRecord(
                model=model,
                cost=cost,
                input_tokens=tokens.get("input", 0),
                output_tokens=tokens.get("output", 0),
                fallback=self._using_fallback,
            )
        )
        self._check_warn()
        self._check_limit()

    def _check_warn(self) -> None:
        if (
            self.warn_at is not None
            and self.max_usd is not None
            and not self._warn_fired
            and self._spent >= self.max_usd * self.warn_at
        ):
            self._warn_fired = True
            if self.on_exceed is not None:
                self.on_exceed(self._spent, self.max_usd)
            else:
                warnings.warn(
                    f"shekel: ${self._spent:.4f} spent — "
                    f"{self.warn_at * 100:.0f}% of ${self.max_usd:.2f} budget reached.",
                    stacklevel=4,
                )

    def _check_limit(self) -> None:
        if self.max_usd is None:
            return
        if self._spent <= self.max_usd:
            return

        if self.fallback is not None and not self._using_fallback:
            # Activate fallback instead of raising
            self._using_fallback = True
            self._switched_at_usd = self._spent
            if self.on_fallback is not None:
                self.on_fallback(self._spent, self.max_usd, self.fallback)
            else:
                warnings.warn(
                    f"shekel: budget of ${self.max_usd:.2f} exceeded "
                    f"(${self._spent:.4f} spent). "
                    f"Switching to fallback model '{self.fallback}'.",
                    stacklevel=4,
                )
            return

        if self.fallback is not None and self._using_fallback:
            # Fallback is active — enforce the hard cap.
            # Default hard cap = max_usd * 2 if not explicitly set (runaway protection).
            effective_hard_cap = self.hard_cap
            if effective_hard_cap is None and self.max_usd is not None:
                effective_hard_cap = self.max_usd * 2.0

            if effective_hard_cap is not None and self._spent > effective_hard_cap:
                raise BudgetExceededError(
                    self._spent,
                    effective_hard_cap,
                    self._last_model,
                    self._last_tokens,
                )

            # Under hard cap — warn once per entry into this branch
            warnings.warn(
                f"shekel: fallback model '{self.fallback}' has exceeded the primary budget "
                f"(${self._spent:.4f} spent, primary limit ${self.max_usd:.2f}). "
                f"Hard cap: ${effective_hard_cap:.2f}. "
                f"Use hard_cap= to override.",
                stacklevel=4,
            )
            return

        # No fallback — standard raise
        raise BudgetExceededError(self._spent, self.max_usd, self._last_model, self._last_tokens)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def spent(self) -> float:
        """Total USD spent so far in this context."""
        return self._spent

    @property
    def remaining(self) -> float | None:
        """Remaining USD budget, or None if track-only mode (max_usd=None)."""
        if self.max_usd is None:
            return None
        return max(0.0, self.max_usd - self._spent)

    @property
    def limit(self) -> float | None:
        """The configured max_usd limit, or None if track-only mode."""
        return self.max_usd

    @property
    def price_override(self) -> dict[str, float] | None:
        """Price override dict for _patch.py to use."""
        return self.price_per_1k_tokens

    @property
    def model_switched(self) -> bool:
        """True if a fallback switch has occurred in this budget context."""
        return self._using_fallback

    @property
    def switched_at_usd(self) -> float | None:
        """USD spent at the moment the switch occurred, or None if no switch."""
        return self._switched_at_usd

    @property
    def fallback_spent(self) -> float:
        """USD spent on the fallback model (0.0 if no switch occurred)."""
        return self._fallback_spent

    # ------------------------------------------------------------------
    # Summary (F5)
    # ------------------------------------------------------------------

    def summary_data(self) -> dict[str, object]:
        """Return structured spend data as a dict."""
        by_model: dict[str, dict[str, Any]] = {}
        for call in self._calls:
            m = call["model"]
            if m not in by_model:
                by_model[m] = {"calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0}
            by_model[m]["calls"] += 1
            by_model[m]["cost"] += call["cost"]
            by_model[m]["input_tokens"] += call["input_tokens"]
            by_model[m]["output_tokens"] += call["output_tokens"]

        effective_hard_cap: float | None = self.hard_cap
        if effective_hard_cap is None and self.fallback is not None and self.max_usd is not None:
            effective_hard_cap = self.max_usd * 2.0

        return {
            "total_spent": self._spent,
            "limit": self.max_usd,
            "hard_cap": self.hard_cap,
            "effective_hard_cap": effective_hard_cap,
            "model_switched": self._using_fallback,
            "switched_at_usd": self._switched_at_usd,
            "fallback_model": self.fallback,
            "fallback_spent": self._fallback_spent,
            "total_calls": len(self._calls),
            "calls": list(self._calls),
            "by_model": by_model,
        }

    def summary(self) -> str:
        """Return a plain-text formatted spend summary."""
        lines = []
        width = 60

        total_spent: float = self._spent
        limit_val: float | None = self.max_usd
        model_switched: bool = self._using_fallback
        switched_at: float | None = self._switched_at_usd
        calls: list[CallRecord] = list(self._calls)
        total_calls: int = len(calls)

        # Build per-model aggregation
        by_model: dict[str, dict[str, Any]] = {}
        for call in calls:
            m = call["model"]
            if m not in by_model:
                by_model[m] = {"calls": 0, "cost": 0.0}
            by_model[m]["calls"] += 1
            by_model[m]["cost"] += call["cost"]

        status = (
            "SWITCHED"
            if model_switched
            else ("EXCEEDED" if (limit_val is not None and total_spent > limit_val) else "OK")
        )
        limit_str = f"${limit_val:.2f}" if limit_val is not None else "none"

        lines.append("┌─ Shekel Budget Summary " + "─" * (width - 24) + "┐")
        lines.append(
            f"│ Total: ${total_spent:.4f}  Limit: {limit_str}  "
            f"Calls: {total_calls}  Status: {status}"
        )

        if calls:
            lines.append("├" + "─" * width + "┤")
            lines.append(f"│  {'#':<4} {'Model':<28} {'Input':>7} {'Output':>7} {'Cost':>10}")
            lines.append("│  " + "─" * (width - 2))
            for i, call in enumerate(calls, 1):
                fallback_marker = " ← fallback" if call["fallback"] else ""
                lines.append(
                    f"│  {i:<4} {call['model']:<28} "
                    f"{call['input_tokens']:>7,} {call['output_tokens']:>7,} "
                    f"${call['cost']:>9.4f}{fallback_marker}"
                )

        lines.append("├" + "─" * width + "┤")
        for model, stats in by_model.items():
            lines.append(f"│  {model}: {stats['calls']} calls  ${stats['cost']:.4f}")

        if model_switched and switched_at is not None:
            lines.append(f"│  Switched at: ${switched_at:.4f}")

        lines.append("└" + "─" * width + "┘")
        return "\n".join(lines)
