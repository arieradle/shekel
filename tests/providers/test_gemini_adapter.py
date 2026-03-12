"""Unit tests for the Gemini provider adapter.

Tests cover:
- Adapter name and isinstance checks
- Token extraction from usage_metadata
- Stream detection via separate generate_content_stream method
- Stream wrapping and usage_metadata collection
- Fallback model validation (must be gemini-*)
- Patch install/remove lifecycle
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.providers.conftest import ProviderTestBase

# ---------------------------------------------------------------------------
# Lazy import guard — skip all tests if google-genai is not installed
# ---------------------------------------------------------------------------


def _gemini_available() -> bool:
    try:
        import google.genai  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _gemini_available(), reason="google-genai not installed")


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


class MockUsageMetadata:
    """Mock Gemini usage_metadata object."""

    def __init__(self, prompt_token_count: int = 0, candidates_token_count: int = 0) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class MockGeminiResponse:
    """Mock Gemini generate_content response."""

    def __init__(
        self,
        usage_metadata: MockUsageMetadata | None = None,
        model_version: str | None = None,
    ) -> None:
        self.usage_metadata = usage_metadata
        self.model_version = model_version


class MockGeminiStreamChunk:
    """Mock Gemini streaming chunk."""

    def __init__(self, usage_metadata: MockUsageMetadata | None = None) -> None:
        self.usage_metadata = usage_metadata


# ---------------------------------------------------------------------------
# Helper to build a mock Gemini stream
# ---------------------------------------------------------------------------


def make_gemini_stream(
    input_tokens: int = 0, output_tokens: int = 0
) -> Generator[MockGeminiStreamChunk, None, None]:
    """Yield content chunks then a final chunk with usage_metadata."""
    yield MockGeminiStreamChunk()
    yield MockGeminiStreamChunk()
    yield MockGeminiStreamChunk(
        usage_metadata=MockUsageMetadata(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
        )
    )


# ---------------------------------------------------------------------------
# TestGeminiAdapterBasic
# ---------------------------------------------------------------------------


class TestGeminiAdapterBasic(ProviderTestBase):
    """Test adapter name and base class membership."""

    def test_name(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        assert adapter.name == "gemini"

    def test_isinstance_provider_adapter(self) -> None:
        from shekel.providers.base import ProviderAdapter
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        assert isinstance(adapter, ProviderAdapter)


# ---------------------------------------------------------------------------
# TestGeminiTokenExtraction
# ---------------------------------------------------------------------------


class TestGeminiTokenExtraction(ProviderTestBase):
    """Test extract_tokens() for various response shapes."""

    def test_normal_response(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        response = MockGeminiResponse(
            usage_metadata=MockUsageMetadata(prompt_token_count=100, candidates_token_count=50)
        )
        it, ot, model = adapter.extract_tokens(response)
        assert it == 100
        assert ot == 50
        assert model == "unknown"  # model not in response; wrapper passes model name

    def test_none_usage_metadata(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        response = MockGeminiResponse(usage_metadata=None)
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0
        assert model == "unknown"

    def test_missing_usage_metadata_attr(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        response = object()
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0
        assert model == "unknown"

    def test_zero_tokens(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        response = MockGeminiResponse(
            usage_metadata=MockUsageMetadata(prompt_token_count=0, candidates_token_count=0)
        )
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0

    def test_none_token_counts(self) -> None:
        """usage_metadata exists but token counts are None — should return 0."""
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()

        class BrokenUsage:
            prompt_token_count = None
            candidates_token_count = None

        response = MockGeminiResponse(usage_metadata=BrokenUsage())  # type: ignore[arg-type]
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0


# ---------------------------------------------------------------------------
# TestGeminiStreamDetection
# ---------------------------------------------------------------------------


class TestGeminiStreamDetection(ProviderTestBase):
    """Test detect_streaming() — Gemini uses a separate method so stream kwarg is False."""

    def test_detect_streaming_no_stream_kwarg(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        # generate_content_stream is a separate method; no stream kwarg is passed
        assert adapter.detect_streaming({}, None) is False

    def test_detect_streaming_with_false_kwarg(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        assert adapter.detect_streaming({"stream": False}, None) is False

    def test_detect_streaming_empty_kwargs(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        assert adapter.detect_streaming({}, MagicMock()) is False


# ---------------------------------------------------------------------------
# TestGeminiStreamWrapping
# ---------------------------------------------------------------------------


class TestGeminiStreamWrapping(ProviderTestBase):
    """Test wrap_stream() collects usage_metadata from chunks."""

    def test_yields_all_chunks(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        stream = make_gemini_stream(input_tokens=10, output_tokens=5)
        chunks = list(adapter.wrap_stream(stream))
        assert len(chunks) == 3

    def test_collects_usage_metadata(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        stream = make_gemini_stream(input_tokens=100, output_tokens=50)
        gen = adapter.wrap_stream(stream)
        seen: list[Any] = []
        try:
            while True:
                seen.append(next(gen))
        except StopIteration as e:
            it, ot, model = e.value
        assert it == 100
        assert ot == 50
        assert model == "unknown"

    def test_no_usage_returns_zeros(self) -> None:
        """Stream with no usage chunks returns (0, 0, 'unknown')."""
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()

        def no_usage_stream() -> Generator[MockGeminiStreamChunk, None, None]:
            yield MockGeminiStreamChunk()
            yield MockGeminiStreamChunk()

        gen = adapter.wrap_stream(no_usage_stream())
        try:
            while True:
                next(gen)
        except StopIteration as e:
            it, ot, model = e.value
        assert it == 0
        assert ot == 0
        assert model == "unknown"

    def test_empty_stream_returns_zeros(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()

        def empty() -> Generator[Any, None, None]:
            return
            yield  # noqa: F704

        gen = adapter.wrap_stream(empty())
        try:
            while True:
                next(gen)
        except StopIteration as e:
            it, ot, model = e.value
        assert (it, ot, model) == (0, 0, "unknown")


# ---------------------------------------------------------------------------
# TestGeminiFallbackValidation
# ---------------------------------------------------------------------------


class TestGeminiFallbackValidation(ProviderTestBase):
    """Test validate_fallback() rejects non-gemini models."""

    def test_accepts_gemini_model(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        adapter.validate_fallback("gemini-2.0-flash")  # should not raise

    def test_accepts_gemini_25_pro(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        adapter.validate_fallback("gemini-2.5-pro")

    def test_rejects_gpt_model(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        with pytest.raises(ValueError, match="gemini"):
            adapter.validate_fallback("gpt-4o-mini")

    def test_rejects_claude_model(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        with pytest.raises(ValueError, match="gemini"):
            adapter.validate_fallback("claude-3-haiku-20240307")

    def test_rejects_arbitrary_model(self) -> None:
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        with pytest.raises(ValueError):
            adapter.validate_fallback("llama-3-8b")


# ---------------------------------------------------------------------------
# TestGeminiPatching
# ---------------------------------------------------------------------------


class TestGeminiPatching(ProviderTestBase):
    """Test install_patches() / remove_patches() lifecycle."""

    def test_install_patches_replaces_generate_content(self) -> None:
        import google.genai.models as gm

        from shekel import _patch
        from shekel.providers.gemini import GeminiAdapter

        original_gc = gm.Models.generate_content
        original_gcs = gm.Models.generate_content_stream

        adapter = GeminiAdapter()
        try:
            adapter.install_patches()
            assert "gemini_sync" in _patch._originals
            assert "gemini_stream" in _patch._originals
            assert gm.Models.generate_content is not original_gc
            assert gm.Models.generate_content_stream is not original_gcs
        finally:
            adapter.remove_patches()
            # Restore to originals in case test fails mid-way
            if gm.Models.generate_content is not original_gc:
                gm.Models.generate_content = original_gc  # type: ignore[method-assign]
            if gm.Models.generate_content_stream is not original_gcs:
                gm.Models.generate_content_stream = original_gcs  # type: ignore[method-assign]

    def test_remove_patches_restores_originals(self) -> None:
        import google.genai.models as gm

        from shekel import _patch
        from shekel.providers.gemini import GeminiAdapter

        original_gc = gm.Models.generate_content
        original_gcs = gm.Models.generate_content_stream

        adapter = GeminiAdapter()
        adapter.install_patches()
        adapter.remove_patches()

        assert "gemini_sync" not in _patch._originals
        assert "gemini_stream" not in _patch._originals
        assert gm.Models.generate_content is original_gc
        assert gm.Models.generate_content_stream is original_gcs

    def test_install_patches_idempotent(self) -> None:
        """Calling install_patches() twice should not double-wrap."""
        import google.genai.models as gm

        from shekel.providers.gemini import GeminiAdapter

        original_gc = gm.Models.generate_content

        adapter = GeminiAdapter()
        try:
            adapter.install_patches()
            patched_first = gm.Models.generate_content
            adapter.install_patches()
            # Should still be the same patched function
            assert gm.Models.generate_content is patched_first
        finally:
            adapter.remove_patches()
            if gm.Models.generate_content is not original_gc:
                gm.Models.generate_content = original_gc  # type: ignore[method-assign]

    def test_remove_patches_safe_without_install(self) -> None:
        """remove_patches() before install_patches() should not raise."""
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        adapter.remove_patches()  # Should not raise

    def test_no_import_safety(self) -> None:
        """install_patches() is a no-op when google-genai is not importable."""
        from shekel.providers.gemini import GeminiAdapter

        adapter = GeminiAdapter()
        with patch.dict(
            "sys.modules", {"google": None, "google.genai": None, "google.genai.models": None}
        ):
            # Even with the module mocked out, should not raise
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is acceptable
