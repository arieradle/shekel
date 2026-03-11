"""Performance tests for message operations: parsing, token extraction, streaming.

Measures:
- Response object parsing speed
- Token extraction from various response structures
- Streaming detection performance
- Generator wrapping overhead
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.openai import OpenAIAdapter


class TestTokenExtractionPerformance:
    """Benchmark token extraction from response objects."""

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    def test_extract_tokens_openai_typical_response(self, benchmark, openai_adapter):
        """Measure token extraction from typical OpenAI response."""
        response = Mock()
        response.usage = Mock()
        response.usage.prompt_tokens = 42
        response.usage.completion_tokens = 156
        response.model = "gpt-4o-mini"

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (42, 156, "gpt-4o-mini")

    def test_extract_tokens_openai_missing_usage(self, benchmark, openai_adapter):
        """Measure extraction with missing usage field."""
        response = Mock()
        response.usage = None
        response.model = "gpt-4o"

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "gpt-4o")

    def test_extract_tokens_openai_missing_model(self, benchmark, openai_adapter):
        """Measure extraction with missing model field."""
        response = Mock()
        response.usage = Mock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 20
        response.model = None

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (10, 20, "unknown")

    def test_extract_tokens_openai_malformed_response(self, benchmark, openai_adapter):
        """Measure error handling for malformed response."""
        response = Mock(spec=[])  # Empty spec to trigger AttributeError

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_anthropic_typical_response(self, benchmark, anthropic_adapter):
        """Measure token extraction from typical Anthropic response."""
        response = Mock()
        response.usage = Mock()
        response.usage.input_tokens = 87
        response.usage.output_tokens = 234
        response.model = "claude-3-sonnet-20240229"

        def extract():
            return anthropic_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (87, 234, "claude-3-sonnet-20240229")

    def test_extract_tokens_anthropic_missing_usage(self, benchmark, anthropic_adapter):
        """Measure extraction with missing usage field."""
        response = Mock()
        response.usage = None
        response.model = "claude-3-haiku-20240307"

        def extract():
            return anthropic_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "claude-3-haiku-20240307")

    def test_extract_tokens_anthropic_zero_tokens(self, benchmark, anthropic_adapter):
        """Measure extraction with zero token counts."""
        response = Mock()
        response.usage = Mock()
        response.usage.input_tokens = 0
        response.usage.output_tokens = 0
        response.model = "claude-3"

        def extract():
            return anthropic_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "claude-3")

    def test_extract_tokens_anthropic_malformed_response(self, benchmark, anthropic_adapter):
        """Measure error handling for malformed Anthropic response."""
        response = Mock(spec=[])

        def extract():
            return anthropic_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_large_token_counts(self, benchmark, openai_adapter):
        """Measure extraction with large token counts."""
        response = Mock()
        response.usage = Mock()
        response.usage.prompt_tokens = 100000
        response.usage.completion_tokens = 50000
        response.model = "gpt-4"

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (100000, 50000, "gpt-4")


class TestStreamingDetection:
    """Benchmark streaming detection performance."""

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    def test_detect_streaming_openai_stream_true(self, benchmark, openai_adapter):
        """Measure detection with stream=True."""
        kwargs = {"stream": True}
        response = Mock()

        def detect():
            return openai_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is True

    def test_detect_streaming_openai_stream_false(self, benchmark, openai_adapter):
        """Measure detection with stream=False."""
        kwargs = {"stream": False}
        response = Mock()

        def detect():
            return openai_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is False

    def test_detect_streaming_openai_no_stream_kwarg(self, benchmark, openai_adapter):
        """Measure detection without stream kwarg."""
        kwargs = {"model": "gpt-4"}
        response = Mock()

        def detect():
            return openai_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is False

    def test_detect_streaming_openai_many_kwargs(self, benchmark, openai_adapter):
        """Measure detection with many other kwargs."""
        kwargs = {
            "model": "gpt-4",
            "messages": [],
            "temperature": 0.7,
            "max_tokens": 1000,
            "stream": True,
        }
        response = Mock()

        def detect():
            return openai_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is True

    def test_detect_streaming_anthropic_with_iter(self, benchmark, anthropic_adapter):
        """Measure Anthropic detection with iterable response."""
        kwargs = {}
        response = Mock(spec=["__iter__"])  # Only has __iter__, not usage
        response.__iter__ = Mock(return_value=iter([]))

        def detect():
            return anthropic_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is True

    def test_detect_streaming_anthropic_without_iter(self, benchmark, anthropic_adapter):
        """Measure Anthropic detection with non-iterable response."""
        kwargs = {}
        response = Mock(spec=[])

        def detect():
            return anthropic_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is False

    def test_detect_streaming_anthropic_with_usage(self, benchmark, anthropic_adapter):
        """Measure detection when response has usage (not streaming)."""
        kwargs = {}
        response = Mock()
        response.__iter__ = Mock(return_value=iter([]))
        response.usage = Mock()

        def detect():
            return anthropic_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is False

    def test_detect_streaming_anthropic_none_response(self, benchmark, anthropic_adapter):
        """Measure detection with None response."""
        kwargs = {}
        response = None

        def detect():
            return anthropic_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is False


class TestStreamWrapping:
    """Benchmark stream wrapping and token collection."""

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    def test_wrap_stream_openai_no_usage(self, benchmark, openai_adapter):
        """Measure wrapping stream with no usage information."""
        chunks = [Mock(usage=None) for _ in range(10)]

        def wrap():
            gen = openai_adapter.wrap_stream(iter(chunks))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 10

    def test_wrap_stream_openai_with_usage(self, benchmark, openai_adapter):
        """Measure wrapping stream with usage in final chunk."""
        chunks = [Mock(usage=None) for _ in range(9)]
        final_chunk = Mock()
        final_chunk.usage = Mock()
        final_chunk.usage.prompt_tokens = 50
        final_chunk.usage.completion_tokens = 100
        final_chunk.model = "gpt-4"
        chunks.append(final_chunk)

        def wrap():
            gen = openai_adapter.wrap_stream(iter(chunks))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 10

    def test_wrap_stream_openai_multiple_usage_events(self, benchmark, openai_adapter):
        """Measure wrapping with usage in multiple chunks."""
        chunks = []
        for i in range(20):
            chunk = Mock()
            chunk.usage = Mock()
            chunk.usage.prompt_tokens = 10 + i
            chunk.usage.completion_tokens = 20 + i
            chunk.model = "gpt-4"
            chunks.append(chunk)

        def wrap():
            gen = openai_adapter.wrap_stream(iter(chunks))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 20

    def test_wrap_stream_anthropic_no_events(self, benchmark, anthropic_adapter):
        """Measure wrapping Anthropic stream with no token events."""
        events = [Mock(type="content_block_delta") for _ in range(10)]

        def wrap():
            gen = anthropic_adapter.wrap_stream(iter(events))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 10

    def test_wrap_stream_anthropic_message_start(self, benchmark, anthropic_adapter):
        """Measure wrapping with message_start event."""
        events = []
        start_event = Mock()
        start_event.type = "message_start"
        start_event.message = Mock()
        start_event.message.usage = Mock()
        start_event.message.usage.input_tokens = 42
        start_event.message.model = "claude-3"
        events.append(start_event)
        events.extend([Mock(type="content_block_delta") for _ in range(9)])

        def wrap():
            gen = anthropic_adapter.wrap_stream(iter(events))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 10

    def test_wrap_stream_anthropic_message_delta(self, benchmark, anthropic_adapter):
        """Measure wrapping with message_delta event containing tokens."""
        events = []
        events.append(Mock(type="content_block_delta"))
        delta_event = Mock()
        delta_event.type = "message_delta"
        delta_event.usage = Mock()
        delta_event.usage.output_tokens = 156
        events.append(delta_event)
        events.extend([Mock(type="content_block_delta") for _ in range(8)])

        def wrap():
            gen = anthropic_adapter.wrap_stream(iter(events))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 10

    def test_wrap_stream_anthropic_full_sequence(self, benchmark, anthropic_adapter):
        """Measure wrapping with complete Anthropic event sequence."""
        events = []
        start = Mock()
        start.type = "message_start"
        start.message = Mock()
        start.message.usage = Mock()
        start.message.usage.input_tokens = 30
        start.message.model = "claude-3-sonnet"
        events.append(start)

        events.extend([Mock(type="content_block_delta") for _ in range(15)])

        delta = Mock()
        delta.type = "message_delta"
        delta.usage = Mock()
        delta.usage.output_tokens = 87
        events.append(delta)

        def wrap():
            gen = anthropic_adapter.wrap_stream(iter(events))
            consumed = list(gen)
            return len(consumed)

        result = benchmark(wrap)
        assert result == 17


class TestKwargsProcessing:
    """Benchmark kwargs inspection and processing."""

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    def test_process_minimal_kwargs(self, benchmark, openai_adapter):
        """Measure processing minimal kwargs."""
        kwargs = {"stream": True}

        def process():
            return openai_adapter.detect_streaming(kwargs, None)

        result = benchmark(process)
        assert result is True

    def test_process_large_kwargs(self, benchmark, openai_adapter):
        """Measure processing kwargs with many keys."""
        kwargs = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 2000,
            "stream": False,
            "stream_options": {"include_usage": True},
            "timeout": 30,
            "n": 1,
        }

        def process():
            return openai_adapter.detect_streaming(kwargs, None)

        result = benchmark(process)
        assert result is False

    def test_process_deeply_nested_kwargs(self, benchmark, openai_adapter):
        """Measure processing deeply nested kwargs structures."""
        kwargs = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "hello"},
                        {"type": "image", "image": "url"},
                    ],
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "test",
                        "description": "test function",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "stream": True,
        }

        def process():
            return openai_adapter.detect_streaming(kwargs, None)

        result = benchmark(process)
        assert result is True
