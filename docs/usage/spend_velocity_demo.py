"""
spend_velocity_demo.py — runnable example for the Spend Velocity feature.

Demonstrates:
- Velocity guard firing on bursty LLM usage
- warn_velocity warning threshold firing first
- Velocity-only mode (no max_usd)
- Compound guardrails: max_usd + max_velocity

No real API key needed — LLM spend is simulated directly.
"""

from __future__ import annotations

import time

from shekel import budget
from shekel.exceptions import BudgetExceededError, SpendVelocityExceededError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_spend(b: budget, usd: float) -> None:  # type: ignore[name-defined]
    """Push a fake LLM cost event into the active shekel budget."""
    b._record_cost(usd, model="gpt-4o-mini", input_tokens=500, output_tokens=500)  # type: ignore[attr-defined]


def bursty_llm_calls(b: budget, calls: int = 10, spend_per_call: float = 0.25) -> None:  # type: ignore[name-defined]
    """Simulate rapid-fire LLM calls — each call spends USD immediately."""
    for i in range(calls):
        _record_spend(b, spend_per_call)
        print(f"  Call {i + 1}: ${spend_per_call:.2f} (total: ${b.spent:.4f})")


# ---------------------------------------------------------------------------
# Demo 1: Velocity guard fires — burst of calls exceeds $0.50/min
# ---------------------------------------------------------------------------


def demo_velocity_guard() -> None:
    print("=== Demo 1: Velocity guard fires on bursty spend ===")

    try:
        with budget(max_velocity="$0.50/min") as b:
            # Each call costs $0.25. After the 3rd call the velocity crosses $0.50/min.
            bursty_llm_calls(b, calls=10, spend_per_call=0.25)
            print("This line should not be reached — velocity guard should have fired")

    except SpendVelocityExceededError as e:
        print(f"\nCaught SpendVelocityExceededError:")
        print(f"  velocity_per_min: ${e.velocity_per_min:.4f}/min")
        print(f"  limit_per_min:    ${e.limit_per_min:.4f}/min")
        print(f"  usd_spent:        ${e.usd_spent:.4f}")
        print(f"  elapsed_seconds:  {e.elapsed_seconds:.2f}s")
    except BudgetExceededError as e:
        print(f"Budget exceeded (unexpected type): {e}")

    print()


# ---------------------------------------------------------------------------
# Demo 2: warn_velocity fires first, then hard stop
# ---------------------------------------------------------------------------


def demo_velocity_warning() -> None:
    print("=== Demo 2: warn_velocity fires before the hard stop ===")

    warnings_fired = []

    def on_warn(current_rate: float, limit_rate: float) -> None:
        warnings_fired.append((current_rate, limit_rate))
        print(f"  [WARN] Velocity ${current_rate:.4f}/min approaching limit ${limit_rate:.4f}/min")

    try:
        with budget(
            max_velocity="$1.00/min",
            warn_velocity="$0.50/min",  # warn at half the limit
            on_warn=on_warn,
        ) as b:
            bursty_llm_calls(b, calls=10, spend_per_call=0.20)
            print("This line should not be reached")

    except SpendVelocityExceededError as e:
        print(f"\nHard stop at ${e.velocity_per_min:.4f}/min")
        print(f"Warnings fired: {len(warnings_fired)}")
    except BudgetExceededError as e:
        print(f"Budget exceeded (unexpected type): {e}")

    print()


# ---------------------------------------------------------------------------
# Demo 3: Velocity-only mode — no max_usd
# ---------------------------------------------------------------------------


def demo_velocity_only() -> None:
    print("=== Demo 3: Velocity-only guard (no max_usd) ===")

    try:
        with budget(max_velocity="$0.30/min") as b:
            # Just a velocity guard — no total cap
            bursty_llm_calls(b, calls=10, spend_per_call=0.15)
            print("This line should not be reached")

    except SpendVelocityExceededError as e:
        print(f"\nVelocity-only guard fired: ${e.velocity_per_min:.4f}/min > ${e.limit_per_min:.4f}/min")
        print(f"Total spent before block: ${e.usd_spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded (unexpected type): {e}")

    print()


# ---------------------------------------------------------------------------
# Demo 4: Compound guardrails — max_usd + max_velocity
# ---------------------------------------------------------------------------


def demo_compound_guardrails() -> None:
    print("=== Demo 4: Compound guardrails — max_usd=$50 + max_velocity=$1/min ===")

    print("Scenario A: velocity fires first (fast burst)")
    try:
        with budget(max_usd=50.00, max_velocity="$1.00/min") as b:
            bursty_llm_calls(b, calls=10, spend_per_call=0.30)  # $3/min burst rate
            print("This line should not be reached")
    except SpendVelocityExceededError as e:
        print(f"  Velocity fired: ${e.velocity_per_min:.4f}/min (total: ${e.usd_spent:.4f})")
    except BudgetExceededError as e:
        print(f"  Total cap fired: ${e.spent:.4f}")
    print()

    print("Scenario B: total cap fires first (slow steady spend)")
    try:
        with budget(max_usd=1.00, max_velocity="$100/min") as b:
            # Slow enough to not trigger velocity, but total cap is tight
            for i in range(20):
                _record_spend(b, 0.10)
                time.sleep(0.001)  # tiny pause to keep velocity low
        print("Completed without error (unexpected)")
    except BudgetExceededError as e:
        if isinstance(e, SpendVelocityExceededError):
            print(f"  Velocity fired unexpectedly: ${e.velocity_per_min:.4f}/min")
        else:
            print(f"  Total cap fired: ${e.spent:.4f} > ${e.limit:.2f}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    demo_velocity_guard()
    demo_velocity_warning()
    demo_velocity_only()
    demo_compound_guardrails()
    print("=== All demos complete ===")


if __name__ == "__main__":
    main()
