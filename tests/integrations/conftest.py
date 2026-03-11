"""Pytest fixtures for integration tests."""

from __future__ import annotations

import pytest

from tests.integrations.ollama_mock import OllamaMockServer, create_mock_ollama_response


@pytest.fixture
def ollama_mock_server():
    """Fixture that provides a mock Ollama server."""
    server = OllamaMockServer("127.0.0.1", 12435)  # Use non-conflicting port
    server.start()
    yield server
    server.stop()


@pytest.fixture
def ollama_mock_server_with_responses(ollama_mock_server):
    """Fixture with pre-registered common responses."""
    ollama_mock_server.register_response(
        "chat",
        "llama2",
        create_mock_ollama_response("llama2", "Hello! I'm ready to help.", 100, 50),
    )
    ollama_mock_server.register_response(
        "chat",
        "neural-chat",
        create_mock_ollama_response("neural-chat", "Neural chat model response.", 120, 60),
    )
    ollama_mock_server.register_response(
        "generate",
        "llama2",
        {
            "model": "llama2",
            "created_at": "2024-01-01T00:00:00Z",
            "response": "Generated text response",
            "done": True,
            "context": [1, 2, 3],
            "total_duration": 1000000000,
            "load_duration": 100000000,
            "prompt_eval_duration": 200000000,
            "eval_duration": 600000000,
            "eval_count": 50,
            "prompt_eval_count": 100,
        },
    )
    yield ollama_mock_server
