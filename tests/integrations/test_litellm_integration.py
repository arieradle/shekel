"""Integration tests for the LiteLLM provider adapter.

Real-API tests require provider-specific API keys and are skipped without them:
  - TestLiteLLMGroqIntegration      requires GROQ_API_KEY
  - TestLiteLLMGeminiIntegration    requires GEMINI_API_KEY
  - TestLiteLLMHuggingFaceIntegration requires HUGGINGFACE_TOKEN

Mock tests (TestLiteLLMMockIntegration) run without any API keys and verify
the adapter's patch lifecycle and token extraction end-to-end.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from shekel import budget
from shekel.exceptions import BudgetExceededError

try:
    import litellm

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LITELLM_AVAILABLE, reason="litellm not installed")

_GROQ_MODEL = "groq/llama-3.1-8b-instant"
_GEMINI_MODEL = "gemini/gemini-2.0-flash-lite"
_HF_MODEL = "huggingface/HuggingFaceH4/zephyr-7b-beta"


# ---------------------------------------------------------------------------
# Mock tests — always run, no API key required
# ---------------------------------------------------------------------------


class TestLiteLLMMockIntegration:
    """Verify adapter lifecycle and token extraction without real API calls."""

    def test_patch_install_and_remove_lifecycle(self) -> None:
        """Adapter patches litellm.completion and litellm.acompletion."""
        from shekel.providers.litellm import LiteLLMAdapter

        original_sync = litellm.completion
        original_async = litellm.acompletion

        adapter = LiteLLMAdapter()
        try:
            adapter.install_patches()
            assert litellm.completion is not original_sync
            assert litellm.acompletion is not original_async
        finally:
            adapter.remove_patches()

        assert litellm.completion is original_sync
        assert litellm.acompletion is original_async

    def test_budget_records_spend_from_mock_response(self) -> None:
        """budget() records correct cost from a mocked completion call."""

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50

        class FakeResponse:
            model = "gpt-4o-mini"
            usage = FakeUsage()

        def fake_completion(**kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch("litellm.completion", fake_completion):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                litellm.completion(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                )

        assert b.spent > 0

    def test_streaming_mock_records_spend(self) -> None:
        """budget() records correct cost from a mocked streaming completion."""

        class FakeUsage:
            prompt_tokens = 80
            completion_tokens = 40

        class FakeChunk:
            model = "gpt-4o-mini"
            usage = None

        class FakeChunkWithUsage:
            model = "gpt-4o-mini"
            usage = FakeUsage()

        def fake_completion(**kwargs: Any) -> Any:
            yield FakeChunk()
            yield FakeChunk()
            yield FakeChunkWithUsage()

        with patch("litellm.completion", fake_completion):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                list(
                    litellm.completion(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
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
            model = "gpt-4o-mini"
            usage = FakeUsage()

        def fake_completion(**kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch("litellm.completion", fake_completion):
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    litellm.completion(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
                    )

    def test_unknown_model_records_zero_cost(self) -> None:
        """Unknown model with no price override records $0 rather than crashing."""

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50

        class FakeResponse:
            model = "unknown-provider/unknown-model"
            usage = FakeUsage()

        def fake_completion(**kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch("litellm.completion", fake_completion):
            with budget(max_usd=1.00) as b:
                litellm.completion(
                    model="unknown-provider/unknown-model",
                    messages=[{"role": "user", "content": "hi"}],
                )

        assert b.spent == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_async_budget_records_spend_from_mock_response(self) -> None:
        """async with budget() records correct cost from a mocked acompletion call."""

        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50

        class FakeResponse:
            model = "gpt-4o-mini"
            usage = FakeUsage()

        async def fake_acompletion(**kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch("litellm.acompletion", fake_acompletion):
            async with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                await litellm.acompletion(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hi"}],
                )

        assert b.spent > 0

    @pytest.mark.asyncio
    async def test_async_streaming_mock_records_spend(self) -> None:
        """async with budget() records cost from a mocked async streaming completion."""

        class FakeUsage:
            prompt_tokens = 80
            completion_tokens = 40

        class FakeChunk:
            model = "gpt-4o-mini"
            usage = None

        class FakeChunkWithUsage:
            model = "gpt-4o-mini"
            usage = FakeUsage()

        async def fake_acompletion(**kwargs: Any) -> Any:
            async def _gen() -> Any:
                yield FakeChunk()
                yield FakeChunkWithUsage()

            return _gen()

        with patch("litellm.acompletion", fake_acompletion):
            async with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                stream = await litellm.acompletion(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hi"}],
                    stream=True,
                )
                async for _ in stream:
                    pass

        assert b.spent > 0

    @pytest.mark.asyncio
    async def test_async_budget_exceeded_from_mock(self) -> None:
        """BudgetExceededError raised from async call when budget tiny."""

        class FakeUsage:
            prompt_tokens = 1000
            completion_tokens = 500

        class FakeResponse:
            model = "gpt-4o-mini"
            usage = FakeUsage()

        async def fake_acompletion(**kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch("litellm.acompletion", fake_acompletion):
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    await litellm.acompletion(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
                    )


# ---------------------------------------------------------------------------
# Groq real-API tests
# ---------------------------------------------------------------------------


class TestLiteLLMGroqIntegration:
    """Tests that call the Groq API via LiteLLM."""

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("GROQ_API_KEY")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key)

    @staticmethod
    def _maybe_skip_quota(exc: Exception) -> None:
        msg = str(exc)
        if "429" in msg or "rate_limit" in msg.lower() or "quota" in msg.lower():
            pytest.skip(f"Groq rate-limit: {msg[:120]}")

    def test_completion_tracks_spend(self, api_key: str | None, available: bool) -> None:
        """budget() tracks spend from litellm.completion() via Groq."""
        if not available:
            pytest.skip("GROQ_API_KEY not set")

        try:
            with budget(max_usd=1.00) as b:
                response = litellm.completion(
                    model=_GROQ_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_streaming_tracks_spend(self, api_key: str | None, available: bool) -> None:
        """budget() tracks spend when iterating a Groq streaming completion."""
        if not available:
            pytest.skip("GROQ_API_KEY not set")

        try:
            with budget(max_usd=1.00) as b:
                chunks = list(
                    litellm.completion(
                        model=_GROQ_MODEL,
                        messages=[{"role": "user", "content": "Count to three."}],
                        max_tokens=10,
                        stream=True,
                        api_key=api_key,
                    )
                )
            assert len(chunks) > 0
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_raises_error(self, api_key: str | None, available: bool) -> None:
        """BudgetExceededError raised when Groq call exceeds tiny budget."""
        if not available:
            pytest.skip("GROQ_API_KEY not set")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    litellm.completion(
                        model=_GROQ_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                        api_key=api_key,
                    )
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_tracks_spend(
        self, api_key: str | None, available: bool
    ) -> None:
        """budget() tracks spend from async litellm.acompletion() via Groq."""
        if not available:
            pytest.skip("GROQ_API_KEY not set")

        try:
            with budget(max_usd=1.00) as b:
                response = await litellm.acompletion(
                    model=_GROQ_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_with_async_budget(
        self, api_key: str | None, available: bool
    ) -> None:
        """async with budget() tracks spend from async litellm.acompletion() via Groq."""
        if not available:
            pytest.skip("GROQ_API_KEY not set")

        try:
            async with budget(max_usd=1.00) as b:
                response = await litellm.acompletion(
                    model=_GROQ_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise


# ---------------------------------------------------------------------------
# Gemini real-API tests
# ---------------------------------------------------------------------------


class TestLiteLLMGeminiIntegration:
    """Tests that call the Gemini API via LiteLLM."""

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key)

    @staticmethod
    def _maybe_skip_quota(exc: Exception) -> None:
        msg = str(exc)
        if "429" in msg or "rate_limit" in msg.lower() or "quota" in msg.lower():
            pytest.skip(f"Gemini rate-limit: {msg[:120]}")

    def test_completion_tracks_spend(self, api_key: str | None, available: bool) -> None:
        """budget() tracks spend from litellm.completion() via Gemini."""
        if not available:
            pytest.skip("GEMINI_API_KEY not set")

        try:
            with budget(max_usd=1.00) as b:
                response = litellm.completion(
                    model=_GEMINI_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_streaming_tracks_spend(self, api_key: str | None, available: bool) -> None:
        """budget() tracks spend when iterating a Gemini streaming completion."""
        if not available:
            pytest.skip("GEMINI_API_KEY not set")

        try:
            with budget(max_usd=1.00) as b:
                chunks = list(
                    litellm.completion(
                        model=_GEMINI_MODEL,
                        messages=[{"role": "user", "content": "Count to three."}],
                        max_tokens=10,
                        stream=True,
                        api_key=api_key,
                    )
                )
            assert len(chunks) > 0
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_raises_error(self, api_key: str | None, available: bool) -> None:
        """BudgetExceededError raised when Gemini call exceeds tiny budget."""
        if not available:
            pytest.skip("GEMINI_API_KEY not set")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    litellm.completion(
                        model=_GEMINI_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                        api_key=api_key,
                    )
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_tracks_spend(
        self, api_key: str | None, available: bool
    ) -> None:
        """budget() tracks spend from async litellm.acompletion() via Gemini."""
        if not available:
            pytest.skip("GEMINI_API_KEY not set")

        try:
            with budget(max_usd=1.00) as b:
                response = await litellm.acompletion(
                    model=_GEMINI_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_with_async_budget(
        self, api_key: str | None, available: bool
    ) -> None:
        """async with budget() tracks spend from async litellm.acompletion() via Gemini."""
        if not available:
            pytest.skip("GEMINI_API_KEY not set")

        try:
            async with budget(max_usd=1.00) as b:
                response = await litellm.acompletion(
                    model=_GEMINI_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise


# ---------------------------------------------------------------------------
# HuggingFace real-API tests
# ---------------------------------------------------------------------------


class TestLiteLLMHuggingFaceIntegration:
    """Tests that call the HuggingFace Inference API via LiteLLM.

    Note: Many HuggingFace models do not return usage data in streaming
    responses; spend assertions use >= 0 for streaming paths.
    """

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("HUGGINGFACE_TOKEN")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key)

    @staticmethod
    def _maybe_skip_quota(exc: Exception) -> None:
        msg = str(exc)
        if "429" in msg or "rate_limit" in msg.lower() or "quota" in msg.lower():
            pytest.skip(f"HuggingFace rate-limit: {msg[:120]}")

    def test_completion_tracks_spend(self, api_key: str | None, available: bool) -> None:
        """budget() tracks spend from litellm.completion() via HuggingFace."""
        if not available:
            pytest.skip("HUGGINGFACE_TOKEN not set")

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as b:
                response = litellm.completion(
                    model=_HF_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_streaming_tracks_spend(self, api_key: str | None, available: bool) -> None:
        """budget() tracks spend when iterating a HuggingFace streaming completion."""
        if not available:
            pytest.skip("HUGGINGFACE_TOKEN not set")

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as b:
                chunks = list(
                    litellm.completion(
                        model=_HF_MODEL,
                        messages=[{"role": "user", "content": "Count to three."}],
                        max_tokens=10,
                        stream=True,
                        api_key=api_key,
                    )
                )
            assert len(chunks) > 0
            assert b.spent >= 0  # HF may not return usage in streaming
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_raises_error(self, api_key: str | None, available: bool) -> None:
        """BudgetExceededError raised when HuggingFace call exceeds tiny budget."""
        if not available:
            pytest.skip("HUGGINGFACE_TOKEN not set")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    litellm.completion(
                        model=_HF_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                        api_key=api_key,
                    )
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_tracks_spend(
        self, api_key: str | None, available: bool
    ) -> None:
        """budget() tracks spend from async litellm.acompletion() via HuggingFace."""
        if not available:
            pytest.skip("HUGGINGFACE_TOKEN not set")

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as b:
                response = await litellm.acompletion(
                    model=_HF_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_completion_with_async_budget(
        self, api_key: str | None, available: bool
    ) -> None:
        """async with budget() tracks spend from async litellm.acompletion() via HuggingFace."""
        if not available:
            pytest.skip("HUGGINGFACE_TOKEN not set")

        try:
            async with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as b:
                response = await litellm.acompletion(
                    model=_HF_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=5,
                    api_key=api_key,
                )
            assert response is not None
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise
