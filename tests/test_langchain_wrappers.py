"""Tests for LangChain chain-level budget enforcement.

Domain: LangChainRunnerAdapter — patching, chain gate, spend attribution, async support.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import shekel.providers.langchain as lc_mod
from shekel import budget
from shekel._budget import Budget
from shekel._runtime import ShekelRuntime
from shekel.exceptions import BudgetExceededError, ChainBudgetExceededError
from shekel.providers.langchain import LangChainRunnerAdapter

try:
    from langchain_core.runnables.base import Runnable, RunnableLambda, RunnableSequence

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LANGCHAIN_AVAILABLE, reason="langchain_core not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_adapter_state():
    """Restore LangChainRunnerAdapter patch state and ShekelRuntime registry after each test."""
    original_refcount = lc_mod._chain_patch_refcount
    original_cwc = lc_mod._original_call_with_config
    original_acwc = lc_mod._original_acall_with_config
    original_seq_invoke = lc_mod._original_sequence_invoke
    original_seq_ainvoke = lc_mod._original_sequence_ainvoke
    original_registry = ShekelRuntime._adapter_registry[:]

    real_cwc = Runnable._call_with_config
    real_acwc = Runnable._acall_with_config
    real_seq_invoke = RunnableSequence.invoke
    real_seq_ainvoke = RunnableSequence.ainvoke

    yield

    lc_mod._chain_patch_refcount = original_refcount
    lc_mod._original_call_with_config = original_cwc
    lc_mod._original_acall_with_config = original_acwc
    lc_mod._original_sequence_invoke = original_seq_invoke
    lc_mod._original_sequence_ainvoke = original_seq_ainvoke

    Runnable._call_with_config = real_cwc  # type: ignore[method-assign]
    Runnable._acall_with_config = real_acwc  # type: ignore[method-assign]
    RunnableSequence.invoke = real_seq_invoke  # type: ignore[method-assign]
    RunnableSequence.ainvoke = real_seq_ainvoke  # type: ignore[method-assign]

    ShekelRuntime._adapter_registry = original_registry


# ---------------------------------------------------------------------------
# Group 1: LangChainRunnerAdapter registered in ShekelRuntime
# ---------------------------------------------------------------------------


def test_langchain_runner_adapter_in_runtime_registry() -> None:
    """LangChainRunnerAdapter is registered in ShekelRuntime at import time."""
    assert LangChainRunnerAdapter in ShekelRuntime._adapter_registry


def test_langchain_runner_adapter_registered_exactly_once() -> None:
    """LangChainRunnerAdapter appears exactly once in the registry."""
    count = sum(1 for a in ShekelRuntime._adapter_registry if a is LangChainRunnerAdapter)
    assert count == 1


# ---------------------------------------------------------------------------
# Group 2: install_patches / remove_patches lifecycle
# ---------------------------------------------------------------------------


def test_install_patches_replaces_call_with_config() -> None:
    """install_patches() patches Runnable._call_with_config."""
    original = Runnable._call_with_config
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert Runnable._call_with_config is not original
    adapter.remove_patches(b)


def test_install_patches_replaces_sequence_invoke() -> None:
    """install_patches() patches RunnableSequence.invoke."""
    original = RunnableSequence.invoke
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    assert RunnableSequence.invoke is not original
    adapter.remove_patches(b)


def test_install_patches_raises_import_error_when_langchain_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install_patches() raises ImportError when langchain_core is not importable."""
    monkeypatch.setitem(sys.modules, "langchain_core", None)
    monkeypatch.setitem(sys.modules, "langchain_core.runnables", None)
    monkeypatch.setitem(sys.modules, "langchain_core.runnables.base", None)
    adapter = LangChainRunnerAdapter()
    with pytest.raises(ImportError):
        adapter.install_patches(Budget(max_usd=5.00))


def test_remove_patches_restores_call_with_config() -> None:
    """remove_patches() restores Runnable._call_with_config."""
    original = Runnable._call_with_config
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert Runnable._call_with_config is original


def test_remove_patches_restores_sequence_invoke() -> None:
    """remove_patches() restores RunnableSequence.invoke."""
    original = RunnableSequence.invoke
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    adapter.remove_patches(b)
    assert RunnableSequence.invoke is original


