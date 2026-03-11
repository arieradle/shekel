"""TDD tests for AnthropicAdapter."""

import pytest
from unittest.mock import MagicMock, patch
from tests.providers.conftest import ProviderTestBase, MockAnthropicEvent, MockUsage, MockAnthropicMessage


class TestAnthropicAdapterBasic(ProviderTestBase):

    def test_name_is_anthropic(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        assert adapter.name == "anthropic"

    def test_implements_provider_adapter(self):
        from shekel.providers.base import ProviderAdapter
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        assert isinstance(adapter, ProviderAdapter)


class TestAnthropicTokenExtraction(ProviderTestBase):

    def test_extract_tokens_from_valid_response(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        response = self.make_anthropic_response("claude-3-haiku-20240307", 100, 50)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 100
        assert output_tok == 50
        assert model == "claude-3-haiku-20240307"

    def test_extract_tokens_handles_none_usage(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        response = MagicMock()
        response.usage = None
        response.model = "claude-3-haiku-20240307"
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0

    def test_extract_tokens_handles_missing_attributes(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        response = MagicMock(spec=[])  # No attributes
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 0
        assert output_tok == 0
        assert model == "unknown"

    def test_extract_tokens_uses_input_output_fields(self):
        """Anthropic uses 'input_tokens'/'output_tokens', not 'prompt_tokens'."""
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        response = self.make_anthropic_response("claude-3-opus-20240229", 200, 80)
        input_tok, output_tok, model = adapter.extract_tokens(response)
        assert input_tok == 200
        assert output_tok == 80


class TestAnthropicStreamDetection(ProviderTestBase):

    def test_detect_streaming_true_when_response_is_iterable_no_usage(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        response = MagicMock()
        del response.usage  # No usage attribute
        response.__iter__ = MagicMock(return_value=iter([]))
        assert adapter.detect_streaming({}, response) is True

    def test_detect_streaming_false_when_response_has_usage(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        response = MagicMock()
        response.usage = MagicMock()
        assert adapter.detect_streaming({}, response) is False

    def test_detect_streaming_false_when_response_none(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        assert adapter.detect_streaming({}, None) is False


class TestAnthropicStreamWrapping(ProviderTestBase):

    def test_wrap_stream_yields_all_events(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        stream = self.make_anthropic_stream("claude-3-haiku-20240307", 100, 50)
        events = list(adapter.wrap_stream(stream))
        assert len(events) == 5  # message_start, content_start, content_delta, message_delta, message_stop

    def test_wrap_stream_collects_tokens(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        stream = self.make_anthropic_stream("claude-3-haiku-20240307", 100, 50)
        gen = adapter.wrap_stream(stream)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            input_tok, output_tok, model = e.value
            assert input_tok == 100
            assert output_tok == 50
            assert model == "claude-3-haiku-20240307"

    def test_wrap_stream_returns_unknown_if_no_events(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        gen = adapter.wrap_stream(iter([]))
        try:
            while True:
                next(gen)
        except StopIteration as e:
            input_tok, output_tok, model = e.value
            assert input_tok == 0
            assert output_tok == 0


class TestAnthropicFallbackValidation(ProviderTestBase):

    def test_validate_fallback_accepts_anthropic_models(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        # Should not raise
        adapter.validate_fallback("claude-3-haiku-20240307")
        adapter.validate_fallback("claude-3-opus-20240229")

    def test_validate_fallback_rejects_openai_models(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        with pytest.raises(ValueError, match="OpenAI"):
            adapter.validate_fallback("gpt-4o-mini")

    def test_validate_fallback_rejects_gpt_prefix(self):
        from shekel.providers.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter()
        with pytest.raises(ValueError):
            adapter.validate_fallback("gpt-4o")


class TestAnthropicPatching(ProviderTestBase):

    def test_install_patches_when_anthropic_available(self):
        from shekel.providers.anthropic import AnthropicAdapter
        import anthropic.resources.messages as ant
        adapter = AnthropicAdapter()
        original_sync = ant.Messages.create
        adapter.install_patches()
        assert ant.Messages.create is not original_sync
        # Cleanup
        adapter.remove_patches()

    def test_remove_patches_restores_originals(self):
        from shekel.providers.anthropic import AnthropicAdapter
        import anthropic.resources.messages as ant
        adapter = AnthropicAdapter()
        original_sync = ant.Messages.create
        adapter.install_patches()
        adapter.remove_patches()
        assert ant.Messages.create is original_sync
