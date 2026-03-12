"""Tests for F4 — @with_budget decorator."""

from __future__ import annotations

import asyncio
import warnings
from unittest.mock import patch

import pytest

from shekel import BudgetExceededError, with_budget
from shekel._pricing import calculate_cost
from tests.conftest import make_openai_response

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
ASYNC_OPENAI_CREATE = "openai.resources.chat.completions.AsyncCompletions.create"


# ---------------------------------------------------------------------------
# test_sync_function_wrapped
# ---------------------------------------------------------------------------


def test_sync_function_wrapped() -> None:
    """Decorated sync function runs, spend tracked via patching."""
    fake = make_openai_response("gpt-4o", 500, 200)
    results: list[float] = []

    @with_budget(max_usd=1.00)
    def run() -> None:
        from shekel import _context

        b = _context.get_active_budget()
        assert b is not None
        import openai

        client = openai.OpenAI(api_key="test")
        client.chat.completions.create(model="gpt-4o", messages=[])
        results.append(b.spent)

    with patch(OPENAI_CREATE, return_value=fake):
        run()

    expected = calculate_cost("gpt-4o", 500, 200)
    assert results[0] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# test_async_function_wrapped
# ---------------------------------------------------------------------------


def test_async_function_wrapped() -> None:
    """Decorated async function runs, spend tracked."""
    fake = make_openai_response("gpt-4o", 500, 200)
    results: list[float] = []

    @with_budget(max_usd=1.00)
    async def run_async() -> None:
        from shekel import _context

        b = _context.get_active_budget()
        assert b is not None
        import openai

        client = openai.AsyncOpenAI(api_key="test")
        await client.chat.completions.create(model="gpt-4o", messages=[])
        results.append(b.spent)

    async def fake_create_async(self: object, *args: object, **kwargs: object) -> object:
        return fake

    with patch(ASYNC_OPENAI_CREATE, new=fake_create_async):
        asyncio.get_event_loop().run_until_complete(run_async())

    expected = calculate_cost("gpt-4o", 500, 200)
    assert results[0] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# test_budget_exceeded_raises
# ---------------------------------------------------------------------------


def test_budget_exceeded_raises() -> None:
    """Decorated function raises BudgetExceededError when over limit."""
    fake = make_openai_response("gpt-4o", 100_000, 50_000)  # very expensive

    @with_budget(max_usd=0.001)
    def run() -> None:
        import openai

        client = openai.OpenAI(api_key="test")
        client.chat.completions.create(model="gpt-4o", messages=[])

    with patch(OPENAI_CREATE, return_value=fake):
        with pytest.raises(BudgetExceededError):
            run()


# ---------------------------------------------------------------------------
# test_fallback_works_in_decorator
# ---------------------------------------------------------------------------


def test_fallback_works_in_decorator() -> None:
    """@with_budget(fallback=...) switches model correctly."""
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

    @with_budget(max_usd=0.1, fallback={"at": 0.8, "model": "gpt-4o-mini"})
    def run() -> None:
        import openai

        client = openai.OpenAI(api_key="test")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            client.chat.completions.create(model="gpt-4o", messages=[])
            client.chat.completions.create(model="gpt-4o", messages=[])

    with patch(OPENAI_CREATE, new=fake_create):
        run()

    assert captured_models[1] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# test_fresh_budget_per_call
# ---------------------------------------------------------------------------


def test_fresh_budget_per_call() -> None:
    """Each call to decorated function gets fresh budget state."""
    fake = make_openai_response("gpt-4o", 10_000, 5_000)
    spent_values: list[float] = []

    @with_budget(max_usd=1.00)
    def run() -> None:
        from shekel import _context

        b = _context.get_active_budget()
        assert b is not None
        import openai

        client = openai.OpenAI(api_key="test")
        client.chat.completions.create(model="gpt-4o", messages=[])
        spent_values.append(b.spent)

    with patch(OPENAI_CREATE, return_value=fake):
        run()
        run()

    # Each call has fresh state — both should have the same (single-call) spend
    assert spent_values[0] == pytest.approx(spent_values[1])
    # Both should be > 0
    assert spent_values[0] > 0.0


# ---------------------------------------------------------------------------
# test_functools_wraps_preserved
# ---------------------------------------------------------------------------


def test_functools_wraps_preserved() -> None:
    """__name__ and __doc__ preserved on wrapped function."""

    @with_budget(max_usd=1.00)
    def my_agent_function() -> None:
        """Runs the agent."""
        pass

    assert my_agent_function.__name__ == "my_agent_function"
    assert my_agent_function.__doc__ == "Runs the agent."


def test_functools_wraps_preserved_async() -> None:
    """__name__ and __doc__ preserved on wrapped async function."""

    @with_budget(max_usd=1.00)
    async def my_async_agent() -> None:
        """Async agent."""
        pass

    assert my_async_agent.__name__ == "my_async_agent"
    assert my_async_agent.__doc__ == "Async agent."


# ---------------------------------------------------------------------------
# test_no_params_decorator
# ---------------------------------------------------------------------------


def test_no_params_decorator() -> None:
    """@with_budget() with no params works (track-only mode)."""
    fake = make_openai_response("gpt-4o", 500, 200)
    results: list[float] = []

    @with_budget()
    def run() -> None:
        from shekel import _context

        b = _context.get_active_budget()
        assert b is not None
        assert b.max_usd is None  # track-only mode
        import openai

        client = openai.OpenAI(api_key="test")
        client.chat.completions.create(model="gpt-4o", messages=[])
        results.append(b.spent)

    with patch(OPENAI_CREATE, return_value=fake):
        run()

    assert results[0] > 0.0


class TestWithBudgetName:
    def test_with_budget_accepts_name(self) -> None:
        """with_budget should pass name to Budget, enabling named budgets."""
        called = []

        @with_budget(max_usd=5.00, name="outer")
        def run() -> None:
            from shekel import _context

            b = _context.get_active_budget()
            assert b is not None
            assert b.name == "outer"
            called.append(True)

        run()
        assert called

    def test_with_budget_name_enables_nesting(self) -> None:
        """Named with_budget decorator can serve as a named parent for nested budgets."""
        from shekel import budget

        names_seen: list[str] = []

        @with_budget(max_usd=10.00, name="workflow")
        def run_workflow() -> None:
            with budget(max_usd=3.00, name="step") as child:
                names_seen.append(child.full_name)

        run_workflow()
        assert names_seen == ["workflow.step"]
