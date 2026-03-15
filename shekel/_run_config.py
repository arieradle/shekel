from __future__ import annotations

import sys
from typing import Any


def load_budget_file(path: str) -> dict[str, object]:
    """Parse a TOML budget config file and return budget kwargs.

    Supports the following keys under ``[budget]``:

    .. code-block:: toml

        [budget]
        max_usd = 5.0
        warn_at = 0.8
        max_llm_calls = 20
        max_tool_calls = 50

    Requires Python 3.11+ (uses stdlib ``tomllib``) or the optional
    ``tomli`` package for Python 3.9/3.10.

    Raises:
        FileNotFoundError: If *path* does not exist.
        SystemExit: If ``tomllib``/``tomli`` is unavailable on Python < 3.11.
    """
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore[import-not-found]
        except ImportError:
            raise SystemExit("shekel: --budget-file requires Python 3.11+ or: pip install tomli")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    section: dict[str, Any] = data.get("budget", {})
    kwargs: dict[str, object] = {}

    if "max_usd" in section:
        kwargs["max_usd"] = float(section["max_usd"])
    if "warn_at" in section:
        kwargs["warn_at"] = float(section["warn_at"])
    if "max_llm_calls" in section:
        kwargs["max_llm_calls"] = int(section["max_llm_calls"])
    if "max_tool_calls" in section:
        kwargs["max_tool_calls"] = int(section["max_tool_calls"])

    return kwargs
