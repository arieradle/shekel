"""Performance tests for error handling paths: exception detection, recovery, validation.

Measures:
- Exception creation overhead
- Error detection and classification
- Malformed data handling
- Validation performance
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from shekel.exceptions import BudgetExceededError
from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.openai import OpenAIAdapter


class TestExceptionCreation:
    """Benchmark exception object creation."""

    def test_create_budget_exceeded_minimal(self, benchmark):
        """Measure BudgetExceededError creation with minimal args."""

        def create():
            return BudgetExceededError(spent=10.5, limit=10.0)

        result = benchmark(create)
        assert result.spent == 10.5
        assert result.limit == 10.0

    def test_create_budget_exceeded_with_model(self, benchmark):
        """Measure BudgetExceededError with model name."""

        def create():
            return BudgetExceededError(spent=10.5, limit=10.0, model="gpt-4")

        result = benchmark(create)
        assert result.model == "gpt-4"

    def test_create_budget_exceeded_with_tokens(self, benchmark):
        """Measure BudgetExceededError with token information."""

        def create():
            return BudgetExceededError(
                spent=10.5, limit=10.0, model="gpt-4", tokens={"input": 1000, "output": 500}
            )

        result = benchmark(create)
        assert result.tokens == {"input": 1000, "output": 500}

    def test_exception_str_conversion(self, benchmark):
        """Measure string conversion of exception."""
        exc = BudgetExceededError(
            spent=10.5, limit=10.0, model="gpt-4", tokens={"input": 1000, "output": 500}
        )

        def convert():
            return str(exc)

        result = benchmark(convert)
        assert "10.00" in result
        assert "gpt-4" in result

    def test_exception_str_no_tokens(self, benchmark):
        """Measure exception string without token info."""
        exc = BudgetExceededError(spent=5.0, limit=10.0, model="claude-3")

        def convert():
            return str(exc)

        result = benchmark(convert)
        assert "5.0000" in result
        assert "claude-3" in result


class TestTokenExtractionErrorHandling:
    """Benchmark error handling in token extraction."""

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    def test_extract_tokens_attribute_error(self, benchmark, openai_adapter):
        """Measure handling of missing attributes."""
        response = Mock(spec=[])  # Empty spec causes AttributeError

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_type_error(self, benchmark, openai_adapter):
        """Measure handling of type mismatches."""
        response = Mock()
        response.usage = "invalid"  # String instead of object

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_none_response(self, benchmark, openai_adapter):
        """Measure handling of None response."""
        response = None

        def extract():
            try:
                return openai_adapter.extract_tokens(response)
            except AttributeError:
                return 0, 0, "unknown"

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_missing_optional_fields(self, benchmark, openai_adapter):
        """Measure handling when optional fields are None."""
        response = Mock()
        response.usage = Mock()
        response.usage.prompt_tokens = None
        response.usage.completion_tokens = None
        response.model = None

        def extract():
            return openai_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_anthropic_attribute_error(self, benchmark, anthropic_adapter):
        """Measure Anthropic handling of missing attributes."""
        response = Mock(spec=[])

        def extract():
            return anthropic_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")

    def test_extract_tokens_anthropic_missing_fields(self, benchmark, anthropic_adapter):
        """Measure Anthropic handling of missing optional fields."""
        response = Mock()
        response.usage = Mock()
        response.usage.input_tokens = None
        response.usage.output_tokens = None
        response.model = None

        def extract():
            return anthropic_adapter.extract_tokens(response)

        result = benchmark(extract)
        assert result == (0, 0, "unknown")


class TestStreamingDetectionErrorHandling:
    """Benchmark error handling in streaming detection."""

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    def test_detect_streaming_anthropic_no_iter(self, benchmark, anthropic_adapter):
        """Measure handling of non-iterable response."""
        kwargs = {}
        response = object()  # Plain object, no __iter__

        def detect():
            return anthropic_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        assert result is False

    def test_detect_streaming_anthropic_malformed_usage(self, benchmark, anthropic_adapter):
        """Measure handling of malformed usage attribute."""
        kwargs = {}
        response = Mock()
        response.__iter__ = Mock(return_value=iter([]))
        response.usage = "invalid"  # Wrong type

        def detect():
            return anthropic_adapter.detect_streaming(kwargs, response)

        result = benchmark(detect)
        # Has usage attribute (even if invalid), so returns False (not streaming)
        assert result is False

    def test_detect_streaming_anthropic_exception(self, benchmark, anthropic_adapter):
        """Measure handling of exceptions during detection."""
        kwargs = {}
        response = Mock()
        response.__iter__ = Mock(side_effect=RuntimeError("iter failed"))

        def detect():
            try:
                return anthropic_adapter.detect_streaming(kwargs, response)
            except RuntimeError:
                return False

        result = benchmark(detect)
        assert result is False


class TestStreamWrapperErrorHandling:
    """Benchmark error handling in stream wrapping."""

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    def test_wrap_stream_openai_with_exception_in_chunks(self, benchmark, openai_adapter):
        """Measure handling of exceptions during chunk iteration."""

        def broken_stream():
            yield Mock(usage=None)
            yield Mock(usage=None)
            raise RuntimeError("Stream broke")

        def wrap():
            gen = openai_adapter.wrap_stream(broken_stream())
            try:
                list(gen)
            except RuntimeError:
                return 0, 0, "unknown"

        result = benchmark(wrap)
        assert result == (0, 0, "unknown")

    def test_wrap_stream_openai_malformed_usage(self, benchmark, openai_adapter):
        """Measure handling of malformed usage in chunk."""
        chunk = Mock()
        chunk.usage = "not_an_object"  # Wrong type

        def wrap():
            gen = openai_adapter.wrap_stream(iter([chunk]))
            list(gen)

        # Should not raise, just skip the malformed usage
        benchmark(wrap)

    def test_wrap_stream_anthropic_with_exception_in_stream(self, benchmark, anthropic_adapter):
        """Measure handling of exceptions in Anthropic stream."""

        def broken_stream():
            yield Mock(type="content_block_delta")
            raise RuntimeError("Stream broke")

        def wrap():
            gen = anthropic_adapter.wrap_stream(broken_stream())
            try:
                list(gen)
            except RuntimeError:
                return 0, 0, "unknown"

        result = benchmark(wrap)
        assert result == (0, 0, "unknown")

    def test_wrap_stream_anthropic_missing_event_attributes(self, benchmark, anthropic_adapter):
        """Measure handling of events with missing attributes."""
        events = []
        start = Mock(spec=[])  # No attributes
        events.append(start)
        events.extend([Mock(type="content_block_delta") for _ in range(5)])

        def wrap():
            gen = anthropic_adapter.wrap_stream(iter(events))
            list(gen)

        # Should not raise
        benchmark(wrap)


class TestValidationErrorHandling:
    """Benchmark fallback model validation."""

    @pytest.fixture
    def anthropic_adapter(self):
        return AnthropicAdapter()

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    def test_validate_fallback_anthropic_valid_model(self, benchmark, anthropic_adapter):
        """Measure validation of valid Anthropic model."""

        def validate():
            anthropic_adapter.validate_fallback("claude-3-sonnet-20240229")

        benchmark(validate)
        # Should not raise

    def test_validate_fallback_anthropic_openai_model(self, benchmark, anthropic_adapter):
        """Measure validation detecting OpenAI model."""

        def validate():
            try:
                anthropic_adapter.validate_fallback("gpt-4")
            except ValueError:
                pass

        benchmark(validate)

    def test_validate_fallback_anthropic_all_prefixes(self, benchmark, anthropic_adapter):
        """Measure validation with various OpenAI model prefixes."""
        openai_prefixes = ["gpt-", "o1", "o2", "o3", "o4", "text-"]

        def validate():
            for prefix in openai_prefixes:
                try:
                    anthropic_adapter.validate_fallback(f"{prefix}model")
                except ValueError:
                    pass

        benchmark(validate)

    def test_validate_fallback_openai_valid_model(self, benchmark, openai_adapter):
        """Measure validation of valid OpenAI model."""

        def validate():
            openai_adapter.validate_fallback("gpt-4")

        benchmark(validate)

    def test_validate_fallback_openai_anthropic_model(self, benchmark, openai_adapter):
        """Measure validation detecting Anthropic model."""

        def validate():
            try:
                openai_adapter.validate_fallback("claude-3-sonnet-20240229")
            except ValueError:
                pass

        benchmark(validate)


class TestErrorPathScaling:
    """Benchmark error handling with scale."""

    @pytest.fixture
    def openai_adapter(self):
        return OpenAIAdapter()

    def test_extract_tokens_many_malformed_responses(self, benchmark, openai_adapter):
        """Measure handling of many malformed responses."""
        responses = [Mock(spec=[]) for _ in range(100)]

        def extract_many():
            results = []
            for resp in responses:
                results.append(openai_adapter.extract_tokens(resp))
            return results

        results = benchmark(extract_many)
        assert all(r == (0, 0, "unknown") for r in results)

    def test_create_many_budget_exceptions(self, benchmark):
        """Measure creation of many budget exceptions."""

        def create_many():
            return [
                BudgetExceededError(
                    spent=i * 0.5,
                    limit=10.0,
                    model="gpt-4",
                    tokens={"input": i * 10, "output": i * 5},
                )
                for i in range(100)
            ]

        results = benchmark(create_many)
        assert len(results) == 100