def test_reference_counting_patch_applied_once_for_nested_budgets() -> None:
    """Nested budgets increment refcount but only patch once."""
    b1 = Budget(max_usd=5.00)
    b2 = Budget(max_usd=3.00)
    a1 = LangChainRunnerAdapter()
    a2 = LangChainRunnerAdapter()

    a1.install_patches(b1)
    assert lc_mod._chain_patch_refcount == 1

    a2.install_patches(b2)
    assert lc_mod._chain_patch_refcount == 2

    a2.remove_patches(b2)
    assert lc_mod._chain_patch_refcount == 1

    a1.remove_patches(b1)
    assert lc_mod._chain_patch_refcount == 0


def test_remove_patches_is_safe_at_zero_refcount() -> None:
    """remove_patches() is a no-op when refcount is already 0."""
    adapter = LangChainRunnerAdapter()
    lc_mod._chain_patch_refcount = 0
    adapter.remove_patches(Budget(max_usd=5.00))
    assert lc_mod._chain_patch_refcount == 0


def test_patches_restored_on_budget_exit_even_on_exception() -> None:
    """Runnable methods are restored even when an exception propagates."""
    original_cwc = Runnable._call_with_config
    raised = False
    try:
        with budget(max_usd=5.00):
            assert Runnable._call_with_config is not original_cwc
            raise ValueError("simulated error")
    except ValueError:
        raised = True
    assert raised
    assert Runnable._call_with_config is original_cwc


# ---------------------------------------------------------------------------
# Group 3: Budget.chain() API
# ---------------------------------------------------------------------------


def test_budget_chain_registers_component_budget() -> None:
    """b.chain() registers a ComponentBudget in _chain_budgets."""
    b = Budget(max_usd=5.00)
    b.chain("summarize", max_usd=0.50)
    assert "summarize" in b._chain_budgets
    assert b._chain_budgets["summarize"].max_usd == 0.50


def test_chain_method_returns_self_for_chaining() -> None:
    """b.chain() returns self for method chaining."""
    b = Budget(max_usd=5.00)
    result = b.chain("a", max_usd=0.10).chain("b", max_usd=0.20)
    assert result is b
    assert "a" in b._chain_budgets
    assert "b" in b._chain_budgets


def test_chain_max_usd_must_be_positive() -> None:
    """b.chain() raises ValueError when max_usd <= 0."""
    b = Budget(max_usd=5.00)
    with pytest.raises(ValueError):
        b.chain("step", max_usd=0.0)
    with pytest.raises(ValueError):
        b.chain("step", max_usd=-1.0)


def test_chain_budgets_accessible_outside_context_manager() -> None:
    """b.chain() can be called before __enter__ — registration is separate from activation."""
    b = Budget(max_usd=5.00)
    b.chain("step", max_usd=0.30)
    assert b._chain_budgets["step"]._spent == 0.0


# ---------------------------------------------------------------------------
# Group 4: Pre-execution gate — explicit chain cap (RunnableLambda)
# ---------------------------------------------------------------------------


def test_explicit_chain_cap_exceeded_raises_before_lambda_runs() -> None:
    """ChainBudgetExceededError raised BEFORE the RunnableLambda body executes."""
    executed: list[bool] = []

    def my_fn(x: Any) -> Any:
        executed.append(True)
        return x

    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.10)
        b._chain_budgets["my_fn"]._spent = 0.10  # exhaust the cap
        chain = RunnableLambda(my_fn, name="my_fn")

        with pytest.raises(ChainBudgetExceededError):
            chain.invoke("input")

    assert executed == []


def test_explicit_chain_cap_error_carries_correct_fields() -> None:
    """ChainBudgetExceededError has correct chain_name, spent, limit."""

    def my_fn(x: Any) -> Any:
        return x

    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.10)
        b._chain_budgets["my_fn"]._spent = 0.10
        chain = RunnableLambda(my_fn, name="my_fn")

        with pytest.raises(ChainBudgetExceededError) as exc_info:
            chain.invoke("input")

    err = exc_info.value
    assert err.chain_name == "my_fn"
    assert err.spent == pytest.approx(0.10)
    assert err.limit == pytest.approx(0.10)


def test_chain_cap_not_exceeded_allows_lambda_to_run() -> None:
    """Lambda runs normally when spend is below chain cap."""

    def my_fn(x: Any) -> Any:
        return "result"

    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.50)
        b._chain_budgets["my_fn"]._spent = 0.05  # below cap
        chain = RunnableLambda(my_fn, name="my_fn")
        result = chain.invoke("input")

    assert result == "result"


