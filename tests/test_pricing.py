from __future__ import annotations

import sys
import warnings
from unittest.mock import MagicMock, patch

import pytest

from shekel._pricing import UnknownModelError, calculate_cost, list_models

# ---------------------------------------------------------------------------
# Prefix model name resolution
# ---------------------------------------------------------------------------


def test_versioned_openai_model_resolves_via_prefix() -> None:
    # gpt-4o-2024-08-06 should resolve to gpt-4o pricing
    cost_versioned = calculate_cost("gpt-4o-2024-08-06", 1000, 1000)
    cost_base = calculate_cost("gpt-4o", 1000, 1000)
    assert cost_versioned == pytest.approx(cost_base)


def test_versioned_anthropic_model_resolves_via_prefix() -> None:
    # claude-3-5-sonnet-20241022-preview should resolve to claude-3-5-sonnet-20241022
    cost_versioned = calculate_cost("claude-3-5-sonnet-20241022-preview", 500, 200)
    cost_base = calculate_cost("claude-3-5-sonnet-20241022", 500, 200)
    assert cost_versioned == pytest.approx(cost_base)


def test_prefix_picks_longest_match() -> None:
    # Both "gpt-4o" and "gpt-4o-mini" are in prices.json
    # "gpt-4o-mini-2024-07-18" should match "gpt-4o-mini", not "gpt-4o"
    cost = calculate_cost("gpt-4o-mini-2024-07-18", 1000, 1000)
    cost_mini = calculate_cost("gpt-4o-mini", 1000, 1000)
    cost_4o = calculate_cost("gpt-4o", 1000, 1000)
    assert cost == pytest.approx(cost_mini)
    assert cost != pytest.approx(cost_4o)


def test_exact_match_beats_prefix() -> None:
    # An exact match in prices.json should not fall through to prefix lookup
    cost_exact = calculate_cost("gpt-4o", 1000, 1000)
    assert cost_exact == pytest.approx(0.0025 + 0.010)


# ---------------------------------------------------------------------------
# Bundled model pricing
# ---------------------------------------------------------------------------


def test_known_model_cost() -> None:
    cost = calculate_cost("gpt-4o", 1000, 1000)
    assert cost == pytest.approx(0.0025 + 0.010)


def test_known_model_zero_tokens() -> None:
    assert calculate_cost("gpt-4o", 0, 0) == 0.0


def test_known_model_only_input() -> None:
    cost = calculate_cost("gpt-4o", 500, 0)
    assert cost == pytest.approx(500 / 1000 * 0.0025)


def test_known_model_only_output() -> None:
    cost = calculate_cost("gpt-4o", 0, 200)
    assert cost == pytest.approx(200 / 1000 * 0.010)


def test_bundled_model_used_without_tokencost() -> None:
    """Known model resolves from prices.json even when tokencost is unavailable."""
    with patch.dict(sys.modules, {"tokencost": None}):
        cost = calculate_cost("gpt-4o", 1000, 500)
    assert cost > 0.0


# ---------------------------------------------------------------------------
# Price override
# ---------------------------------------------------------------------------


def test_price_override_used() -> None:
    override = {"input": 0.001, "output": 0.002}
    cost = calculate_cost("gpt-999-fake", 1000, 1000, price_override=override)
    assert cost == pytest.approx(0.001 + 0.002)


def test_price_override_ignores_unknown_model() -> None:
    override = {"input": 0.005, "output": 0.015}
    cost = calculate_cost("some-private-model", 500, 500, price_override=override)
    assert cost == pytest.approx(500 / 1000 * 0.005 + 500 / 1000 * 0.015)


def test_price_override_takes_precedence_over_tokencost() -> None:
    fake_tokencost = MagicMock()
    fake_tokencost.cost_per_token.return_value = 9999.0

    with patch.dict(sys.modules, {"tokencost": fake_tokencost}):
        cost = calculate_cost("gpt-4o", 1000, 500, price_override={"input": 0.001, "output": 0.002})

    expected = (1000 / 1000.0 * 0.001) + (500 / 1000.0 * 0.002)
    assert cost == pytest.approx(expected)
    fake_tokencost.cost_per_token.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown model — warns and returns 0.0
# ---------------------------------------------------------------------------


def test_unknown_model_warns_and_returns_zero() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cost = calculate_cost("gpt-999-fake", 100, 100)
    assert cost == 0.0
    assert len(w) == 1
    assert "gpt-999-fake" in str(w[0].message)


def test_unknown_model_string_warns_and_returns_zero() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cost = calculate_cost("unknown", 100, 100)
    assert cost == 0.0
    assert len(w) == 1


def test_unknown_model_without_tokencost_warns() -> None:
    with patch.dict(sys.modules, {"tokencost": None}):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cost = calculate_cost("completely-unknown-model-abc123", 1000, 500)
    assert cost == 0.0
    assert len(w) == 1
    assert issubclass(w[0].category, UserWarning)
    assert "not found in bundled prices" in str(w[0].message)


