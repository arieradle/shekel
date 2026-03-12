"""TDD tests for LiteLLMAdapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.providers.conftest import MockLiteLLMChunk, ProviderTestBase


class TestLiteLLMAdapterBasic(ProviderTestBase):

    def test_name_is_litellm(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        assert adapter.name == "litellm"

    def test_implements_provider_adapter(self):
        from shekel.providers.base import ProviderAdapter
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        assert isinstance(adapter, ProviderAdapter)


class TestLiteLLMTokenExtraction(ProviderTestBase):

    def test_extract_tokens_from_valid_response(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        response = self.make_litellm_response("gpt-4o", 100, 50)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 100
        assert output_tok == 50
        assert model == "gpt-4o"

    def test_extract_tokens_handles_none_usage(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        response = MagicMock()
        response.usage = None
        response.model = "gpt-4o"
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0

    def test_extract_tokens_handles_missing_usage_attribute(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        response = MagicMock(spec=[])
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0
        assert model == "unknown"

    def test_extract_tokens_handles_zero_tokens(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        response = self.make_litellm_response("gpt-4o", 0, 0)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0

    def test_extract_tokens_handles_litellm_prefixed_model(self):
        """LiteLLM may return model names like 'openai/gpt-4o'."""
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        response = self.make_litellm_response("openai/gpt-4o", 200, 80)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 200
        assert output_tok == 80
        assert model == "openai/gpt-4o"


class TestLiteLLMStreamDetection(ProviderTestBase):

    def test_detect_streaming_true_when_stream_kwarg_set(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        assert adapter.detect_streaming({"stream": True}, None) is True

    def test_detect_streaming_false_when_no_kwarg(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        assert adapter.detect_streaming({}, None) is False

    def test_detect_streaming_false_when_stream_false(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        assert adapter.detect_streaming({"stream": False}, None) is False


class TestLiteLLMStreamWrapping(ProviderTestBase):

    def test_wrap_stream_yields_all_chunks(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        stream = self.make_litellm_stream("gpt-4o", 100, 50)
        chunks = list(adapter.wrap_stream(stream))
        assert len(chunks) == 3

    def test_wrap_stream_collects_tokens_from_final_chunk(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        stream = self.make_litellm_stream("gpt-4o", 100, 50)
        gen = adapter.wrap_stream(stream)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            input_tok, output_tok, model = e.value
            assert input_tok == 100
            assert output_tok == 50
            assert model == "gpt-4o"

    def test_wrap_stream_returns_unknown_if_no_usage_chunk(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        chunks = [MockLiteLLMChunk(model="gpt-4o", usage=None) for _ in range(3)]
        gen = adapter.wrap_stream(iter(chunks))
        try:
            while True:
                next(gen)
        except StopIteration as e:
            input_tok, output_tok, model = e.value
            assert input_tok == 0
            assert output_tok == 0

    def test_wrap_stream_handles_chunk_attribute_error(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()

        class BrokenUsage:
            def __getattr__(self, name: str) -> None:
                raise AttributeError(f"broken: {name}")

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


class TestLiteLLMPatching(ProviderTestBase):

    def test_install_patches_when_litellm_available(self):
        import litellm

        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        original = litellm.completion
        adapter.install_patches()
        assert litellm.completion is not original
        adapter.remove_patches()

    def test_remove_patches_restores_originals(self):
        import litellm

        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        original = litellm.completion
        adapter.install_patches()
        adapter.remove_patches()
        assert litellm.completion is original

    def test_install_patches_idempotent(self):
        """Calling install_patches twice does not double-wrap."""
        import litellm

        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        original = litellm.completion
        adapter.install_patches()
        after_first = litellm.completion
        adapter.install_patches()  # second call — should no-op
        assert litellm.completion is after_first
        adapter.remove_patches()
        assert litellm.completion is original

    def test_install_patches_safe_without_litellm(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        with patch.dict("sys.modules", {"litellm": None}):
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is fine; no logic error

    def test_remove_patches_safe_without_litellm(self):
        from shekel.providers.litellm import LiteLLMAdapter

        adapter = LiteLLMAdapter()
        with patch.dict("sys.modules", {"litellm": None}):
            adapter.remove_patches()  # Must not raise


class TestLiteLLMCostRecording(ProviderTestBase):

    def test_completion_records_cost(self):
        """litellm.completion inside budget() records spend."""
        import litellm

        from shekel import budget

        mock_response = self.make_litellm_response("gpt-4o-mini", 100, 50)

        with patch.object(litellm, "completion", return_value=mock_response):
            with budget(max_usd=1.0) as b:
                litellm.completion(model="gpt-4o-mini", messages=[])
                assert b.spent > 0

    def test_completion_stream_records_cost(self):
        """litellm.completion(stream=True) inside budget() records spend."""
        import litellm

        from shekel import budget

        mock_stream = self.make_litellm_stream("gpt-4o-mini", 100, 50)

        with patch.object(litellm, "completion", return_value=mock_stream):
            with budget(max_usd=1.0) as b:
                stream = litellm.completion(model="gpt-4o-mini", messages=[], stream=True)
                for _ in stream:
                    pass
                assert b.spent > 0

    @pytest.mark.asyncio
    async def test_acompletion_records_cost(self):
        """litellm.acompletion inside budget() records spend."""
        import litellm

        from shekel import budget

        mock_response = self.make_litellm_response("gpt-4o-mini", 100, 50)

        with patch.object(litellm, "acompletion", new=AsyncMock(return_value=mock_response)):
            with budget(max_usd=1.0) as b:
                await litellm.acompletion(model="gpt-4o-mini", messages=[])
                assert b.spent > 0