def test_unnamed_lambda_not_gated() -> None:
    """Unnamed RunnableLambda is not gated even with chain caps registered."""
    executed: list[bool] = []

    def my_fn(x: Any) -> Any:
        executed.append(True)
        return x

    with budget(max_usd=5.00) as b:
        b.chain("other", max_usd=0.10)
        b._chain_budgets["other"]._spent = 0.10  # other cap exhausted
        # No name — should NOT be gated
        chain = RunnableLambda(my_fn)
        result = chain.invoke("input")

    assert executed == [True]
    assert result == "input"


def test_chain_budget_exceeded_is_subclass_of_budget_exceeded_error() -> None:
    """ChainBudgetExceededError is catchable as BudgetExceededError."""

    def my_fn(x: Any) -> Any:
        return x

    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.10)
        b._chain_budgets["my_fn"]._spent = 0.10
        chain = RunnableLambda(my_fn, name="my_fn")

        with pytest.raises(BudgetExceededError):
            chain.invoke("input")


# ---------------------------------------------------------------------------
# Group 5: Pre-execution gate — parent budget exhaustion
# ---------------------------------------------------------------------------


def test_parent_budget_exhausted_raises_chain_budget_exceeded_error() -> None:
    """ChainBudgetExceededError raised when parent budget is at limit."""
    executed: list[bool] = []

    def my_fn(x: Any) -> Any:
        executed.append(True)
        return x

    with budget(max_usd=1.00) as b:
        b.chain("my_fn", max_usd=5.00)  # chain cap not exceeded
        b._spent = 1.00  # parent exhausted
        chain = RunnableLambda(my_fn, name="my_fn")

        with pytest.raises(ChainBudgetExceededError) as exc_info:
            chain.invoke("input")

    assert executed == []
    assert exc_info.value.chain_name == "my_fn"


def test_no_active_budget_lambda_runs_unguarded() -> None:
    """Lambda executes normally when invoked outside any budget context."""

    def my_fn(x: Any) -> Any:
        return "unguarded"

    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.10)
        b._chain_budgets["my_fn"]._spent = 0.10
        chain = RunnableLambda(my_fn, name="my_fn")

    # Invoke OUTSIDE budget — get_active_budget() returns None
    result = chain.invoke("input")
    assert result == "unguarded"


# ---------------------------------------------------------------------------
# Group 6: Post-execution spend attribution (RunnableLambda)
# ---------------------------------------------------------------------------


def test_spend_delta_attributed_to_chain_component_budget() -> None:
    """Spend during lambda execution is attributed to its chain ComponentBudget._spent."""
    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=1.00)

        def my_fn(x: Any) -> Any:
            b._spent += 0.15  # simulate LLM call
            return x

        chain = RunnableLambda(my_fn, name="my_fn")
        chain.invoke("input")
        cb = b._chain_budgets["my_fn"]

    assert cb._spent == pytest.approx(0.15)


def test_zero_spend_in_lambda_leaves_chain_budget_at_zero() -> None:
    """Lambda with no LLM spend leaves chain ComponentBudget._spent at 0."""

    def my_fn(x: Any) -> Any:
        return x

    with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.50)
        chain = RunnableLambda(my_fn, name="my_fn")
        chain.invoke("input")
        cb = b._chain_budgets["my_fn"]

    assert cb._spent == pytest.approx(0.0)


def test_spend_not_attributed_when_no_cap_registered_for_name() -> None:
    """Named lambda without a registered cap doesn't populate _chain_budgets."""

    def my_fn(x: Any) -> Any:
        b._spent += 0.05
        return x

    with budget(max_usd=5.00) as b:
        chain = RunnableLambda(my_fn, name="my_fn")
        chain.invoke("input")

    assert "my_fn" not in b._chain_budgets


# ---------------------------------------------------------------------------
# Group 7: RunnableSequence (LCEL pipeline) cap enforcement
# ---------------------------------------------------------------------------


def test_sequence_cap_exceeded_raises_before_pipeline_runs() -> None:
    """ChainBudgetExceededError raised before a capped RunnableSequence executes."""
    executed: list[bool] = []

    def step1(x: Any) -> Any:
        executed.append(True)
        return x

    def step2(x: Any) -> Any:
        executed.append(True)
        return x

    with budget(max_usd=5.00) as b:
        b.chain("my_pipeline", max_usd=0.10)
        b._chain_budgets["my_pipeline"]._spent = 0.10

        seq = RunnableLambda(step1) | RunnableLambda(step2)
        seq.name = "my_pipeline"  # type: ignore[assignment]

        with pytest.raises(ChainBudgetExceededError):
            seq.invoke("input")

    assert executed == []