# ---------------------------------------------------------------------------
# tokencost integration (tier 3)
# ---------------------------------------------------------------------------


def test_tokencost_used_for_unknown_model() -> None:
    fake_tokencost = MagicMock()
    fake_tokencost.cost_per_token.return_value = 0.000001

    with patch.dict(sys.modules, {"tokencost": fake_tokencost}):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cost = calculate_cost("some-exotic-model-xyz", 1000, 500)

    assert cost == pytest.approx(0.000001 * 1000 + 0.000001 * 500)
    assert not any("not found" in str(warning.message) for warning in w)


def test_tokencost_exception_falls_through_to_warn() -> None:
    fake_tokencost = MagicMock()
    fake_tokencost.cost_per_token.side_effect = Exception("unknown model")
    fake_tokencost.TOKEN_COSTS = {}

    with patch.dict(sys.modules, {"tokencost": fake_tokencost}):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cost = calculate_cost("completely-unknown-model-xyz999", 1000, 500)

    assert cost == 0.0
    assert any("not found in bundled prices" in str(warning.message) for warning in w)


def test_tokencost_key_error_falls_through_to_warn() -> None:
    fake_tokencost = MagicMock()
    fake_tokencost.cost_per_token.side_effect = KeyError("model not found")
    fake_tokencost.TOKEN_COSTS = {}

    with patch.dict(sys.modules, {"tokencost": fake_tokencost}):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cost = calculate_cost("another-mystery-model", 100, 100)

    assert cost == 0.0
    assert any("not found" in str(warning.message) for warning in w)


def test_tokencost_token_costs_dict_fallback() -> None:
    import types

    from shekel._pricing import _try_tokencost

    fake_tokencost = types.ModuleType("tokencost")

    def bad_cost_per_token(model: str, token_type: str) -> float:
        raise RuntimeError("not available")

    fake_tokencost.cost_per_token = bad_cost_per_token  # type: ignore[attr-defined]
    fake_tokencost.TOKEN_COSTS = {  # type: ignore[attr-defined]
        "my-custom-model": {"prompt": 0.000001, "completion": 0.000002}
    }

    original = sys.modules.get("tokencost")
    sys.modules["tokencost"] = fake_tokencost
    try:
        result = _try_tokencost("my-custom-model", 1000, 500)
        assert result is not None
        assert result == pytest.approx(1000 * 0.000001 + 500 * 0.000002)
    finally:
        if original is None:
            sys.modules.pop("tokencost", None)
        else:
            sys.modules["tokencost"] = original


def test_tokencost_token_costs_dict_raises_falls_through() -> None:
    """TOKEN_COSTS.get() itself raises — caught by except Exception: pass."""
    import types

    fake_tokencost = types.ModuleType("tokencost")

    def bad_cost_per_token(model: str, token_type: str) -> float:
        raise RuntimeError("unavailable")

    fake_tokencost.cost_per_token = bad_cost_per_token  # type: ignore[attr-defined]
    # Make TOKEN_COSTS.get raise too
    mock_costs = MagicMock()
    mock_costs.get.side_effect = RuntimeError("broken dict")
    fake_tokencost.TOKEN_COSTS = mock_costs  # type: ignore[attr-defined]

    original = sys.modules.get("tokencost")
    sys.modules["tokencost"] = fake_tokencost
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            cost = calculate_cost("mystery-model-broken", 100, 100)
        assert cost == 0.0
        assert any("not found" in str(warning.message) for warning in w)
    finally:
        if original is None:
            sys.modules.pop("tokencost", None)
        else:
            sys.modules["tokencost"] = original


def test_tokencost_not_imported_at_module_level() -> None:
    sys.modules.pop("tokencost", None)
    import shekel  # noqa: F401

    assert "tokencost" not in sys.modules


# ---------------------------------------------------------------------------
# UnknownModelError (kept for backwards compatibility)
# ---------------------------------------------------------------------------


def test_unknown_model_error_contains_model_name() -> None:
    err = UnknownModelError("my-custom-model")
    assert "my-custom-model" in str(err)
    assert "price_per_1k_tokens" in str(err)


# ---------------------------------------------------------------------------
# prices.json schema and model list
# ---------------------------------------------------------------------------


def test_prices_json_schema() -> None:
    from shekel._pricing import _PRICES

    for model, entry in _PRICES.items():
        assert "input_per_1k" in entry, f"{model} missing input_per_1k"
        assert "output_per_1k" in entry, f"{model} missing output_per_1k"
        assert entry["input_per_1k"] >= 0
        assert entry["output_per_1k"] >= 0


def test_list_models_returns_ten() -> None:
    assert len(list_models()) == 13


def test_anthropic_model_in_list() -> None:
    assert "claude-3-5-sonnet-20241022" in list_models()
