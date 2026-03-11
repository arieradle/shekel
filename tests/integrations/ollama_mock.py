"""Mock Ollama-compatible API server for integration testing."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, ClassVar


class OllamaMockHandler(BaseHTTPRequestHandler):
    """HTTP request handler for mock Ollama API."""

    # Class variable to store responses (shared across instances)
    _responses: ClassVar[dict[str, Any]] = {}
    _request_log: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        """Handle POST requests to /api/generate or /api/chat."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        request_data = json.loads(body)

        self._request_log.append(request_data)

        if self.path == "/api/generate":
            self._handle_generate(request_data)
        elif self.path == "/api/chat":
            self._handle_chat(request_data)
        else:
            self.send_error(404, "Not Found")

    def _handle_generate(self, request_data: dict[str, Any]) -> None:
        """Handle /api/generate endpoint."""
        model = request_data.get("model", "default")
        prompt = request_data.get("prompt", "")

        # Get mock response from registry
        response_key = f"generate_{model}"
        mock_response = self._responses.get(response_key)

        if not mock_response:
            mock_response = {
                "model": model,
                "created_at": "2024-01-01T00:00:00Z",
                "response": f"Mock response for {prompt[:20]}...",
                "done": True,
                "context": [1, 2, 3],
                "total_duration": 1000000000,
                "load_duration": 100000000,
                "prompt_eval_duration": 200000000,
                "eval_duration": 600000000,
                "eval_count": 50,
                "prompt_eval_count": 20,
            }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(mock_response).encode("utf-8"))

    def _handle_chat(self, request_data: dict[str, Any]) -> None:
        """Handle /api/chat endpoint."""
        model = request_data.get("model", "default")

        # Get mock response from registry
        response_key = f"chat_{model}"
        mock_response = self._responses.get(response_key)

        if not mock_response:
            mock_response = {
                "model": model,
                "created_at": "2024-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": "Mock response from Ollama"},
                "done": True,
                "total_duration": 1000000000,
                "load_duration": 100000000,
                "prompt_eval_duration": 200000000,
                "eval_duration": 600000000,
                "eval_count": 50,
                "prompt_eval_count": 20,
            }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(mock_response).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress logging to avoid noise in tests."""
        pass


class OllamaMockServer:
    """Mock Ollama server for testing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 11434) -> None:
        self.host = host
        self.port = port
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the mock server in a background thread."""
        self.server = HTTPServer((self.host, self.port), OllamaMockHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the mock server."""
        if self.server:
            self.server.shutdown()
            if self.thread:
                self.thread.join(timeout=1)

    def register_response(self, endpoint: str, model: str, response: dict[str, Any]) -> None:
        """Register a mock response for a specific endpoint and model.

        Args:
            endpoint: "generate" or "chat"
            model: Model name
            response: Response dict to return
        """
        key = f"{endpoint}_{model}"
        OllamaMockHandler._responses[key] = response

    def get_request_log(self) -> list[dict[str, Any]]:
        """Get log of all requests received."""
        return OllamaMockHandler._request_log.copy()

    def clear_request_log(self) -> None:
        """Clear request log."""
        OllamaMockHandler._request_log.clear()

    def get_url(self) -> str:
        """Get the base URL for this server."""
        return f"http://{self.host}:{self.port}"


def create_mock_ollama_response(
    model: str,
    content: str,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> dict[str, Any]:
    """Create a mock Ollama chat response.

    Args:
        model: Model name
        content: Response content
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens

    Returns:
        Mock Ollama response dict
    """
    return {
        "model": model,
        "created_at": "2024-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "total_duration": 1000000000,
        "load_duration": 100000000,
        "prompt_eval_duration": 200000000,
        "eval_duration": 600000000,
        "eval_count": completion_tokens,
        "prompt_eval_count": prompt_tokens,
    }