def test_sequence_cap_not_exceeded_allows_pipeline_to_run() -> None:
    """RunnableSequence runs normally when below its chain cap."""

    def step1(x: Any) -> Any:
        return x + "_s1"

    def step2(x: Any) -> Any:
        return x + "_s2"

    with budget(max_usd=5.00) as b:
        b.chain("my_pipeline", max_usd=0.50)
        seq = RunnableLambda(step1) | RunnableLambda(step2)
        seq.name = "my_pipeline"  # type: ignore[assignment]
        result = seq.invoke("input")

    assert result == "input_s1_s2"


def test_sequence_spend_attributed_to_chain_budget() -> None:
    """Spend during RunnableSequence execution attributed to its chain ComponentBudget."""
    with budget(max_usd=5.00) as b:
        b.chain("my_pipeline", max_usd=1.00)

        def step1(x: Any) -> Any:
            b._spent += 0.20
            return x

        seq = RunnableLambda(step1)
        seq.name = "my_pipeline"  # type: ignore[assignment]
        seq.invoke("input")

    assert b._chain_budgets["my_pipeline"]._spent == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Group 8: Nested budget cap inheritance (parent-chain lookup)
# ---------------------------------------------------------------------------


def test_chain_cap_on_outer_budget_enforced_in_nested_inner_budget() -> None:
    """Cap registered on outer budget raises ChainBudgetExceededError inside inner context."""
    executed: list[bool] = []

    def my_fn(x: Any) -> Any:
        executed.append(True)
        return x

    with budget(max_usd=5.00, name="outer") as outer:
        outer.chain("my_fn", max_usd=0.10)
        outer._chain_budgets["my_fn"]._spent = 0.10

        with budget(max_usd=2.00, name="inner"):
            chain = RunnableLambda(my_fn, name="my_fn")
            with pytest.raises(ChainBudgetExceededError):
                chain.invoke("input")

    assert executed == []


def test_inner_budget_chain_cap_takes_precedence_over_outer() -> None:
    """Cap registered on inner budget is used even if outer also has a cap for same name."""

    def my_fn(x: Any) -> Any:
        return x

    with budget(max_usd=5.00, name="outer") as outer:
        outer.chain("my_fn", max_usd=1.00)  # outer cap: $1.00 — not exceeded

        with budget(max_usd=2.00, name="inner") as inner:
            inner.chain("my_fn", max_usd=0.05)
            inner._chain_budgets["my_fn"]._spent = 0.05  # exhaust inner cap

            chain = RunnableLambda(my_fn, name="my_fn")
            with pytest.raises(ChainBudgetExceededError) as exc_info:
                chain.invoke("input")

    assert exc_info.value.limit == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Group 9: Async support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_lambda_cap_exceeded_raises_before_execution() -> None:
    """Async ChainBudgetExceededError raised before awaiting lambda body."""
    executed: list[bool] = []

    async def my_fn(x: Any) -> Any:
        executed.append(True)
        return x

    async with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.10)
        b._chain_budgets["my_fn"]._spent = 0.10
        chain = RunnableLambda(my_fn, name="my_fn")

        with pytest.raises(ChainBudgetExceededError):
            await chain.ainvoke("input")

    assert executed == []


@pytest.mark.asyncio
async def test_async_lambda_runs_and_returns_result() -> None:
    """Async lambda runs normally when below cap."""

    async def my_fn(x: Any) -> Any:
        return "async_result"

    async with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=1.00)
        chain = RunnableLambda(my_fn, name="my_fn")
        result = await chain.ainvoke("input")

    assert result == "async_result"


@pytest.mark.asyncio
async def test_async_spend_attributed_to_chain_budget() -> None:
    """Spend during async lambda execution attributed to chain ComponentBudget."""

    async with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=1.00)

        async def my_fn(x: Any) -> Any:
            b._spent += 0.25
            return x

        chain = RunnableLambda(my_fn, name="my_fn")
        await chain.ainvoke("input")

    assert b._chain_budgets["my_fn"]._spent == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_async_no_active_budget_runs_unguarded() -> None:
    """Async lambda executes normally outside any budget context."""

    async def my_fn(x: Any) -> Any:
        return "unguarded_async"

    async with budget(max_usd=5.00) as b:
        b.chain("my_fn", max_usd=0.10)
        b._chain_budgets["my_fn"]._spent = 0.10
        chain = RunnableLambda(my_fn, name="my_fn")

    result = await chain.ainvoke("input")
    assert result == "unguarded_async"


