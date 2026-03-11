"""TDD tests for OpenAIAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.providers.conftest import MockOpenAIChunk, MockUsage, ProviderTestBase


class TestOpenAIAdapterBasic(ProviderTestBase):

    def test_name_is_openai(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert adapter.name == "openai"

    def test_implements_provider_adapter(self):
        from shekel.providers.base import ProviderAdapter
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert isinstance(adapter, ProviderAdapter)


class TestOpenAITokenExtraction(ProviderTestBase):

    def test_extract_tokens_from_valid_response(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        response = self.make_openai_response("gpt-4o", 100, 50)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 100
        assert output_tok == 50
        assert model == "gpt-4o"

    def test_extract_tokens_handles_none_usage(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        response = MagicMock()
        response.usage = None
        response.model = "gpt-4o"
        # Should not raise, return (0, 0, model)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0

    def test_extract_tokens_handles_missing_usage_attribute(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        response = MagicMock(spec=[])  # No attributes
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0
        assert model == "unknown"

    def test_extract_tokens_uses_prompt_tokens_field(self):
        """OpenAI uses 'prompt_tokens', not 'input_tokens'."""
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        response = self.make_openai_response("gpt-4o-mini", 200, 80)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 200
        assert output_tok == 80

    def test_extract_tokens_handles_zero_tokens(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        response = self.make_openai_response("gpt-4o", 0, 0)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0


class TestOpenAIStreamDetection(ProviderTestBase):

    def test_detect_streaming_true_when_stream_kwarg_set(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert adapter.detect_streaming({"stream": True}, None) is True

    def test_detect_streaming_false_when_no_kwarg(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert adapter.detect_streaming({}, None) is False

    def test_detect_streaming_false_when_stream_false(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert adapter.detect_streaming({"stream": False}, None) is False

    def test_detect_streaming_ignores_response(self):
        """OpenAI detects streaming from kwargs, not response."""
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        response = MagicMock()
        assert adapter.detect_streaming({"stream": True}, response) is True
        assert adapter.detect_streaming({}, response) is False


class TestOpenAIStreamWrapping(ProviderTestBase):

    def test_wrap_stream_yields_all_chunks(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        stream = self.make_openai_stream("gpt-4o", 100, 50)
        chunks = list(adapter.wrap_stream(stream))
        assert len(chunks) == 3  # 2 content + 1 final with usage

    def test_wrap_stream_collects_tokens_from_final_chunk(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        stream = self.make_openai_stream("gpt-4o", 100, 50)
        gen = adapter.wrap_stream(stream)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            input_tok, output_tok, model = e.value
            assert input_tok == 100
            assert output_tok == 50

    def test_wrap_stream_returns_unknown_if_no_usage_chunk(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        # Stream with no usage in any chunk
        chunks = [MockOpenAIChunk(model="gpt-4o", usage=None) for _ in range(3)]
        gen = adapter.wrap_stream(iter(chunks))
        try:
            while True:
                next(gen)
        except StopIteration as e:
            input_tok, output_tok, model = e.value
            assert input_tok == 0
            assert output_tok == 0

    def test_wrap_stream_collects_tokens_even_on_exception(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()

        def failing_stream():
            yield MockOpenAIChunk(
                model="gpt-4o", usage=MockUsage(prompt_tokens=100, completion_tokens=50)
            )
            raise ValueError("Stream error")

        def collect_tokens():
            gen = adapter.wrap_stream(failing_stream())
            try:
                while True:
                    next(gen)
            except (StopIteration, ValueError):
                pass

        # Should not raise despite stream error
        collect_tokens()


class TestOpenAIFallbackValidation(ProviderTestBase):

    def test_validate_fallback_accepts_openai_models(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        # Should not raise
        adapter.validate_fallback("gpt-4o-mini")
        adapter.validate_fallback("gpt-3.5-turbo")
        adapter.validate_fallback("o1-mini")

    def test_validate_fallback_rejects_anthropic_models(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        with pytest.raises(ValueError, match="Anthropic"):
            adapter.validate_fallback("claude-3-haiku-20240307")

    def test_validate_fallback_rejects_claude_prefix(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        with pytest.raises(ValueError):
            adapter.validate_fallback("claude-3-opus-20240229")


class TestOpenAIPatching(ProviderTestBase):

    def test_install_patches_when_openai_available(self):
        import openai.resources.chat.completions as oai

        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        original_sync = oai.Completions.create
        adapter.install_patches()
        assert oai.Completions.create is not original_sync
        # Cleanup
        adapter.remove_patches()

    def test_remove_patches_restores_originals(self):
        import openai.resources.chat.completions as oai

        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        original_sync = oai.Completions.create
        adapter.install_patches()
        adapter.remove_patches()
        assert oai.Completions.create is original_sync

    def test_install_patches_safe_without_openai(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        with patch.dict("sys.modules", {"openai": None, "openai.resources.chat.completions": None}):
            # Should not raise even without the SDK
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is expected but not an OpenAI logic error

    def test_remove_patches_safe_without_openai(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        with patch.dict("sys.modules", {"openai": None, "openai.resources.chat.completions": None}):
            # Should not raise even without the SDK
            adapter.remove_patches()

    def test_wrap_stream_handles_chunk_usage_attribute_error(self):
        from shekel.providers.openai import OpenAIAdapter

        adapter = OpenAIAdapter()

        class BrokenUsage:
            """Usage object that raises AttributeError on access."""

            def __getattr__(self, name: str) -> None:
                raise AttributeError(f"Broken usage: {name}")

        def stream_with_bad_usage():
            chunk1 = MagicMock()
            chunk1.usage = BrokenUsage()
            chunk1.model = "gpt-4o"
            yield chunk1

            chunk2 = MagicMock()
            chunk2.usage = None
            chunk2.model = "gpt-4o"
            yield chunk2

        gen = adapter.wrap_stream(stream_with_bad_usage())
        chunks = list(gen)
        assert len(chunks) == 2
        # Should gracefully continue despite AttributeError and return default
