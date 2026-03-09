from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shekel._budget import Budget

# ContextVar provides thread-safe, async-safe, nested-context-safe isolation.
# Each thread/async task gets its own copy — two concurrent budget() contexts
# never see each other's state.
_active_budget: ContextVar[Budget | None] = ContextVar("_active_budget", default=None)


def get_active_budget() -> Budget | None:
    return _active_budget.get()


def set_active_budget(b: Budget | None) -> Token[Budget | None]:
    return _active_budget.set(b)