# ---------------------------------------------------------------------------
# Group 10: Integration with Budget lifecycle via ShekelRuntime
# ---------------------------------------------------------------------------


def test_call_with_config_patched_on_budget_enter() -> None:
    """Runnable._call_with_config is patched when a budget context is entered."""
    original = Runnable._call_with_config
    with budget(max_usd=5.00):
        assert Runnable._call_with_config is not original
    assert Runnable._call_with_config is original


def test_call_with_config_restored_on_budget_exit() -> None:
    """Runnable._call_with_config is restored after the budget context exits."""
    original = Runnable._call_with_config
    with budget(max_usd=5.00):
        pass
    assert Runnable._call_with_config is original


def test_named_lambda_passthrough_when_patch_active_but_no_budget() -> None:
    """Named lambda runs unguarded when patch is installed but no budget context is active."""
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    try:
        chain = RunnableLambda(lambda x: "passthrough", name="my_fn")
        result = chain.invoke("input")  # no active budget — passthrough path
        assert result == "passthrough"
    finally:
        adapter.remove_patches(b)


@pytest.mark.asyncio
async def test_named_lambda_async_passthrough_when_no_budget() -> None:
    """Async named lambda runs unguarded when patch is installed but no budget context is active."""
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    try:

        async def my_fn(x: Any) -> Any:
            return "async_passthrough"

        chain = RunnableLambda(my_fn, name="my_fn")
        result = await chain.ainvoke("input")
        assert result == "async_passthrough"
    finally:
        adapter.remove_patches(b)


def test_sequence_passthrough_when_patch_active_but_no_budget() -> None:
    """Named RunnableSequence runs unguarded when patch is installed but no budget context."""
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    try:
        # Use | to create an actual RunnableSequence
        seq = RunnableLambda(lambda x: x) | RunnableLambda(lambda x: x + "_done")
        seq.name = "my_seq"  # type: ignore[assignment]
        result = seq.invoke("input")  # no active budget — passthrough path
        assert result == "input_done"
    finally:
        adapter.remove_patches(b)


@pytest.mark.asyncio
async def test_async_sequence_cap_enforced_and_spend_attributed() -> None:
    """Async RunnableSequence (created with |) cap enforced and spend attributed."""
    async with budget(max_usd=5.00) as b:
        b.chain("async_pipeline", max_usd=1.00)

        seq = RunnableLambda(lambda x: x) | RunnableLambda(lambda x: x + "_done")
        seq.name = "async_pipeline"  # type: ignore[assignment]
        result = await seq.ainvoke("input")

    assert result == "input_done"


@pytest.mark.asyncio
async def test_sequence_async_passthrough_when_patch_active_but_no_budget() -> None:
    """Named RunnableSequence async runs unguarded when patch is installed but no budget context."""
    adapter = LangChainRunnerAdapter()
    b = Budget(max_usd=5.00)
    adapter.install_patches(b)
    try:
        # Use | to create an actual RunnableSequence
        seq = RunnableLambda(lambda x: x) | RunnableLambda(lambda x: x + "_async_done")
        seq.name = "my_seq"  # type: ignore[assignment]
        result = await seq.ainvoke("input")
        assert result == "input_async_done"
    finally:
        adapter.remove_patches(b)


def test_mock_llm_spend_tracked_with_chain_cap() -> None:
    """End-to-end: mocked LLM call inside lambda → spend tracked in chain ComponentBudget."""
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "ok"
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 50
    mock_resp.model = "gpt-4o-mini"

    with patch(
        "openai.resources.chat.completions.Completions.create",
        return_value=mock_resp,
    ):
        import openai

        client = openai.OpenAI(api_key="test")

        with budget(max_usd=5.00) as b:
            b.chain("llm_step", max_usd=1.00)

            def llm_step(x: Any) -> Any:
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hello"}],
                )
                return x

            chain = RunnableLambda(llm_step, name="llm_step")
            chain.invoke("input")

    assert b._chain_budgets["llm_step"]._spent > 0
    assert b._chain_budgets["llm_step"]._spent == pytest.approx(b.spent)
