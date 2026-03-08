from __future__ import annotations

import pytest

from shekel._pricing import UnknownModelError, calculate_cost, list_models


def test_known_model_cost() -> None:
    # gpt-4o: input=0.0025/1k, output=0.010/1k
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


def test_unknown_model_raises() -> None:
    with pytest.raises(UnknownModelError) as exc_info:
        calculate_cost("gpt-999-fake", 100, 100)
    assert "gpt-999-fake" in str(exc_info.value)


def test_unknown_model_error_contains_model_name() -> None:
    err = UnknownModelError("my-custom-model")
    assert "my-custom-model" in str(err)
    assert "price_per_1k_tokens" in str(err)


def test_price_override_used() -> None:
    override = {"input": 0.001, "output": 0.002}
    cost = calculate_cost("gpt-999-fake", 1000, 1000, price_override=override)
    assert cost == pytest.approx(0.001 + 0.002)


def test_price_override_ignores_unknown_model() -> None:
    # With override, unknown model should NOT raise
    override = {"input": 0.005, "output": 0.015}
    cost = calculate_cost("some-private-model", 500, 500, price_override=override)
    assert cost == pytest.approx(500 / 1000 * 0.005 + 500 / 1000 * 0.015)


def test_prices_json_schema() -> None:
    """All bundled models have required fields."""
    from shekel._pricing import _PRICES

    for model, entry in _PRICES.items():
        assert "input_per_1k" in entry, f"{model} missing input_per_1k"
        assert "output_per_1k" in entry, f"{model} missing output_per_1k"
        assert entry["input_per_1k"] >= 0
        assert entry["output_per_1k"] >= 0


def test_list_models_returns_ten() -> None:
    models = list_models()
    assert len(models) == 10


def test_anthropic_model_in_list() -> None:
    models = list_models()
    assert "claude-3-5-sonnet-20241022" in models


def test_unknown_model_string_is_always_error() -> None:
    """Model name 'unknown' (the default fallback) raises, not returns $0."""
    with pytest.raises(UnknownModelError):
        calculate_cost("unknown", 100, 100)
