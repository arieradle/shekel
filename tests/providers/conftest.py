"""Test fixtures and utilities for provider adapter testing."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, NamedTuple


class MockUsage(NamedTuple):
    """Mock usage object matching SDK response structures."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class MockOpenAIResponse:
    """Mock OpenAI API response."""

    def __init__(self, model: str, input_tokens: int, output_tokens: int):
        self.model = model
        self.usage = MockUsage(prompt_tokens=input_tokens, completion_tokens=output_tokens)


class MockOpenAIChunk:
    """Mock OpenAI streaming chunk."""

    def __init__(self, model: str | None = None, usage: MockUsage | None = None):
        self.model = model
        self.usage = usage
        self.choices = []


class MockAnthropicResponse:
    """Mock Anthropic API response."""

    def __init__(self, model: str, input_tokens: int, output_tokens: int):
        self.model = model
        self.usage = MockUsage(input_tokens=input_tokens, output_tokens=output_tokens)


class MockAnthropicEvent:
    """Mock Anthropic streaming event."""

    def __init__(self, event_type: str, message: Any = None, usage: MockUsage | None = None):
        self.type = event_type
        self.message = message
        self.usage = usage


class MockAnthropicMessage:
    """Mock Anthropic message for message_start event."""

    def __init__(self, model: str, input_tokens: int):
        self.model = model
        self.usage = MockUsage(input_tokens=input_tokens)


class ProviderTestBase:
    """Base class providing mock response factories for provider testing."""

    def make_openai_response(
        self, model: str = "gpt-4o", input_tokens: int = 0, output_tokens: int = 0
    ) -> MockOpenAIResponse:
        """Create a mock OpenAI API response."""
        return MockOpenAIResponse(model, input_tokens, output_tokens)

    def make_anthropic_response(
        self, model: str = "claude-3-haiku-20240307", input_tokens: int = 0, output_tokens: int = 0
    ) -> MockAnthropicResponse:
        """Create a mock Anthropic API response."""
        return MockAnthropicResponse(model, input_tokens, output_tokens)

    def make_openai_stream(
        self, model: str = "gpt-4o", input_tokens: int = 0, output_tokens: int = 0
    ) -> Generator[MockOpenAIChunk, None, None]:
        """Create a mock OpenAI streaming response."""
        # Yield some content chunks (without usage)
        yield MockOpenAIChunk(model=model)
        yield MockOpenAIChunk(model=model)
        # Final chunk has usage
        yield MockOpenAIChunk(
            model=model,
            usage=MockUsage(prompt_tokens=input_tokens, completion_tokens=output_tokens),
        )

    def make_anthropic_stream(
        self, model: str = "claude-3-haiku-20240307", input_tokens: int = 0, output_tokens: int = 0
    ) -> Generator[MockAnthropicEvent, None, None]:
        """Create a mock Anthropic streaming response."""
        # Message start event with input tokens
        yield MockAnthropicEvent(
            event_type="message_start", message=MockAnthropicMessage(model, input_tokens)
        )
        # Content events (no tokens)
        yield MockAnthropicEvent(event_type="content_block_start")
        yield MockAnthropicEvent(event_type="content_block_delta")
        # Message delta with output tokens
        yield MockAnthropicEvent(
            event_type="message_delta", usage=MockUsage(output_tokens=output_tokens)
        )
        # Final event
        yield MockAnthropicEvent(event_type="message_stop")
