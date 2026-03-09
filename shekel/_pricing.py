from __future__ import annotations

import json
import os
import warnings

# Load bundled prices.json at import time
_PRICES_PATH = os.path.join(os.path.dirname(__file__), "prices.json")
with open(_PRICES_PATH) as _f:
    _PRICES: dict[str, dict[str, float]] = json.load(_f)


class UnknownModelError(ValueError):
    """Raised when a model is not in the bundled pricing table and no override is provided.

    Deprecated: no longer raised by calculate_cost() in v0.2. Preserved for
    backwards compatibility — existing ``except UnknownModelError`` blocks will
    continue to compile. calculate_cost() now emits a UserWarning and returns 0.0
    instead of raising.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(
            f"Model '{model}' not found in shekel's pricing table. "
            f"Pass price_per_1k_tokens={{'input': X, 'output': Y}} to budget() to override."
        )


def _prefix_lookup(model: str) -> dict[str, float] | None:
    """Find the longest bundled model name that is a prefix of the given model string.

    Handles versioned model names like 'gpt-4o-2024-08-06' -> 'gpt-4o'.
    Returns the pricing entry dict, or None if no prefix matches.
    """
    match: str | None = None
    for key in _PRICES:
        if model.startswith(key) and (match is None or len(key) > len(match)):
            match = key
    return _PRICES[match] if match is not None else None


def _try_tokencost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Attempt cost lookup via tokencost. Returns None if unavailable or model unknown."""
    try:
        import tokencost  # type: ignore[import-untyped]  # lazy import — may not be installed
    except ImportError:
        return None

    try:
        # tokencost.cost_per_token returns cost per single token
        input_cost = tokencost.cost_per_token(model, "input") * input_tokens
        output_cost = tokencost.cost_per_token(model, "output") * output_tokens
        return float(input_cost + output_cost)
    except Exception:
        pass

    # Fallback: try TOKEN_COSTS dict
    try:
        price = tokencost.TOKEN_COSTS.get(model, {})
        if price:
            input_cost = price.get("prompt", 0) * input_tokens
            output_cost = price.get("completion", 0) * output_tokens
            return float(input_cost + output_cost)
    except Exception:
        pass

    return None


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    price_override: dict[str, float] | None = None,
) -> float:
    """Calculate the cost in USD for a given model call.

    Three-tier lookup:
      Tier 3 (highest priority): explicit price_override from user
      Tier 1: bundled prices.json (always available, zero deps)
      Tier 2: tokencost (if installed — lazy import, 400+ models)
      Fallback: warn and return 0.0

    Args:
        model: Model name (e.g. "gpt-4o").
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.
        price_override: Optional dict with 'input' and 'output' keys (price per 1k tokens).

    Returns:
        Cost in USD as a float.
    """
    # Tier 3: explicit override always wins
    if price_override is not None:
        input_per_1k = price_override["input"]
        output_per_1k = price_override["output"]
        return (input_tokens / 1000.0 * input_per_1k) + (output_tokens / 1000.0 * output_per_1k)

    # Tier 1: bundled prices.json — exact match
    if model in _PRICES:
        entry = _PRICES[model]
        return (
            input_tokens / 1000.0 * entry["input_per_1k"]
            + output_tokens / 1000.0 * entry["output_per_1k"]
        )

    # Tier 1b: prefix match — handles versioned names like "gpt-4o-2024-08-06"
    prefix_match = _prefix_lookup(model)
    if prefix_match is not None:
        return (
            input_tokens / 1000.0 * prefix_match["input_per_1k"]
            + output_tokens / 1000.0 * prefix_match["output_per_1k"]
        )

    # Tier 2: tokencost (lazy import)
    tokencost_cost = _try_tokencost(model, input_tokens, output_tokens)
    if tokencost_cost is not None:
        return tokencost_cost

    # No pricing available — warn, return 0.0 (don't crash)
    warnings.warn(
        f"shekel: model '{model}' not found in bundled prices or tokencost. "
        f"Cost tracking disabled for this call. "
        f"Install shekel[all-models] for 400+ model support, or pass "
        f"price_per_1k_tokens={{'input': X, 'output': Y}} to budget().",
        stacklevel=5,
    )
    return 0.0


def list_models() -> list[str]:
    """Return list of models with bundled pricing."""
    return list(_PRICES.keys())
