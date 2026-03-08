from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock

import pytest


def make_openai_response(model: str, input_tokens: int, output_tokens: int) -> MagicMock:
    response = MagicMock()
    response.model = model
    response.usage.prompt_tokens = input_tokens
    response.usage.completion_tokens = output_tokens
    return response


def make_anthropic_response(model: str, input_tokens: int, output_tokens: int) -> MagicMock:
    response = MagicMock()
    response.model = model
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    # Non-streaming: has usage attribute directly
    response.__iter__ = MagicMock(side_effect=TypeError("not iterable"))
    return response


def make_openai_stream(model: str, input_tokens: int, output_tokens: int) -> list[MagicMock]:
    """Returns a list of chunks; last chunk has .usage set."""
    chunk1 = MagicMock()
    chunk1.usage = None
    chunk1.model = model

    chunk2 = MagicMock()
    chunk2.usage = None
    chunk2.model = model

    final_chunk = MagicMock()
    final_chunk.usage.prompt_tokens = input_tokens
    final_chunk.usage.completion_tokens = output_tokens
    final_chunk.model = model

    return [chunk1, chunk2, final_chunk]


def make_anthropic_stream(model: str, input_tokens: int, output_tokens: int) -> list[MagicMock]:
    """Returns a list of Anthropic events."""
    start = MagicMock()
    start.type = "message_start"
    start.message.usage.input_tokens = input_tokens
    start.message.model = model

    delta = MagicMock()
    delta.type = "message_delta"
    delta.usage.output_tokens = output_tokens

    stop = MagicMock()
    stop.type = "message_stop"

    return [start, delta, stop]


@pytest.fixture
def openai_response() -> MagicMock:
    return make_openai_response("gpt-4o", 500, 200)


@pytest.fixture
def anthropic_response() -> MagicMock:
    return make_anthropic_response("claude-3-5-sonnet-20241022", 400, 150)


@pytest.fixture
def openai_stream() -> list[MagicMock]:
    return make_openai_stream("gpt-4o", 500, 200)


@pytest.fixture
def anthropic_stream() -> list[MagicMock]:
    return make_anthropic_stream("claude-3-5-sonnet-20241022", 400, 150)
