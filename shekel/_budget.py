from __future__ import annotations

import math
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

    Usage::

        # Track-only mode (no enforcement):
        with budget() as b:
            response = openai_client.chat.completions.create(...)
        print(f"This run cost: ${b.spent:.4f}")

        # Cap by USD:
        with budget(max_usd=1.00) as b:
            response = openai_client.chat.completions.create(...)

        # Cap by call count:
        with budget(max_llm_calls=50) as b:
            run_agent()

        # Graceful degradation — switch to cheaper model at 80% of budget:
        with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
            run_agent()
        print(b.model_switched)   # True if switch occurred
        print(b.summary())

        # Session budget (accumulates across multiple with-blocks):
        session = budget(max_usd=5.00)
        with session:
            respond(turn_1)
        with session:
            respond(turn_2)   # spend accumulates

    Note: Budget objects are not thread-safe when shared across threads or
    concurrent asyncio tasks. Each thread/task should use its own budget instance.
    """

    def __init__(
        self,
        max_usd: float | None = None,
        warn_at: float | None = None,
        on_warn: Callable[[float, float], None] | None = None,
        price_per_1k_tokens: dict[str, float] | None = None,
        fallback: dict[str, Any] | None = None,
        on_fallback: Callable[[float, float, str], None] | None = None,
        name: str | None = None,
        max_llm_calls: int | None = None,
    ) -> None:

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

        if fallback is not None:
            if not isinstance(fallback, dict):
                raise ValueError(
                    "fallback must be a dict with keys: 'at_pct' (float), 'model' (str). "
                    f"Got: {type(fallback).__name__}"
                )
            required_keys = {"at_pct", "model"}
            provided_keys = set(fallback.keys())
            if not required_keys.issubset(provided_keys):
                missing = required_keys - provided_keys
                raise ValueError(
                    f"fallback dict missing required keys: {missing}. "
                    f"Required: 'at_pct', 'model'"
                )

            # Validate 'at_pct' (activation percentage — 0 exclusive, 1 inclusive)
            at_value = fallback["at_pct"]
            if not isinstance(at_value, (int, float)) or not (0.0 < at_value <= 1.0):
                raise ValueError(
                    f"fallback['at_pct'] must be a fraction between 0 and 1 "
                    f"(exclusive 0, inclusive 1), got {at_value}"
                )

            # Validate 'model' (non-empty string)
            model_value = fallback["model"]
            if not isinstance(model_value, str) or model_value == "":
                raise ValueError(
                    f"fallback['model'] must be a non-empty string, got {repr(model_value)}"
                )

            # Require at least one limit so fallback has something to threshold against
            if max_usd is None and max_llm_calls is None:
                raise ValueError("fallback requires either max_usd or max_llm_calls to be set")

        if on_fallback is not None and fallback is None:
            raise ValueError("on_fallback requires fallback to be set")

        if max_llm_calls is not None and max_llm_calls <= 0:
            raise ValueError(
                "max_llm_calls must be positive or None for track-only mode. "
                f"Got: {max_llm_calls}"
            )

        self.max_usd = max_usd
        self.warn_at = warn_at
        self.on_warn = on_warn
        self.price_per_1k_tokens = price_per_1k_tokens
        self.fallback: dict[str, Any] | None = fallback
        self.on_fallback = on_fallback

        # --- Nested budget support (v0.2.3) ---
        self.name: str | None = name
        self.parent: Budget | None = None
        self.children: list[Budget] = []
        self.active_child: Budget | None = None
        self._depth: int = 0
        self._effective_limit: float | None = max_usd  # Auto-capped in __enter__ for children

        # --- Call limit support (v0.2.6) ---
        self.max_llm_calls: int | None = max_llm_calls
        self._effective_call_limit: int | None = max_llm_calls  # Auto-capped in __enter__

        self._ctx_token: Token[Budget | None] | None = None

        # Spend-tracking state
        self._spent: float = 0.0
        self._spent_direct: float = 0.0
        self._warn_fired: bool = False
        self._last_model: str = "unknown"
        self._last_tokens: dict[str, int] = {"input": 0, "output": 0}
        self._using_fallback: bool = False
        self._fallback_spent: float = 0.0
        self._switched_at_usd: float | None = None
        self._calls: list[CallRecord] = []
        self._calls_made: int = 0

    # ------------------------------------------------------------------
    # Internal state reset
    # ------------------------------------------------------------------

    def _reset_state(self) -> None:
        """Reset all spend tracking state. Called via reset() between with-blocks."""
        self._spent = 0.0
        self._spent_direct = 0.0
        self._warn_fired = False
        self._last_model = "unknown"
        self._last_tokens = {"input": 0, "output": 0}
        self._using_fallback = False
        self._fallback_spent = 0.0
        self._switched_at_usd = None
        self._calls = []
        self._calls_made = 0

    # ------------------------------------------------------------------
    # Sync context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Budget:
        # Nested budget validation
        current_budget = _context.get_active_budget()
        if current_budget is not None:
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

            if current_budget._depth >= 4:
                raise ValueError(
                    f"Maximum budget nesting depth of 5 exceeded. "
                    f"Current depth: {current_budget._depth}, "
                    f"attempted depth: {current_budget._depth + 1}"
                )

            for existing_child in current_budget.children:
                if existing_child.name == self.name:
                    raise ValueError(
                        f"Child name '{self.name}' already exists under "
                        f"parent '{current_budget.name}'. "
                        f"Sibling budgets must have unique names."
                    )

        # All validation passed — apply patches and wire up hierarchy
        _patch.apply_patches()

        if current_budget is not None:
            self.parent = current_budget
            self._depth = current_budget._depth + 1
            current_budget.children.append(self)
            current_budget.active_child = self

            # Auto-cap child USD limit to parent's remaining budget
            if self.max_usd is not None and current_budget.remaining is not None:
                self._effective_limit = min(self.max_usd, current_budget.remaining)
            else:
                self._effective_limit = self.max_usd

            # Auto-cap child call limit to parent's remaining calls
            if self.max_llm_calls is not None and current_budget.calls_remaining is not None:
                self._effective_call_limit = min(self.max_llm_calls, current_budget.calls_remaining)
            else:
                self._effective_call_limit = self.max_llm_calls
        else:
            self._effective_limit = self.max_usd
            self._effective_call_limit = self.max_llm_calls

        self._ctx_token = _context.set_active_budget(self)
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # Propagate spend and call count to parent on exit
        if self.parent is not None:
            self.parent._spent += self._spent
            self.parent._calls_made += self._calls_made
            self.parent.active_child = None

        if self._ctx_token is not None:
            from shekel._context import _active_budget

            _active_budget.reset(self._ctx_token)
        _patch.remove_patches()
        # returning None (not False) — never suppress exceptions

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Budget:
        current_budget = _context.get_active_budget()
        if current_budget is not None:
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

            if current_budget._depth >= 4:
                raise ValueError(
                    f"Maximum budget nesting depth of 5 exceeded. "
                    f"Current depth: {current_budget._depth}, "
                    f"attempted depth: {current_budget._depth + 1}"
                )

            for existing_child in current_budget.children:
                if existing_child.name == self.name:
                    raise ValueError(
                        f"Child name '{self.name}' already exists under "
                        f"parent '{current_budget.name}'. "
                        f"Sibling budgets must have unique names."
                    )

        _patch.apply_patches()

        if current_budget is not None:
            self.parent = current_budget
            self._depth = current_budget._depth + 1
            current_budget.children.append(self)
            current_budget.active_child = self

            if self.max_usd is not None and current_budget.remaining is not None:
                self._effective_limit = min(self.max_usd, current_budget.remaining)
            else:
                self._effective_limit = self.max_usd

            if self.max_llm_calls is not None and current_budget.calls_remaining is not None:
                self._effective_call_limit = min(self.max_llm_calls, current_budget.calls_remaining)
            else:
                self._effective_call_limit = self.max_llm_calls
        else:
            self._effective_limit = self.max_usd
            self._effective_call_limit = self.max_llm_calls

        self._ctx_token = _context.set_active_budget(self)
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self.parent is not None:
            self.parent._spent += self._spent
            self.parent._calls_made += self._calls_made
            self.parent.active_child = None

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
        # Parent locking: cannot record spend while a child budget is active
        if self.active_child is not None:
            raise RuntimeError(
                f"shekel: Cannot spend on parent budget '{self.name or 'unnamed'}' "
                f"while child budget '{self.active_child.name or 'unnamed'}' is active. "
                f"Wait for child context to exit."
            )

        self._spent += cost
        self._spent_direct += cost
        if self._using_fallback:
            self._fallback_spent += cost
        self._last_model = model
        self._last_tokens = tokens
        self._calls.append(
            CallRecord(
                model=model,
                cost=cost,
                input_tokens=tokens.get("input", 0),
                output_tokens=tokens.get("output", 0),
                fallback=self._using_fallback,
            )
        )
        self._calls_made += 1
        self._check_warn()
        self._check_limit()
        self._check_call_limit()

    def _check_warn(self) -> None:
        effective_limit = self._effective_limit
        if (
            self.warn_at is not None
            and effective_limit is not None
            and not self._warn_fired
            and self._spent >= effective_limit * self.warn_at
        ):
            self._warn_fired = True
            if self.on_warn is not None:
                self.on_warn(self._spent, effective_limit)
            else:
                warnings.warn(
                    f"shekel: ${self._spent:.4f} spent — "
                    f"{self.warn_at * 100:.0f}% of ${effective_limit:.2f} budget reached.",
                    stacklevel=4,
                )

    def _activate_fallback(self, budget_exceeded: bool) -> None:
        """Activate fallback model with warning and adapter event.

        Called from both USD threshold (_check_limit) and call-count threshold
        (_check_call_limit_for_fallback). Centralises activation logic.
        """
        self._using_fallback = True
        self._switched_at_usd = self._spent
        self._emit_fallback_activated_event()
        fallback_model = self.fallback["model"]  # type: ignore[index]
        effective_limit = self._effective_limit
        limit_val = effective_limit if effective_limit is not None else 0
        if self.on_fallback is not None:
            self.on_fallback(self._spent, limit_val, fallback_model)
        else:
            if budget_exceeded:
                warnings.warn(
                    f"shekel: budget of ${limit_val:.2f} exceeded "
                    f"(${self._spent:.4f} spent). "
                    f"Switching to fallback model '{fallback_model}'.",
                    stacklevel=5,
                )
            else:
                warnings.warn(
                    f"shekel: approaching budget limit "
                    f"(${self._spent:.4f} spent of ${limit_val:.2f}). "
                    f"Switching to fallback model '{fallback_model}'.",
                    stacklevel=5,
                )

    def _check_limit(self) -> None:
        """Check USD limit. Activates fallback at threshold; raises if exceeded without fallback."""
        effective_limit = self._effective_limit
        if effective_limit is None:
            return

        budget_exceeded = self._spent > effective_limit
        fallback_threshold_met = (
            self.fallback is not None and self._spent >= effective_limit * self.fallback["at_pct"]
        )

        if (
            (budget_exceeded or fallback_threshold_met)
            and self.fallback is not None
            and not self._using_fallback
        ):
            self._activate_fallback(budget_exceeded=budget_exceeded)
            return  # Fallback just activated — keep running on cheaper model

        if budget_exceeded and (self.fallback is None or self._using_fallback):
            # No fallback available, or already on fallback and still exceeded — raise
            self._emit_budget_exceeded_event()
            raise BudgetExceededError(
                self._spent, effective_limit, self._last_model, self._last_tokens
            )

    def _check_call_limit_for_fallback(self) -> None:
        """Called BEFORE the API call. Activates fallback if call-count threshold is reached.

        Uses math.ceil so that e.g. 10 calls × 0.85 = ceil(8.5) = 9 (not floor 8).
        """
        effective_call_limit = self._effective_call_limit
        if effective_call_limit is None or self.fallback is None or self._using_fallback:
            return

        call_threshold = math.ceil(effective_call_limit * self.fallback["at_pct"])
        if self._calls_made >= call_threshold:
            self._activate_fallback(budget_exceeded=False)

    def _check_call_limit(self) -> None:
        """Called AFTER recording spend. Enforces the hard call limit."""
        effective_call_limit = self._effective_call_limit
        if effective_call_limit is None:
            return

        if self._calls_made > effective_call_limit:
            self._emit_budget_exceeded_event()
            raise BudgetExceededError(
                self._calls_made,
                effective_call_limit,
                self._last_model,
                self._last_tokens,
            )

    def _emit_fallback_activated_event(self) -> None:
        """Emit fallback activated event to adapters."""
        try:
            from shekel.integrations import AdapterRegistry

            fallback_model = self.fallback["model"] if self.fallback else "unknown"
            AdapterRegistry.emit_event(
                "on_fallback_activated",
                {
                    "from_model": self._last_model,
                    "to_model": fallback_model,
                    "switched_at": self._switched_at_usd,
                    "cost_primary": self._switched_at_usd,
                    "cost_fallback": 0.0,
                    "savings": 0.0,
                },
            )
        except Exception:
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

    @property
    def calls_used(self) -> int:
        """Number of LLM calls made in this budget context."""
        return self._calls_made

    @property
    def calls_remaining(self) -> int | None:
        """Remaining call count (based on effective limit), or None if track-only mode."""
        if self._effective_call_limit is None:
            return None
        return max(0, self._effective_call_limit - self._calls_made)

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
        """Visual hierarchy of budget tree with spend breakdown.

        Active children are shown with [ACTIVE] marker but no spend details.
        """
        lines = []
        prefix = "  " * _indent

        if self.active_child is not None:
            lines.append(f"{prefix}{self.name or 'unnamed'}")
        else:
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

        for child in self.children:
            if child == self.active_child:
                lines.append(f"{prefix}  {child.name or 'unnamed'} [ACTIVE]")
            else:
                lines.append(child.tree(_indent=_indent + 1))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary_data(self) -> dict[str, object]:
        """Return structured spend data as a dict."""
        fallback_model: str | None = self.fallback["model"] if self.fallback is not None else None

        by_model: dict[str, dict[str, Any]] = {}
        for call in self._calls:
            m = call["model"]
            if m not in by_model:
                by_model[m] = {
                    "calls": 0,
                    "cost": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "fallback": m == fallback_model,
                }
            by_model[m]["calls"] += 1
            by_model[m]["cost"] += call["cost"]
            by_model[m]["input_tokens"] += call["input_tokens"]
            by_model[m]["output_tokens"] += call["output_tokens"]

        return {
            "total_spent": self._spent,
            "limit": self.max_usd,
            "calls_used": self._calls_made,
            "calls_limit": self.max_llm_calls,
            "model_switched": self._using_fallback,
            "switched_at_usd": self._switched_at_usd,
            "fallback_model": fallback_model,
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
        call_str = (
            f"{self._calls_made} / {self.max_llm_calls} calls"
            if self.max_llm_calls is not None
            else f"{total_calls} calls"
        )

        lines.append("┌─ Shekel Budget Summary " + "─" * (width - 24) + "┐")
        lines.append(
            f"│ Total: ${total_spent:.4f}  Limit: {limit_str}  " f"{call_str}  Status: {status}"
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

        fallback_model_name: str | None = (
            self.fallback["model"] if self.fallback is not None else None
        )
        lines.append("├" + "─" * width + "┤")
        for model, stats in by_model.items():
            role = " (fallback)" if model == fallback_model_name and model_switched else ""
            lines.append(f"│  {model}: {stats['calls']} calls{role}  ${stats['cost']:.4f}")

        if model_switched and switched_at is not None:
            lines.append(f"│  Switched at: ${switched_at:.4f}")

        lines.append("└" + "─" * width + "┘")
        return "\n".join(lines)
