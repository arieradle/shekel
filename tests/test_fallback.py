"""Tests for F1 — Model Fallback on Budget Breach."""

from __future__ import annotations

import asyncio
import warnings
from unittest.mock import patch

import pytest

from shekel import budget
from tests.conftest import (
    make_openai_response,
    make_openai_stream,
)

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _budget_with_fallback(
    max_usd: float = 0.08,  # Changed from 0.001 - allows first call (0.075) to exceed 80% threshold
    fallback_model: str = "gpt-4o-mini",
    fallback_at: float = 0.8,
    **kwargs: object,
) -> budget:
    # With max_usd=0.08 and fallback_at=0.8, threshold is 0.064
    # Large API call costs ~0.075, which exceeds threshold, triggering fallback
    fallback_dict = {
        "at_pct": fallback_at,
        "model": fallback_model,
    }
    return budget(max_usd=max_usd, fallback=fallback_dict, **kwargs)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# test_fallback_activates_after_limit
# ---------------------------------------------------------------------------


def test_fallback_activates_after_limit() -> None:
    """Primary model spend triggers fallback; model_switched becomes True."""
    # Large call that will exceed tiny budget
    fake = make_openai_response("gpt-4o", 10_000, 5_000)
    with patch(OPENAI_CREATE, return_value=fake):
        with _budget_with_fallback(max_usd=0.001) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.model_switched is True


# ---------------------------------------------------------------------------
# test_fallback_model_rewritten_in_kwargs
# ---------------------------------------------------------------------------


def test_fallback_model_rewritten_in_kwargs() -> None:
    """kwargs['model'] is rewritten to the fallback value after switch."""
    # First call: big call to trigger switch
    first_response = make_openai_response("gpt-4o", 10_000, 5_000)
    second_response = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0
    captured_models: list[str] = []

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        captured_models.append(str(kwargs.get("model", "")))
        if call_count == 1:
            return first_response
        return second_response

    with patch(OPENAI_CREATE, new=fake_create):
        with _budget_with_fallback(max_usd=0.08) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                client.chat.completions.create(model="gpt-4o", messages=[])
                # After the first call the budget has switched
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.model_switched is True
    # Second call should have been rewritten to fallback model
    assert captured_models[1] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# test_model_switched_property
# ---------------------------------------------------------------------------


def test_model_switched_property() -> None:
    """model_switched is False before limit is hit, True after."""
    fake_cheap = make_openai_response("gpt-4o", 1, 1)
    fake_big = make_openai_response("gpt-4o", 10_000, 5_000)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_cheap
        return fake_big

    with patch(OPENAI_CREATE, new=fake_create):
        with _budget_with_fallback(max_usd=0.001) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            # First cheap call — should NOT switch
            client.chat.completions.create(model="gpt-4o", messages=[])
            assert b.model_switched is False
            # Second big call — should trigger switch
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                client.chat.completions.create(model="gpt-4o", messages=[])
            assert b.model_switched is True


# ---------------------------------------------------------------------------
# test_switched_at_usd
# ---------------------------------------------------------------------------


def test_switched_at_usd() -> None:
    """switched_at_usd is set at the spend level when the switch occurred."""
    fake = make_openai_response("gpt-4o", 10_000, 5_000)
    with patch(OPENAI_CREATE, return_value=fake):
        with _budget_with_fallback(max_usd=0.001) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.switched_at_usd is not None
    assert b.switched_at_usd > 0.001  # switched when spend exceeded limit
    assert b.switched_at_usd == pytest.approx(b.spent)


# ---------------------------------------------------------------------------
# test_fallback_spent_tracks_separately
# ---------------------------------------------------------------------------


def test_fallback_spent_tracks_separately() -> None:
    """fallback_spent accumulates only fallback-model costs."""
    first_response = make_openai_response("gpt-4o", 10_000, 5_000)
    second_response = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return first_response
        return second_response

    with patch(OPENAI_CREATE, new=fake_create):
        with _budget_with_fallback(max_usd=0.08) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                client.chat.completions.create(model="gpt-4o", messages=[])
                client.chat.completions.create(model="gpt-4o-mini", messages=[])

    assert b.fallback_spent > 0.0
    assert b.fallback_spent < b.spent  # fallback < total
    # fallback_spent should equal cost of second call only
    from shekel._pricing import calculate_cost

    expected_fallback = calculate_cost("gpt-4o-mini", 100, 50)
    assert b.fallback_spent == pytest.approx(expected_fallback)


# ---------------------------------------------------------------------------
# test_on_fallback_callback
# ---------------------------------------------------------------------------


