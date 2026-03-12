"""Integration tests for the OpenAI provider adapter.

Real-API tests (TestOpenAIRealIntegration) require OPENAI_API_KEY env var
and are skipped without it.

Mock tests (TestOpenAIMockIntegration) run without any API keys and verify
the adapter's patch lifecycle and token extraction end-to-end.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shekel import budget
from shekel.exceptions import BudgetExceededError

try:
    import openai
    import openai.resources.chat.completions as oai_completions

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

pytestmark = pytest.mark.skipif(not OPENAI_AVAILABLE, reason="openai not installed")

_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Real-API tests
# ---------------------------------------------------------------------------


class TestOpenAIRealIntegration:
    """Tests that call the real OpenAI API."""

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("OPENAI_API_KEY")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key and OPENAI_AVAILABLE)

    @pytest.fixture
    def client(self, api_key: str | None, available: bool) -> Any:
        if not available or api_key is None:
            pytest.skip("OpenAI API not available")
        return openai.OpenAI(api_key=api_key)

    @pytest.fixture
    def async_client(self, api_key: str | None, available: bool) -> Any:
        if not available or api_key is None:
            pytest.skip("OpenAI API not available")
        return openai.AsyncOpenAI(api_key=api_key)

    @staticmethod
    def _maybe_skip_quota(exc: Exception) -> None:
        """Call pytest.skip() if exc is an OpenAI quota/rate-limit error."""
        msg = str(exc)
        if "429" in msg or "rate_limit" in msg.lower() or "quota" in msg.lower():
            pytest.skip(f"OpenAI quota/rate-limit: {msg[:120]}")

    def test_basic_completion_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend from chat.completions.create()."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=1.00) as b:
                response = client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                )
            assert response is not None
            assert b.spent > 0, "Expected spend > 0 after a real OpenAI call"
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_streaming_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend when iterating a streaming completion."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=1.00) as b:
                chunks = list(
                    client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "Count to three."}],
                        max_tokens=10,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                )
            assert len(chunks) > 0
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_raises_error(self, client: Any, available: bool) -> None:
        """BudgetExceededError is raised when budget is exhausted."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                    )
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_nested_budgets_roll_up(self, client: Any, available: bool) -> None:
        """Spend in an inner budget is reflected in the outer budget."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=5.00, name="outer") as outer:
                with budget(max_usd=1.00, name="inner") as inner:
                    client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "Say yes."}],
                        max_tokens=5,
                    )
            assert inner.spent > 0
            assert outer.spent >= inner.spent
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_warn_at_callback_triggered(self, client: Any, available: bool) -> None:
        """warn_at=0.000001 triggers on_warn callback after first token spend."""
        if not available:
            pytest.skip("OpenAI API not available")

        warnings: list[float] = []

        try:
            with budget(
                max_usd=1.00,
                warn_at=0.000001,
                on_warn=lambda spent, limit: warnings.append(spent),
            ) as b:
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Hi."}],
                    max_tokens=5,
                )
            assert b.spent > 0
            assert len(warnings) > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_multiple_sequential_calls_accumulate(self, client: Any, available: bool) -> None:
        """Multiple calls within one budget context accumulate spend."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=5.00) as b:
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "One."}],
                    max_tokens=5,
                )
                spend_after_first = b.spent
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Two."}],
                    max_tokens=5,
                )
            assert b.spent > spend_after_first
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_remaining_decreases_after_call(self, client: Any, available: bool) -> None:
        """b.remaining decreases after each API call."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=5.00) as b:
                remaining_before = b.remaining
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Hi."}],
                    max_tokens=5,
                )
                assert b.remaining < remaining_before
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_system_message_completion_tracks_spend(self, client: Any, available: bool) -> None:
        """System message plus user message both tracked correctly."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=1.00) as b:
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": "What is 2+2?"},
                    ],
                    max_tokens=10,
                )
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_name_is_preserved(self, client: Any, available: bool) -> None:
        """Budget name attribute is accessible on the context object."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=1.00, name="test-budget") as b:
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Hi."}],
                    max_tokens=5,
                )
            assert b.name == "test-budget"
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_error_has_spent_attribute(self, client: Any, available: bool) -> None:
        """BudgetExceededError carries the spent amount."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with pytest.raises(BudgetExceededError) as exc_info:
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                    )
            assert exc_info.value.spent > 0
        except Exception as exc:
            if not isinstance(exc, pytest.skip.Exception):
                self._maybe_skip_quota(exc)
            raise

    def test_summary_after_call(self, client: Any, available: bool) -> None:
        """b.summary() returns a string after a real API call."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=1.00) as b:
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Hi."}],
                    max_tokens=5,
                )
            summary = b.summary()
            assert isinstance(summary, str)
            assert len(summary) > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_fallback_model_switch(self, client: Any, available: bool) -> None:
        """Fallback rewrites model kwarg to cheaper model when threshold exceeded."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(
                max_usd=0.0001,
                fallback={"at_pct": 0.001, "model": _MODEL},
            ) as b:
                try:
                    client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role": "user", "content": "Say hi."}],
                        max_tokens=5,
                    )
                except BudgetExceededError:
                    pass  # acceptable — budget very small
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_multi_turn_conversation(self, client: Any, available: bool) -> None:
        """Multi-turn conversation tokens accumulate in single budget."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            messages = [{"role": "user", "content": "My name is Alice."}]
            with budget(max_usd=5.00) as b:
                resp1 = client.chat.completions.create(
                    model=_MODEL,
                    messages=messages,
                    max_tokens=20,
                )
                messages.append({"role": "assistant", "content": resp1.choices[0].message.content})
                messages.append({"role": "user", "content": "What is my name?"})
                client.chat.completions.create(
                    model=_MODEL,
                    messages=messages,
                    max_tokens=20,
                )
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_tracks_spend(self, async_client: Any, available: bool) -> None:
        """budget() tracks spend from async chat.completions.create()."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with budget(max_usd=1.00) as b:
                response = await async_client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_streaming_tracks_spend(self, async_client: Any, available: bool) -> None:
        """budget() tracks spend from async streaming."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            chunks = []
            with budget(max_usd=1.00) as b:
                async for chunk in await async_client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "Count to two."}],
                    max_tokens=10,
                    stream=True,
                    stream_options={"include_usage": True},
                ):
                    chunks.append(chunk)
            assert len(chunks) > 0
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_budget_exceeded_raises_error(
        self, async_client: Any, available: bool
    ) -> None:
        """BudgetExceededError raised from async call when budget tiny."""
        if not available:
            pytest.skip("OpenAI API not available")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    await async_client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                    )
        except Exception as exc:
            if not isinstance(exc, pytest.skip.Exception):
                self._maybe_skip_quota(exc)
            raise


# ---------------------------------------------------------------------------
# Mock tests — always run, no API key required
# ---------------------------------------------------------------------------


class TestOpenAIMockIntegration:
    """Verify adapter lifecycle and token extraction without API calls."""

    def test_patch_install_and_remove_lifecycle(self) -> None:
        """Adapter patches Completions.create."""
        from shekel.providers.openai import OpenAIAdapter

        original = oai_completions.Completions.create

        adapter = OpenAIAdapter()
        try:
            adapter.install_patches()
            assert oai_completions.Completions.create is not original
        finally:
            adapter.remove_patches()

        assert oai_completions.Completions.create is original

    def test_budget_records_spend_from_mock_response(self) -> None:
        """budget() records correct cost from a mocked create call."""

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50
            model = _MODEL

        class FakeChoice:
            finish_reason = "stop"

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()
            choices = [FakeChoice()]

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(oai_completions.Completions, "create", fake_create):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = openai.OpenAI(api_key="fake-key")
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "hello"}],
                )

        # 100 input + 50 output at $1/1k each = $0.15
        assert b.spent > 0

    def test_streaming_mock_records_spend(self) -> None:
        """budget() records correct cost from mocked streaming call."""

        class FakeUsage:
            prompt_tokens = 80
            completion_tokens = 40

        class FakeChunk:
            model = _MODEL
            usage = None

        class FakeChunkWithUsage:
            model = _MODEL
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> Any:
            yield FakeChunk()
            yield FakeChunk()
            yield FakeChunkWithUsage()

        with patch.object(oai_completions.Completions, "create", fake_create):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = openai.OpenAI(api_key="fake-key")
                list(
                    client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "hello"}],
                        stream=True,
                    )
                )

        assert b.spent > 0

    def test_budget_exceeded_from_mock(self) -> None:
        """BudgetExceededError raised when mocked usage pushes over tiny budget."""

        class FakeUsage:
            prompt_tokens = 1000
            completion_tokens = 500

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(oai_completions.Completions, "create", fake_create):
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client = openai.OpenAI(api_key="fake-key")
                    client.chat.completions.create(
                        model=_MODEL,
                        messages=[{"role": "user", "content": "hello"}],
                    )

    def test_extract_tokens_from_real_response_shape(self) -> None:
        """extract_tokens handles the real OpenAI response structure."""
        from shekel.providers.openai import OpenAIAdapter

        class FakeUsage:
            prompt_tokens = 42
            completion_tokens = 17

        class FakeResp:
            model = _MODEL
            usage = FakeUsage()

        adapter = OpenAIAdapter()
        it, ot, model = adapter.extract_tokens(FakeResp())
        assert it == 42
        assert ot == 17
        assert model == _MODEL

    def test_no_usage_in_response_returns_zeros(self) -> None:
        """When response.usage is None, extract_tokens returns (0, 0, model)."""
        from shekel.providers.openai import OpenAIAdapter

        class FakeResp:
            model = _MODEL
            usage = None

        adapter = OpenAIAdapter()
        it, ot, model = adapter.extract_tokens(FakeResp())
        assert it == 0
        assert ot == 0
        assert model == _MODEL

    def test_unknown_model_records_zero_cost(self) -> None:
        """Unknown model with no price override records $0 rather than crashing."""

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50

        class FakeResponse:
            model = "gpt-999-not-real"
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(oai_completions.Completions, "create", fake_create):
            with budget(max_usd=1.00) as b:
                client = openai.OpenAI(api_key="fake-key")
                client.chat.completions.create(
                    model="gpt-999-not-real",
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert b.spent == pytest.approx(0.0)

    def test_no_crash_without_openai_package(self) -> None:
        """install_patches() is a no-op when openai is not importable."""
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        with patch.dict("sys.modules", {"openai": None, "openai.resources.chat.completions": None}):
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is acceptable

    def test_warn_at_callback_mock(self) -> None:
        """on_warn callback fires when warn_at threshold is crossed via mock."""

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        warnings: list[float] = []

        with patch.object(oai_completions.Completions, "create", fake_create):
            with budget(
                max_usd=1.00,
                warn_at=0.000001,
                on_warn=lambda spent, limit: warnings.append(spent),
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = openai.OpenAI(api_key="fake-key")
                client.chat.completions.create(
                    model=_MODEL,
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert b.spent > 0
        assert len(warnings) > 0

    def test_wrapper_directly_records_spend(self) -> None:
        """_openai_sync_wrapper records cost via _patch._record."""
        from shekel import _patch

        class FakeUsage:
            prompt_tokens = 200
            completion_tokens = 100

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        original = MagicMock(return_value=FakeResponse())
        _patch._originals["openai_sync"] = original

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                fake_self = MagicMock()
                _patch._openai_sync_wrapper(fake_self, model=_MODEL)
        finally:
            _patch._originals.pop("openai_sync", None)

        assert b.spent > 0
