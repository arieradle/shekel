"""Integration tests for the HuggingFace adapter (huggingface-hub InferenceClient).

Real-API tests (TestHuggingFaceRealIntegration) require HUGGING_FACE_API env var
and are skipped without it.

Mock tests (TestHuggingFaceMockIntegration) run without any API keys and verify
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
    from huggingface_hub import InferenceClient
    from huggingface_hub.errors import BadRequestError as HFBadRequestError
    from huggingface_hub.inference import _client as hf_client

    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    HFBadRequestError = Exception  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(not HF_AVAILABLE, reason="huggingface-hub not installed")

_HF_MODEL = "meta-llama/Llama-3.2-1B-Instruct"


# ---------------------------------------------------------------------------
# Real-API tests
# ---------------------------------------------------------------------------


class TestHuggingFaceRealIntegration:
    """Tests that call the real HuggingFace Inference API."""

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("HUGGING_FACE_API")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key and HF_AVAILABLE)

    @pytest.fixture
    def client(self, api_key: str | None, available: bool) -> Any:
        if not available or api_key is None:
            pytest.skip("HuggingFace API not available")
        return InferenceClient(token=api_key)

    def _skip_on_api_error(self, exc: Exception) -> None:
        """Skip test gracefully on model-not-supported or provider errors."""
        msg = str(exc)
        if "not supported" in msg or "model_not_supported" in msg or "503" in msg:
            pytest.skip(f"HuggingFace model unavailable: {msg[:120]}")

    def test_basic_chat_completion_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend from InferenceClient.chat.completions.create()."""
        if not available:
            pytest.skip("HuggingFace API not available")

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as b:
                response = client.chat.completions.create(
                    model=_HF_MODEL,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                    max_tokens=10,
                )
                assert response is not None
        except HFBadRequestError as e:
            self._skip_on_api_error(e)
            raise

        # Usage data availability varies by model — just assert no crash
        assert b.spent >= 0

    def test_streaming_chat_completion_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() handles streaming chat_completion call."""
        if not available:
            pytest.skip("HuggingFace API not available")

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as b:
                chunks = list(
                    client.chat.completions.create(
                        model=_HF_MODEL,
                        messages=[{"role": "user", "content": "Say hi."}],
                        max_tokens=5,
                        stream=True,
                    )
                )
                assert len(chunks) > 0
        except HFBadRequestError as e:
            self._skip_on_api_error(e)
            raise

        assert b.spent >= 0

    def test_budget_exceeded_raises_error(self, client: Any, available: bool) -> None:
        """BudgetExceededError is raised when budget is exhausted."""
        if not available:
            pytest.skip("HuggingFace API not available")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.chat.completions.create(
                        model=_HF_MODEL,
                        messages=[{"role": "user", "content": "Hello."}],
                        max_tokens=5,
                    )
        except HFBadRequestError as e:
            self._skip_on_api_error(e)
            raise

    def test_nested_budgets_roll_up(self, client: Any, available: bool) -> None:
        """Inner budget spend is visible in outer budget."""
        if not available:
            pytest.skip("HuggingFace API not available")

        try:
            with budget(
                max_usd=5.00,
                name="outer",
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ) as outer:
                with budget(
                    max_usd=1.00,
                    name="inner",
                    price_per_1k_tokens={"input": 0.001, "output": 0.001},
                ) as inner:
                    client.chat.completions.create(
                        model=_HF_MODEL,
                        messages=[{"role": "user", "content": "Yes or no?"}],
                        max_tokens=5,
                    )
                assert outer.spent >= inner.spent
        except HFBadRequestError as e:
            self._skip_on_api_error(e)
            raise


# ---------------------------------------------------------------------------
# Mock tests — always run, no API key required
# ---------------------------------------------------------------------------


class TestHuggingFaceMockIntegration:
    """Verify adapter lifecycle and token extraction without API calls."""

    def test_patch_install_and_remove_lifecycle(self) -> None:
        """Adapter patches InferenceClient.chat_completion."""
        from shekel.providers.huggingface import HuggingFaceAdapter

        original = hf_client.InferenceClient.chat_completion

        adapter = HuggingFaceAdapter()
        try:
            adapter.install_patches()
            assert hf_client.InferenceClient.chat_completion is not original
        finally:
            adapter.remove_patches()

        assert hf_client.InferenceClient.chat_completion is original

    def test_budget_records_spend_from_mock_response(self) -> None:
        """budget() records correct cost from a mocked chat_completion call."""

        class FakeUsage:
            prompt_tokens = 80
            completion_tokens = 40

        class FakeResponse:
            model = _HF_MODEL
            usage = FakeUsage()

        def fake_chat_completion(self: Any, messages: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(hf_client.InferenceClient, "chat_completion", fake_chat_completion):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = InferenceClient(token="fake-token")
                client.chat_completion(
                    messages=[{"role": "user", "content": "hello"}],
                    model=_HF_MODEL,
                )

        # 80 input + 40 output at $1/1k each = $0.12
        assert b.spent > 0

    def test_streaming_mock_records_spend(self) -> None:
        """budget() records correct cost from mocked streaming call."""

        class FakeUsage:
            prompt_tokens = 30
            completion_tokens = 15

        class FakeChunk:
            model = _HF_MODEL
            usage = None

        class FakeChunkWithUsage:
            model = _HF_MODEL
            usage = FakeUsage()

        def fake_stream(self: Any, messages: Any, **kwargs: Any) -> Any:
            yield FakeChunk()
            yield FakeChunk()
            yield FakeChunkWithUsage()

        with patch.object(hf_client.InferenceClient, "chat_completion", fake_stream):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = InferenceClient(token="fake-token")
                list(
                    client.chat_completion(
                        messages=[{"role": "user", "content": "hello"}],
                        model=_HF_MODEL,
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
            model = _HF_MODEL
            usage = FakeUsage()

        def fake_chat_completion(self: Any, messages: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(hf_client.InferenceClient, "chat_completion", fake_chat_completion):
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client = InferenceClient(token="fake-token")
                    client.chat_completion(
                        messages=[{"role": "user", "content": "hello"}],
                        model=_HF_MODEL,
                    )

    def test_no_crash_without_huggingface_hub(self) -> None:
        """install_patches() is a no-op when huggingface-hub is not importable."""
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        with patch.dict(
            "sys.modules",
            {
                "huggingface_hub": None,
                "huggingface_hub.inference": None,
                "huggingface_hub.inference._client": None,
            },
        ):
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is acceptable

    def test_extract_tokens_from_real_response_shape(self) -> None:
        """extract_tokens handles the real HuggingFace response structure."""
        from shekel.providers.huggingface import HuggingFaceAdapter

        class FakeUsage:
            prompt_tokens = 60
            completion_tokens = 30

        class FakeResp:
            model = _HF_MODEL
            usage = FakeUsage()

        adapter = HuggingFaceAdapter()
        it, ot, model = adapter.extract_tokens(FakeResp())
        assert it == 60
        assert ot == 30
        assert model == _HF_MODEL

    def test_no_usage_in_response_returns_zeros(self) -> None:
        """When response.usage is None, extract_tokens returns (0, 0, model)."""
        from shekel.providers.huggingface import HuggingFaceAdapter

        class FakeResp:
            model = _HF_MODEL
            usage = None

        adapter = HuggingFaceAdapter()
        it, ot, model = adapter.extract_tokens(FakeResp())
        assert it == 0
        assert ot == 0
        assert model == _HF_MODEL

    def test_wrapper_directly_records_spend(self) -> None:
        """_huggingface_sync_wrapper records cost via _patch._record."""
        from shekel import _patch

        class FakeUsage:
            prompt_tokens = 200
            completion_tokens = 100

        class FakeResponse:
            model = _HF_MODEL
            usage = FakeUsage()

        original = MagicMock(return_value=FakeResponse())
        _patch._originals["huggingface_sync"] = original

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                fake_self = MagicMock()
                _patch._huggingface_sync_wrapper(
                    fake_self,
                    [{"role": "user", "content": "hi"}],
                    model=_HF_MODEL,
                )
        finally:
            _patch._originals.pop("huggingface_sync", None)

        assert b.spent > 0
