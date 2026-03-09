from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from shekel import _patch as patch_module
from shekel import budget
from tests.conftest import make_openai_response

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"


def test_concurrent_contexts_isolated() -> None:
    """Two threads with separate budget() contexts must not share spend.

    Tests ContextVar isolation directly via _record_spend — avoids
    unittest.mock.patch which is global and racy across threads.
    """
    results: dict[str, float] = {}
    barrier = threading.Barrier(2)

    def run(name: str, spend_amount: float) -> None:
        with budget(max_usd=10.00) as b:
            barrier.wait()  # both threads inside context simultaneously
            b._record_spend(spend_amount, "gpt-4o", {"input": 100, "output": 50})
        results[name] = b.spent

    t1 = threading.Thread(target=run, args=("a", 0.10))
    t2 = threading.Thread(target=run, args=("b", 0.20))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Each thread's budget sees only its own spend
    assert results["a"] == pytest.approx(0.10)
    assert results["b"] == pytest.approx(0.20)


def test_refcount_resets_to_zero_after_all_exit() -> None:
    """Patch ref-count must be 0 after all budget contexts exit."""
    fake = make_openai_response("gpt-4o", 100, 50)

    done = threading.Event()
    results: dict[str, int] = {}

    def run() -> None:
        with patch(OPENAI_CREATE, return_value=fake):
            with budget(max_usd=1.00):
                pass
        results["refcount"] = patch_module._patch_refcount
        done.set()

    t = threading.Thread(target=run)
    t.start()
    done.wait(timeout=5)
    t.join()

    assert results.get("refcount") == 0


def test_refcount_increments_for_concurrent_budgets() -> None:
    """While two budget contexts are active simultaneously, refcount >= 2."""
    entered = threading.Event()
    proceed = threading.Event()
    refcounts: list[int] = []

    def run() -> None:
        with budget(max_usd=1.00):
            entered.set()
            proceed.wait(timeout=5)

    t = threading.Thread(target=run)
    t.start()
    entered.wait(timeout=5)

    with budget(max_usd=1.00):
        refcounts.append(patch_module._patch_refcount)

    proceed.set()
    t.join()

    assert refcounts[0] >= 2