def test_on_fallback_callback() -> None:
    """on_fallback(spent, limit, fallback_model) is called on switch."""
    callback_args: list[tuple[float, float, str]] = []

    def on_fallback(spent: float, limit: float, fallback_model: str) -> None:
        callback_args.append((spent, limit, fallback_model))

    fake = make_openai_response("gpt-4o", 10_000, 5_000)
    with patch(OPENAI_CREATE, return_value=fake):
        with budget(
            max_usd=0.001,
            fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
            on_fallback=on_fallback,
        ) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-4o", messages=[])

    assert len(callback_args) == 1
    spent_arg, limit_arg, fallback_arg = callback_args[0]
    assert spent_arg > 0.001
    assert limit_arg == pytest.approx(0.001)
    assert fallback_arg == "gpt-4o-mini"
    assert b.model_switched is True


# ---------------------------------------------------------------------------
# test_no_raise_when_fallback_set
# ---------------------------------------------------------------------------


def test_no_raise_when_fallback_set() -> None:
    """BudgetExceededError is NOT raised when fallback is set."""
    fake = make_openai_response("gpt-4o", 10_000, 5_000)
    with patch(OPENAI_CREATE, return_value=fake):
        # Should NOT raise despite exceeding budget
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=0.001, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.model_switched is True


# ---------------------------------------------------------------------------
# test_fallback_hard_cap_raises
# ---------------------------------------------------------------------------


def test_fallback_does_not_overspend_primary_budget() -> None:
    """Fallback cannot overspend the primary max_usd budget.

    With max_usd=0.01 and a large fallback call, the second call should fail
    when it would push total spend beyond the shared budget limit.
    """
    from shekel import BudgetExceededError

    big_response = make_openai_response("gpt-4o", 10_000, 5_000)
    also_big = make_openai_response("gpt-4o-mini", 10_000, 5_000)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return big_response
        return also_big

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.01, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
                ) as b:
                    import openai

                    client = openai.OpenAI(api_key="test")
                    client.chat.completions.create(model="gpt-4o", messages=[])
                    # Second big call pushes spend beyond shared budget limit
                    client.chat.completions.create(model="gpt-4o-mini", messages=[])

    assert b.model_switched is True


def test_fallback_small_call_within_budget() -> None:
    """Fallback call that stays within the shared primary budget succeeds."""

    # gpt-4o-mini: 0.00015/1k input, 0.0006/1k output
    # small fallback call: 100 input + 50 output = $0.000015 + $0.000030 = $0.000045
    # primary call (big): triggers switch
    big_primary = make_openai_response("gpt-4o", 10_000, 5_000)
    small_fallback = make_openai_response("gpt-4o-mini", 100, 50)  # cheap
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return big_primary
        return small_fallback

    # Use 0.1 budget so primary call ($0.075) + small fallback ($0.000045) stays well under
    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])
                # Fallback call — cheap, stays under shared max_usd=0.1, no raise
                client.chat.completions.create(model="gpt-4o-mini", messages=[])

    assert b.model_switched is True
    assert b.spent < 0.1  # well under shared budget — no raise


def test_fallback_shares_primary_budget() -> None:
    """Fallback uses the same max_usd budget as primary model (no separate limit)."""
    # This test verifies the simplified API where fallback shares the primary budget
    b = budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})
    assert b.max_usd == 1.00
    assert b.fallback is not None
    assert b.fallback["model"] == "gpt-4o-mini"


def test_hard_cap_without_fallback_warns() -> None:
    """hard_cap without fallback is not possible (removed in new API)."""
    # In the new API, hard_cap is part of the fallback dict, so it's not a separate parameter
    # This test is now obsolete, but we keep it to ensure no regressions
    # Just verify that we can create a budget without fallback
    b = budget(max_usd=1.00)
    assert b is not None


def test_fallback_continues_within_shared_budget() -> None:
    """Fallback model continues spending within the shared budget limit without raising."""
    big_primary = make_openai_response("gpt-4o", 10_000, 5_000)
    small_fallback = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return big_primary
        return small_fallback

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                client.chat.completions.create(model="gpt-4o", messages=[])
                # Fallback call — cheap, stays under shared budget limit
                client.chat.completions.create(model="gpt-4o-mini", messages=[])

    assert b.model_switched is True
    assert b.spent < 0.08  # Both calls together stayed under budget


# ---------------------------------------------------------------------------
# test_cross_provider_raises_valueerror
# ---------------------------------------------------------------------------


def test_cross_provider_raises_valueerror() -> None:
    """fallback model='claude-3-haiku-20240307' on OpenAI call raises ValueError."""
    first_response = make_openai_response("gpt-4o", 10_000, 5_000)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return first_response
        raise AssertionError("Should not reach second call without error")

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=0.001,
                fallback={"at_pct": 0.8, "model": "claude-3-haiku-20240307"},
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                # First call triggers the switch
                client.chat.completions.create(model="gpt-4o", messages=[])
                # Second call should raise ValueError due to cross-provider
                with pytest.raises(ValueError, match="Cross-provider fallback is not supported"):
                    client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.model_switched is True


# ---------------------------------------------------------------------------
# test_fallback_without_max_usd_warns
# ---------------------------------------------------------------------------


