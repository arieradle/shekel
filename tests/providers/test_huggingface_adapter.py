"""Unit tests for the HuggingFace provider adapter.

Tests cover:
- Adapter name and isinstance checks
- Token extraction from OpenAI-compatible usage format
- Stream detection via stream kwarg
- Stream wrapping and usage collection
- Fallback model validation
- Patch install/remove lifecycle
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from tests.providers.conftest import ProviderTestBase

# ---------------------------------------------------------------------------
# Lazy import guard — skip all tests if huggingface-hub is not installed
# ---------------------------------------------------------------------------


def _huggingface_available() -> bool:
    try:
        from huggingface_hub.inference import _client  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _huggingface_available(), reason="huggingface-hub not installed"
)


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


class MockHFUsage:
    """Mock HuggingFace ChatCompletionOutputUsage (OpenAI-compatible)."""

    def __init__(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class MockHFResponse:
    """Mock HuggingFace chat_completion response."""

    def __init__(
        self,
        model: str = "HuggingFaceH4/zephyr-7b-beta",
        usage: MockHFUsage | None = None,
    ) -> None:
        self.model = model
        self.usage = usage


class MockHFStreamChunk:
    """Mock HuggingFace streaming chunk."""

    def __init__(
        self,
        model: str | None = None,
        usage: MockHFUsage | None = None,
    ) -> None:
        self.model = model
        self.usage = usage


# ---------------------------------------------------------------------------
# Helper to build a mock HF stream
# ---------------------------------------------------------------------------


def make_hf_stream(
    model: str = "HuggingFaceH4/zephyr-7b-beta",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> Generator[MockHFStreamChunk, None, None]:
    """Yield content chunks then a final chunk with usage."""
    yield MockHFStreamChunk(model=model)
    yield MockHFStreamChunk(model=model)
    yield MockHFStreamChunk(
        model=model,
        usage=MockHFUsage(prompt_tokens=input_tokens, completion_tokens=output_tokens),
    )


# ---------------------------------------------------------------------------
# TestHuggingFaceAdapterBasic
# ---------------------------------------------------------------------------


class TestHuggingFaceAdapterBasic(ProviderTestBase):
    """Test adapter name and base class membership."""

    def test_name(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        assert adapter.name == "huggingface"

    def test_isinstance_provider_adapter(self) -> None:
        from shekel.providers.base import ProviderAdapter
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        assert isinstance(adapter, ProviderAdapter)


# ---------------------------------------------------------------------------
# TestHuggingFaceTokenExtraction
# ---------------------------------------------------------------------------


class TestHuggingFaceTokenExtraction(ProviderTestBase):
    """Test extract_tokens() for various response shapes."""

    def test_normal_response(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        response = MockHFResponse(
            model="HuggingFaceH4/zephyr-7b-beta",
            usage=MockHFUsage(prompt_tokens=80, completion_tokens=40),
        )
        it, ot, model = adapter.extract_tokens(response)
        assert it == 80
        assert ot == 40
        assert model == "HuggingFaceH4/zephyr-7b-beta"

    def test_none_usage(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        response = MockHFResponse(usage=None)
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0

    def test_missing_usage_attr(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        response = object()
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0
        assert model == "unknown"

    def test_zero_tokens(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        response = MockHFResponse(usage=MockHFUsage(prompt_tokens=0, completion_tokens=0))
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0

    def test_none_token_counts(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()

        class BrokenUsage:
            prompt_tokens = None
            completion_tokens = None

        response = MockHFResponse(usage=BrokenUsage())  # type: ignore[arg-type]
        it, ot, model = adapter.extract_tokens(response)
        assert it == 0
        assert ot == 0


# ---------------------------------------------------------------------------
# TestHuggingFaceStreamDetection
# ---------------------------------------------------------------------------


class TestHuggingFaceStreamDetection(ProviderTestBase):
    """Test detect_streaming() — uses stream=True kwarg."""

    def test_detect_stream_true(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        assert adapter.detect_streaming({"stream": True}, None) is True

    def test_detect_stream_false(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        assert adapter.detect_streaming({"stream": False}, None) is False

    def test_detect_no_stream_kwarg(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        assert adapter.detect_streaming({}, None) is False


# ---------------------------------------------------------------------------
# TestHuggingFaceStreamWrapping
# ---------------------------------------------------------------------------


class TestHuggingFaceStreamWrapping(ProviderTestBase):
    """Test wrap_stream() collects usage from chunks."""

    def test_yields_all_chunks(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        stream = make_hf_stream(input_tokens=10, output_tokens=5)
        chunks = list(adapter.wrap_stream(stream))
        assert len(chunks) == 3

    def test_collects_usage(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        stream = make_hf_stream(
            model="HuggingFaceH4/zephyr-7b-beta",
            input_tokens=100,
            output_tokens=50,
        )
        gen = adapter.wrap_stream(stream)
        seen: list[Any] = []
        try:
            while True:
                seen.append(next(gen))
        except StopIteration as e:
            it, ot, model = e.value
        assert it == 100
        assert ot == 50
        assert model == "HuggingFaceH4/zephyr-7b-beta"

    def test_no_usage_returns_zeros(self) -> None:
        """Streaming chunks with no usage return (0, 0, 'unknown')."""
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()

        def no_usage_stream() -> Generator[MockHFStreamChunk, None, None]:
            yield MockHFStreamChunk()
            yield MockHFStreamChunk()

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
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()

        def empty() -> Generator[Any, None, None]:
            return
            yield  # noqa: unreachable

        gen = adapter.wrap_stream(empty())
        try:
            while True:
                next(gen)
        except StopIteration as e:
            it, ot, model = e.value
        assert (it, ot, model) == (0, 0, "unknown")


# ---------------------------------------------------------------------------
# TestHuggingFaceFallbackValidation
# ---------------------------------------------------------------------------


class TestHuggingFaceFallbackValidation(ProviderTestBase):
    """Test validate_fallback() rejects non-HF models."""

    def test_accepts_hf_model(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        adapter.validate_fallback("HuggingFaceH4/zephyr-7b-beta")  # should not raise

    def test_accepts_any_slash_model(self) -> None:
        """Any model with an org/model format is accepted."""
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        adapter.validate_fallback("mistralai/Mistral-7B-Instruct-v0.3")

    def test_rejects_gpt_model(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        with pytest.raises(ValueError, match="(?i)huggingface"):
            adapter.validate_fallback("gpt-4o-mini")

    def test_rejects_claude_model(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        with pytest.raises(ValueError, match="(?i)huggingface"):
            adapter.validate_fallback("claude-3-haiku-20240307")

    def test_rejects_gemini_model(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        with pytest.raises(ValueError, match="(?i)huggingface"):
            adapter.validate_fallback("gemini-2.0-flash")


# ---------------------------------------------------------------------------
# TestHuggingFacePatching
# ---------------------------------------------------------------------------


class TestHuggingFacePatching(ProviderTestBase):
    """Test install_patches() / remove_patches() lifecycle."""

    def test_install_patches_replaces_chat_completion(self) -> None:
        from huggingface_hub.inference import _client

        from shekel import _patch
        from shekel.providers.huggingface import HuggingFaceAdapter

        original = _client.InferenceClient.chat_completion

        adapter = HuggingFaceAdapter()
        try:
            adapter.install_patches()
            assert "huggingface_sync" in _patch._originals
            assert _client.InferenceClient.chat_completion is not original
        finally:
            adapter.remove_patches()
            if _client.InferenceClient.chat_completion is not original:
                _client.InferenceClient.chat_completion = original  # type: ignore[method-assign]

    def test_remove_patches_restores_original(self) -> None:
        from huggingface_hub.inference import _client

        from shekel import _patch
        from shekel.providers.huggingface import HuggingFaceAdapter

        original = _client.InferenceClient.chat_completion

        adapter = HuggingFaceAdapter()
        adapter.install_patches()
        adapter.remove_patches()

        assert "huggingface_sync" not in _patch._originals
        assert _client.InferenceClient.chat_completion is original

    def test_install_patches_idempotent(self) -> None:
        """Calling install_patches() twice should not double-wrap."""
        from huggingface_hub.inference import _client

        from shekel.providers.huggingface import HuggingFaceAdapter

        original = _client.InferenceClient.chat_completion

        adapter = HuggingFaceAdapter()
        try:
            adapter.install_patches()
            patched_first = _client.InferenceClient.chat_completion
            adapter.install_patches()
            assert _client.InferenceClient.chat_completion is patched_first
        finally:
            adapter.remove_patches()
            if _client.InferenceClient.chat_completion is not original:
                _client.InferenceClient.chat_completion = original  # type: ignore[method-assign]

    def test_remove_patches_safe_without_install(self) -> None:
        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()
        adapter.remove_patches()  # Should not raise

    def test_no_import_safety(self) -> None:
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

    def test_remove_patches_safe_with_missing_import(self) -> None:
        """Lines 61-62: remove_patches() catches ImportError when huggingface-hub unavailable."""
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
            adapter.remove_patches()  # must not raise


# ---------------------------------------------------------------------------
# TestHuggingFaceWrapStreamAttributeError
# ---------------------------------------------------------------------------


class TestHuggingFaceWrapStreamAttributeError(ProviderTestBase):
    """Test wrap_stream() handles chunks with broken usage attributes."""

    def test_wrap_stream_swallows_usage_attribute_error(self) -> None:
        """Lines 101-102: chunk whose usage attrs raise AttributeError is skipped."""
        from unittest.mock import MagicMock

        from shekel.providers.huggingface import HuggingFaceAdapter

        adapter = HuggingFaceAdapter()

        class BrokenUsage:
            def __getattr__(self, name: str) -> None:
                raise AttributeError(name)

        def stream() -> Any:  # type: ignore[return]
            chunk = MagicMock()
            chunk.usage = BrokenUsage()
            yield chunk

        gen = adapter.wrap_stream(stream())
        try:
            while True:
                next(gen)
        except StopIteration as e:
            it, ot, model = e.value
        assert it == 0
        assert ot == 0
        assert model == "unknown"
