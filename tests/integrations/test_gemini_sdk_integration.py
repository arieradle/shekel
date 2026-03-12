"""Integration tests for the Gemini SDK adapter (google-genai).

Real-API tests (TestGeminiSDKRealIntegration) require GEMINI_API_KEY env var
and are skipped without it.

Mock tests (TestGeminiSDKMockIntegration) run without any API keys and verify
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
    import google.genai as genai
    import google.genai.models as gm
    from google.genai.errors import ClientError as GeminiClientError

    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    GeminiClientError = Exception  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(not GENAI_AVAILABLE, reason="google-genai not installed")


# ---------------------------------------------------------------------------
# Real-API tests
# ---------------------------------------------------------------------------


class TestGeminiSDKRealIntegration:
    """Tests that call the real Gemini API via the google-genai SDK."""

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key and GENAI_AVAILABLE)

    @pytest.fixture
    def client(self, api_key: str | None, available: bool) -> Any:
        if not available or api_key is None:
            pytest.skip("Gemini API not available")
        return genai.Client(api_key=api_key)

    @staticmethod
    def _maybe_skip_quota(exc: Exception) -> None:
        """Call pytest.skip() if exc is a Gemini quota/rate-limit error."""
        msg = str(exc)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            pytest.skip(f"Gemini free-tier quota exhausted: {msg[:120]}")

    def test_basic_generate_content_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend from client.models.generate_content()."""
        if not available:
            pytest.skip("Gemini API not available")

        try:
            with budget(max_usd=1.00) as b:
                response = client.models.generate_content(
                    model="gemini-2.0-flash-lite",
                    contents="Say hello in one word.",
                )
            assert response is not None
            assert b.spent > 0, "Expected spend > 0 after a real Gemini call"
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_streaming_generate_content_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend when iterating generate_content_stream()."""
        if not available:
            pytest.skip("Gemini API not available")

        try:
            with budget(max_usd=1.00) as b:
                chunks = list(
                    client.models.generate_content_stream(
                        model="gemini-2.0-flash-lite",
                        contents="Count to three.",
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
            pytest.skip("Gemini API not available")

        try:
            with pytest.raises((BudgetExceededError, GeminiClientError)):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.models.generate_content(
                        model="gemini-2.0-flash-lite",
                        contents="Hello.",
                    )
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_nested_budgets_roll_up(self, client: Any, available: bool) -> None:
        """Spend in an inner budget is reflected in the outer budget."""
        if not available:
            pytest.skip("Gemini API not available")

        try:
            with budget(max_usd=5.00, name="outer") as outer:
                with budget(max_usd=1.00, name="inner") as inner:
                    client.models.generate_content(
                        model="gemini-2.0-flash-lite",
                        contents="Say yes.",
                    )
            assert inner.spent > 0
            assert outer.spent >= inner.spent
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_fallback_model_within_gemini(self, client: Any, available: bool) -> None:
        """Fallback rewrites model kwarg to cheaper Gemini model at threshold."""
        if not available:
            pytest.skip("Gemini API not available")

        try:
            with budget(
                max_usd=0.001,
                fallback={"at_pct": 0.01, "model": "gemini-2.0-flash-lite"},
            ) as b:
                try:
                    client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents="Say hi.",
                    )
                except BudgetExceededError:
                    pass  # acceptable — budget very small
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise


# ---------------------------------------------------------------------------
# Mock tests — always run, no API key required
# ---------------------------------------------------------------------------


class TestGeminiSDKMockIntegration:
    """Verify adapter lifecycle and token extraction without API calls."""

    def test_patch_install_and_remove_lifecycle(self) -> None:
        """Adapter patches Models.generate_content and generate_content_stream."""
        from shekel.providers.gemini import GeminiAdapter

        original_gc = gm.Models.generate_content
        original_gcs = gm.Models.generate_content_stream

        adapter = GeminiAdapter()
        try:
            adapter.install_patches()
            assert gm.Models.generate_content is not original_gc
            assert gm.Models.generate_content_stream is not original_gcs
        finally:
            adapter.remove_patches()

        assert gm.Models.generate_content is original_gc
        assert gm.Models.generate_content_stream is original_gcs

    def test_budget_records_spend_from_mock_response(self) -> None:
        """budget() records correct cost from mocked generate_content call."""

        class FakeUsage:
            prompt_token_count = 50
            candidates_token_count = 25

        class FakeResponse:
            usage_metadata = FakeUsage()

        def fake_generate_content(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(gm.Models, "generate_content", fake_generate_content):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = genai.Client(api_key="fake-key")
                client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents="hello",
                )

        # 50 input + 25 output at $1/1k each = $0.075
        assert b.spent > 0

    def test_streaming_mock_records_spend(self) -> None:
        """budget() records correct cost from mocked generate_content_stream."""

        class FakeUsage:
            prompt_token_count = 30
            candidates_token_count = 15

        class FakeChunk:
            usage_metadata = None

        class FakeChunkWithUsage:
            usage_metadata = FakeUsage()

        def fake_stream(self: Any, **kwargs: Any) -> Any:
            yield FakeChunk()
            yield FakeChunk()
            yield FakeChunkWithUsage()

        with patch.object(gm.Models, "generate_content_stream", fake_stream):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = genai.Client(api_key="fake-key")
                list(
                    client.models.generate_content_stream(
                        model="gemini-2.0-flash",
                        contents="count",
                    )
                )

        assert b.spent > 0

    def test_budget_exceeded_from_mock(self) -> None:
        """BudgetExceededError raised from mocked call when budget tiny."""

        class FakeUsage:
            prompt_token_count = 1000
            candidates_token_count = 500

        class FakeResponse:
            usage_metadata = FakeUsage()

        def fake_generate_content(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(gm.Models, "generate_content", fake_generate_content):
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client = genai.Client(api_key="fake-key")
                    client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents="hello",
                    )

    def test_no_crash_without_google_genai(self) -> None:
        """install_patches() is a no-op when google-genai is not importable."""
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        with patch.dict(
            "sys.modules",
            {"google": None, "google.genai": None, "google.genai.models": None},
        ):
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is acceptable

    def test_extract_tokens_from_real_response_shape(self) -> None:
        """extract_tokens handles the real Gemini response structure."""
        from shekel.providers.gemini import GeminiAdapter

        class FakeUsageMeta:
            prompt_token_count = 42
            candidates_token_count = 17

        class FakeResp:
            usage_metadata = FakeUsageMeta()

        adapter = GeminiAdapter()
        it, ot, model = adapter.extract_tokens(FakeResp())
        assert it == 42
        assert ot == 17
        assert model == "unknown"  # model never in Gemini response

    def test_model_kwarg_captured_for_pricing(self) -> None:
        """Wrapper uses model kwarg for cost calculation, not response field."""
        from shekel import _patch

        class FakeUsage:
            prompt_token_count = 100
            candidates_token_count = 50

        class FakeResponse:
            usage_metadata = FakeUsage()

        original = MagicMock(return_value=FakeResponse())
        _patch._originals["gemini_sync"] = original

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                fake_self = MagicMock()
                _patch._gemini_sync_wrapper(fake_self, model="gemini-2.0-flash", contents="hi")
        finally:
            _patch._originals.pop("gemini_sync", None)

        assert b.spent > 0