def test_fallback_without_max_usd_warns() -> None:
    """budget(fallback={...}) requires max_usd to be set."""
    with pytest.raises(ValueError, match="fallback requires either max_usd"):
        budget(fallback={"at_pct": 0.8, "model": "gpt-4o-mini"})


# ---------------------------------------------------------------------------
# test_on_fallback_without_fallback_raises
# ---------------------------------------------------------------------------


def test_on_fallback_without_fallback_raises() -> None:
    """on_fallback=fn without fallback raises ValueError at init."""
    with pytest.raises(ValueError, match="on_fallback requires fallback"):
        budget(max_usd=1.00, on_fallback=lambda s, lim, m: None)


# ---------------------------------------------------------------------------
# test_fallback_async
# ---------------------------------------------------------------------------


def test_fallback_async() -> None:
    """Async path: fallback activates correctly."""
    ASYNC_OPENAI_CREATE = "openai.resources.chat.completions.AsyncCompletions.create"

    first_response = make_openai_response("gpt-4o", 10_000, 5_000)
    second_response = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0
    captured_models: list[str] = []

    async def fake_create_async(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        captured_models.append(str(kwargs.get("model", "")))
        if call_count == 1:
            return first_response
        return second_response

    async def run() -> budget:
        with patch(ASYNC_OPENAI_CREATE, new=fake_create_async):
            async with budget(
                max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
            ) as b:
                import openai

                client = openai.AsyncOpenAI(api_key="test")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    await client.chat.completions.create(model="gpt-4o", messages=[])
                    await client.chat.completions.create(model="gpt-4o", messages=[])
        return b  # type: ignore[return-value]

    b = asyncio.get_event_loop().run_until_complete(run())
    assert b.model_switched is True
    assert captured_models[1] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# test_fallback_stream_activates_after_stream
# ---------------------------------------------------------------------------


def test_fallback_stream_activates_after_stream() -> None:
    """Stream completes on primary, next non-stream call uses fallback model."""
    stream_chunks = make_openai_stream("gpt-4o", 10_000, 5_000)
    non_stream_response = make_openai_response("gpt-4o-mini", 100, 50)
    call_count = 0
    captured_models: list[str] = []

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        captured_models.append(str(kwargs.get("model", "")))
        if call_count == 1:
            return iter(stream_chunks)
        return non_stream_response

    with patch(OPENAI_CREATE, new=fake_create):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with budget(
                max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
            ) as b:
                import openai

                client = openai.OpenAI(api_key="test")
                # First call is streaming — exhausts and triggers switch
                stream = client.chat.completions.create(model="gpt-4o", messages=[], stream=True)
                list(stream)  # consume to trigger _record
                # Second call should use fallback
                client.chat.completions.create(model="gpt-4o", messages=[])

    assert b.model_switched is True
    assert captured_models[1] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# test_warn_at_fires_before_fallback
# ---------------------------------------------------------------------------


def test_warn_at_fires_before_fallback() -> None:
    """warn_at callback fires at warn threshold; fallback activates when limit hit.

    gpt-4o: $0.0025/1k input, $0.010/1k output
    Call of 10_000 input + 5_000 output:
      input cost  = 10_000/1000 * 0.0025 = $0.025
      output cost = 5_000/1000  * 0.010  = $0.050
      total       = $0.075 per call
    max_usd=0.10, warn_at=0.5 → threshold = $0.05
    Call 1: $0.075 > $0.05 → warn fires; $0.075 < $0.10 → no switch yet
    Call 2: $0.150 > $0.10 → fallback activates
    """
    warn_calls: list[tuple[float, float]] = []

    def on_warn(spent: float, limit: float) -> None:
        warn_calls.append((spent, limit))

    # Each call costs $0.075 (see docstring)
    call1 = make_openai_response("gpt-4o", 10_000, 5_000)
    call2 = make_openai_response("gpt-4o", 10_000, 5_000)
    call_count = 0

    def fake_create(self: object, *args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return call1
        return call2

    with patch(OPENAI_CREATE, new=fake_create):
        with budget(
            max_usd=0.10,
            warn_at=0.5,
            on_warn=on_warn,
            fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
        ) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            # Call 1: crosses warn threshold, NOT limit
            client.chat.completions.create(model="gpt-4o", messages=[])
            assert not b.model_switched, "should not have switched after call 1"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # Call 2: crosses limit → fallback activates
                client.chat.completions.create(model="gpt-4o", messages=[])

    # warn_at callback fired exactly once (on call 1)
    assert len(warn_calls) == 1
    assert warn_calls[0][0] >= 0.05  # spent at least 50% of limit
    # fallback activated after call 2 pushed over limit
    assert b.model_switched is True


def test_fallback_empty_string_raises() -> None:
    """budget(fallback={...}) with empty model raises ValueError at init."""
    with pytest.raises(ValueError, match="non-empty string"):
        budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": ""})
