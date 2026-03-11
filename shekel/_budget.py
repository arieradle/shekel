from __future__ import annotations

import warnings
from contextvars import Token
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
        persistent: bool = False,  # DEPRECATED in v0.2.3
        hard_cap: float | None = None,
        # --- NEW in v0.2.3 (nested budgets) ---
        name: str | None = None,
    ) -> None:
        # --- NEW in v0.2.3 (Decision #12): Deprecate persistent flag ---
        if persistent is not False:  # User explicitly set it
            warnings.warn(
                "The 'persistent' parameter is deprecated in v0.2.3. "
                "Budget variables now always accumulate across multiple 'with' blocks. "
                "To start fresh, create a new Budget instance.",
                DeprecationWarning,
                stacklevel=2,
            )

        # --- NEW in v0.2.3 (Decision #24): Validate zero/negative budgets ---
        if max_usd is not None and max_usd <= 0:
            raise ValueError(
                "max_usd must be positive or None for track-only mode. " f"Got: {max_usd}"
            )

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

        # --- NEW in v0.2.3 (nested budgets) ---
        self.name: str | None = name
        self.parent: Budget | None = None
        self.children: list[Budget] = []
        self.active_child: Budget | None = None
        self._depth: int = 0
        self._effective_limit: float | None = max_usd  # Will be auto-capped in __enter__

        self._ctx_token: Token[Budget | None] | None = None

        # All spend-tracking state lives here — reset on each __enter__ for non-persistent
        self._spent: float = 0.0
        self._spent_direct: float = 0.0  # NEW in v0.2.3: Direct spend (excluding children)
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
        self._spent_direct = 0.0
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
        # --- REMOVED in v0.2.3 (Decision #12): Always accumulate, never reset ---
        # Budget variables now always accumulate across multiple entries
        # if not self.persistent:
        #     self._reset_state()

        # --- NEW in v0.2.3 (nested budgets): Detect parent and validate BEFORE applying patches ---
        current_budget = _context.get_active_budget()
        if current_budget is not None:
            # We're nesting inside another budget

            # --- NEW in v0.2.3 (Decision #9): Required names for nested budgets ---
            if current_budget.name is None:
                raise ValueError(
                    "Parent budget must have a name when nesting. "
                    "Add name='...' to the parent budget."
                )
            if self.name is None:
                raise ValueError(
                    "Child budget must have a name when nesting. "
                    "Add name='...' to the child budget."
                )

            # --- NEW in v0.2.3 (Decision #18): Max depth limit ---
            if current_budget._depth >= 4:  # Depth 4 is max (0, 1, 2, 3, 4)
                raise ValueError(
                    f"Maximum budget nesting depth of 5 exceeded. "
                    f"Current depth: {current_budget._depth}, "
                    f"attempted depth: {current_budget._depth + 1}"
                )

            # --- NEW in v0.2.3 (Decision #23): Unique sibling names ---
            # Check if parent already has a child with this name
            for existing_child in current_budget.children:
                if existing_child.name == self.name:
                    raise ValueError(
                        f"Child name '{self.name}' already exists under "
                        f"parent '{current_budget.name}'. "
                        f"Sibling budgets must have unique names."
                    )

        # All validation passed - now apply patches
        _patch.apply_patches()

        # Set up parent-child relationships
        if current_budget is not None:
            self.parent = current_budget
            self._depth = current_budget._depth + 1
            # Register as child of parent
            current_budget.children.append(self)
            current_budget.active_child = self

            # --- NEW in v0.2.3 (Decision #2): Auto-capping ---
            # Cap child limit to parent's remaining budget
            if self.max_usd is not None and current_budget.remaining is not None:
                self._effective_limit = min(self.max_usd, current_budget.remaining)
            else:
                # Track-only child (max_usd=None) is not capped
                self._effective_limit = self.max_usd
        else:
            # Root budget - no capping needed
            self._effective_limit = self.max_usd

        self._ctx_token = _context.set_active_budget(self)
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # --- NEW in v0.2.3 (nested budgets): Propagate to parent ---
        if self.parent is not None:
            # Propagate our spend to parent
            self.parent._spent += self._spent
            # Clear parent's active_child
            self.parent.active_child = None

        # Always clean up — even if BudgetExceededError is in flight
        # Use proper ContextVar token-based restoration
        if self._ctx_token is not None:
            from shekel._context import _active_budget

            _active_budget.reset(self._ctx_token)
        _patch.remove_patches()
        # returning None (not False) — never suppress exceptions

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Budget:
        # --- REMOVED in v0.2.3 (Decision #12): Always accumulate, never reset ---
        # if not self.persistent:
        #     self._reset_state()

        # --- NEW in v0.2.3 (Decision #20): No async nesting in MVP ---
        current_budget = _context.get_active_budget()
        if current_budget is not None:
            raise RuntimeError(
                "Nested budgets not supported in async contexts yet. "
                "Use sync context managers or a single async budget. "
                "See https://github.com/arieradle/shekel for details."
            )

        _patch.apply_patches()
        self._ctx_token = _context.set_active_budget(self)
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # Use proper ContextVar token-based restoration
        if self._ctx_token is not None:
            from shekel._context import _active_budget

            _active_budget.reset(self._ctx_token)
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
        # --- NEW in v0.2.3 (Decision #4): Parent locking ---
        # If this budget has an active child, it cannot record spend
        if self.active_child is not None:
            raise RuntimeError(
                f"shekel: Cannot spend on parent budget '{self.name or 'unnamed'}' "
                f"while child budget '{self.active_child.name or 'unnamed'}' is active. "
                f"Wait for child context to exit."
            )

        self._spent += cost
        self._spent_direct += cost  # NEW in v0.2.3: Track direct spend
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
        effective_limit = self._effective_limit
        if (
            self.warn_at is not None
            and effective_limit is not None
            and not self._warn_fired
            and self._spent >= effective_limit * self.warn_at
        ):
            self._warn_fired = True
            if self.on_exceed is not None:
                self.on_exceed(self._spent, effective_limit)
            else:
                warnings.warn(
                    f"shekel: ${self._spent:.4f} spent — "
                    f"{self.warn_at * 100:.0f}% of ${effective_limit:.2f} budget reached.",
                    stacklevel=4,
                )

    def _check_limit(self) -> None:
        effective_limit = self._effective_limit
        if effective_limit is None:
            return
        if self._spent <= effective_limit:
            return

        if self.fallback is not None and not self._using_fallback:
            # Activate fallback instead of raising
            self._using_fallback = True
            self._switched_at_usd = self._spent
            self._emit_fallback_activated_event()
            if self.on_fallback is not None:
                self.on_fallback(self._spent, effective_limit, self.fallback)
            else:
                warnings.warn(
                    f"shekel: budget of ${effective_limit:.2f} exceeded "
                    f"(${self._spent:.4f} spent). "
                    f"Switching to fallback model '{self.fallback}'.",
                    stacklevel=4,
                )
            return

        if self.fallback is not None and self._using_fallback:
            # Fallback is active — enforce the hard cap.
            # Default hard cap = effective_limit * 2 if not explicitly set (runaway protection).
            effective_hard_cap = self.hard_cap
            if effective_hard_cap is None:
                effective_hard_cap = effective_limit * 2.0

            if self._spent > effective_hard_cap:
                self._emit_budget_exceeded_event()
                raise BudgetExceededError(
                    self._spent,
                    effective_hard_cap,
                    self._last_model,
                    self._last_tokens,
                )

            # Under hard cap — warn once per entry into this branch
            warnings.warn(
                f"shekel: fallback model '{self.fallback}' has exceeded the primary budget "
                f"(${self._spent:.4f} spent, primary limit ${effective_limit:.2f}). "
                f"Hard cap: ${effective_hard_cap:.2f}. "
                f"Use hard_cap= to override.",
                stacklevel=4,
            )
            return

        # No fallback — standard raise
        self._emit_budget_exceeded_event()
        raise BudgetExceededError(self._spent, effective_limit, self._last_model, self._last_tokens)

    def _emit_fallback_activated_event(self) -> None:
        """Emit fallback activated event to adapters."""
        try:
            from shekel.integrations import AdapterRegistry

            AdapterRegistry.emit_event(
                "on_fallback_activated",
                {
                    "from_model": self._last_model,
                    "to_model": self.fallback,
                    "switched_at": self._switched_at_usd,
                    "cost_primary": self._switched_at_usd,
                    "cost_fallback": 0.0,  # Just activated
                    "savings": 0.0,  # Will be calculated over time
                },
            )
        except Exception:
            # Don't break budget enforcement if adapter system fails
            pass

    def _emit_budget_exceeded_event(self) -> None:
        """Emit budget exceeded event to adapters."""
        try:
            from shekel.integrations import AdapterRegistry

            effective_limit = self._effective_limit or 0.0
            parent_remaining = None
            if self.parent is not None:
                parent_remaining = self.parent.remaining

            AdapterRegistry.emit_event(
                "on_budget_exceeded",
                {
                    "budget_name": self.full_name,
                    "spent": self._spent,
                    "limit": effective_limit,
                    "overage": self._spent - effective_limit,
                    "model": self._last_model,
                    "tokens": self._last_tokens,
                    "parent_remaining": parent_remaining,
                },
            )
        except Exception:
            # Don't break budget enforcement if adapter system fails
            pass

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def spent(self) -> float:
        """Total USD spent so far in this context."""
        return self._spent

    @property
    def remaining(self) -> float | None:
        """Remaining USD budget (based on effective limit), or None if track-only mode."""
        if self._effective_limit is None:
            return None
        return max(0.0, self._effective_limit - self._spent)

    @property
    def limit(self) -> float | None:
        """The effective limit (auto-capped if nested), or None if track-only mode."""
        return self._effective_limit

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

    # --- NEW in v0.2.3 (Decision #11): Rich introspection API ---

    @property
    def full_name(self) -> str:
        """Hierarchical path name (e.g., 'workflow.research.api_calls')."""
        if self.parent is None:
            return self.name or "unnamed"
        return f"{self.parent.full_name}.{self.name or 'unnamed'}"

    @property
    def spent_direct(self) -> float:
        """Direct spend by this budget (excluding children)."""
        return self._spent_direct

    @property
    def spent_by_children(self) -> float:
        """Sum of all child spend."""
        return self._spent - self._spent_direct

    def tree(self, _indent: int = 0) -> str:
        """
        Visual hierarchy of budget tree with spend breakdown.

        Active children are shown with [ACTIVE] marker but no spend details
        (Decision #27 - consistent with transparent model).
        """
        lines = []
        prefix = "  " * _indent

        # Show this budget
        if self.active_child is not None:
            # This budget has an active child - show name only
            lines.append(f"{prefix}{self.name or 'unnamed'}")
        else:
            # Budget completed - show full details
            limit_str = (
                f"${self._effective_limit:.2f}"
                if self._effective_limit is not None
                else "track-only"
            )
            lines.append(
                f"{prefix}{self.name or 'unnamed'}: "
                f"${self._spent:.2f} / {limit_str} "
                f"(direct: ${self._spent_direct:.2f})"
            )

        # Show children
        for child in self.children:
            if child == self.active_child:
                # Active child - show name with marker, no spend (Decision #27)
                lines.append(f"{prefix}  {child.name or 'unnamed'} [ACTIVE]")
            else:
                # Completed child - recurse
                lines.append(child.tree(_indent=_indent + 1))

        return "\n".join(lines)

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
