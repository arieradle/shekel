from __future__ import annotations

import json
import os

# Load bundled prices.json at import time
_PRICES_PATH = os.path.join(os.path.dirname(__file__), "prices.json")
with open(_PRICES_PATH) as _f:
    _PRICES: dict[str, dict[str, float]] = json.load(_f)


class UnknownModelError(ValueError):
    """Raised when a model is not in the bundled pricing table and no override is provided."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(
            f"Model '{model}' not found in shekel's pricing table. "
            f"Pass price_per_1k_tokens={{'input': X, 'output': Y}} to budget() to override."
        )


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    price_override: dict[str, float] | None = None,
) -> float:
    """Calculate the cost in USD for a given model call.

    Args:
        model: Model name (e.g. "gpt-4o").
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.
        price_override: Optional dict with 'input' and 'output' keys (price per 1k tokens).

    Returns:
        Cost in USD as a float.

    Raises:
        UnknownModelError: If model not in pricing table and no override provided.
    """
    if price_override is not None:
        input_per_1k = price_override["input"]
        output_per_1k = price_override["output"]
    else:
        if model not in _PRICES:
            raise UnknownModelError(model)
        entry = _PRICES[model]
        input_per_1k = entry["input_per_1k"]
        output_per_1k = entry["output_per_1k"]

    return (input_tokens / 1000.0 * input_per_1k) + (output_tokens / 1000.0 * output_per_1k)


def list_models() -> list[str]:
    """Return list of models with bundled pricing."""
    return list(_PRICES.keys())
