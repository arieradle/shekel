from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shekel._budget import Budget

# Maps _patch._originals key prefixes to human-readable provider names.
_KEY_PREFIX_TO_PROVIDER: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "litellm": "litellm",
    "gemini": "gemini",
    "huggingface": "huggingface",
    "langchain": "langchain",
    "mcp": "mcp",
    "crewai": "crewai",
    "openai_agents": "openai-agents",
}


def detect_patched_providers() -> list[str]:
    """Return sorted list of provider names whose patches are currently active.

    Must be called after budget.__enter__() (i.e. inside ``with budget():``).
    """
    import shekel._patch as _patch_module

    seen: set[str] = set()
    for key in _patch_module._originals:
        for prefix, provider in _KEY_PREFIX_TO_PROVIDER.items():
            if key.startswith(prefix):
                seen.add(provider)
    return sorted(seen)


def format_spend_summary(b: Budget) -> str:
    """Return a compact one-line spend summary for CLI output."""
    data = b.summary_data()
    spent: float = float(data["total_spent"])  # type: ignore[arg-type]
    calls: int = int(data["calls_used"])  # type: ignore[call-overload]
    limit: float | None = data["limit"]  # type: ignore[assignment]

    by_model: dict[str, object] = data["by_model"]  # type: ignore[assignment]
    model_part = ""
    if by_model:
        top_model = max(by_model.items(), key=lambda kv: kv[1]["calls"])[0]  # type: ignore[index]
        model_part = f" · {top_model}"

    if limit is not None:
        pct = (spent / limit * 100) if limit > 0 else 0.0
        limit_part = f" / ${limit:.2f} ({pct:.0f}%)"
    else:
        limit_part = ""

    return f"${spent:.4f} spent{limit_part} · {calls} calls{model_part}"
