from __future__ import annotations

import warnings
from typing import Callable, Optional

from shekel import _context, _patch
from shekel.exceptions import BudgetExceededError


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
    """

    def __init__(
        self,
        max_usd: Optional[float] = None,
        warn_at: Optional[float] = None,
        on_exceed: Optional[Callable[[float, float], None]] = None,
        price_per_1k_tokens: Optional[dict[str, float]] = None,
    ) -> None:
        if warn_at is not None and not (0.0 <= warn_at <= 1.0):
            raise ValueError(f"warn_at must be a fraction between 0.0 and 1.0, got {warn_at}")
        if price_per_1k_tokens is not None:
            if "input" not in price_per_1k_tokens or "output" not in price_per_1k_tokens:
                raise ValueError(
                    "price_per_1k_tokens must have both 'input' and 'output' keys. "
                    f"Got: {list(price_per_1k_tokens.keys())}"
                )

        self.max_usd = max_usd
        self.warn_at = warn_at
        self.on_exceed = on_exceed
        self.price_per_1k_tokens = price_per_1k_tokens

        self._spent: float = 0.0
        self._warn_fired: bool = False
        self._last_model: str = "unknown"
        self._last_tokens: dict[str, int] = {"input": 0, "output": 0}
        self._ctx_token: Optional[object] = None

    # ------------------------------------------------------------------
    # Sync context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Budget":
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

    async def __aenter__(self) -> "Budget":
        _patch.apply_patches()
        self._ctx_token = _context.set_active_budget(self)
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        _context.set_active_budget(None)
        _patch.remove_patches()

    # ------------------------------------------------------------------
    # Internal spend recording (called by _patch.py)
    # ------------------------------------------------------------------

    def _record_spend(self, cost: float, model: str, tokens: dict[str, int]) -> None:
        self._spent += cost
        self._last_model = model
        self._last_tokens = tokens
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
        if self.max_usd is not None and self._spent > self.max_usd:
            raise BudgetExceededError(
                self._spent, self.max_usd, self._last_model, self._last_tokens
            )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def spent(self) -> float:
        """Total USD spent so far in this context."""
        return self._spent

    @property
    def remaining(self) -> Optional[float]:
        """Remaining USD budget, or None if track-only mode (max_usd=None)."""
        if self.max_usd is None:
            return None
        return max(0.0, self.max_usd - self._spent)

    @property
    def limit(self) -> Optional[float]:
        """The configured max_usd limit, or None if track-only mode."""
        return self.max_usd

    @property
    def price_override(self) -> Optional[dict[str, float]]:
        """Price override dict for _patch.py to use."""
        return self.price_per_1k_tokens
