# Ollama Integration Tests

This document describes the integration tests for Shekel with Ollama and other free LLM providers.

## Overview

The integration test suite validates that Shekel's budget tracking, enforcement, and observability features work correctly with any LLM provider, not just OpenAI and Anthropic.

The approach is **hybrid**:
- **Mock-based tests** run reliably in CI/CD without external dependencies
- **Real Ollama tests** validate actual behavior when Ollama is available (gracefully skipped otherwise)

## Files

- `ollama_mock.py` — Mock HTTP server that mimics Ollama API format
- `test_ollama_integration.py` — Integration tests with both mock and real Ollama
- `conftest.py` — Pytest fixtures for the mock server

## Running Tests

### All integration tests (with mock server):

```bash
pytest tests/integrations/test_ollama_integration.py -v
```

### Only mock-based tests (no Ollama required):

```bash
pytest tests/integrations/test_ollama_integration.py::TestOllamaBudgetIntegration -v
```

### Real Ollama tests (requires running Ollama on localhost:11434):

First, start Ollama:
```bash
ollama serve
```

Or with Docker:
```bash
docker run -d -p 11434:11434 ollama/ollama
```

Then run tests:
```bash
pytest tests/integrations/test_ollama_integration.py::TestOllamaRealIntegration -v
```

Real Ollama tests will gracefully skip if Ollama is not available.

## Test Coverage

### Mock-Based Tests (TestOllamaBudgetIntegration)

These tests simulate Ollama API responses without requiring a running instance:

- **Budget tracking** — Verify costs are tracked from simulated LLM calls
- **Nested budgets** — Test hierarchical budget enforcement
- **Budget exceeded** — Verify BudgetExceededError is raised correctly
- **Fallback models** — Test model switching when budget is exceeded
- **Budget tree** — Verify hierarchy is correctly represented
- **Concurrent budgets** — Ensure thread safety with multiple budgets
- **Budget summary** — Verify formatted spend reports

### Real Ollama Tests (TestOllamaRealIntegration)

These tests connect to a real Ollama instance (if available):

- **Chat API** — Test with `/api/chat` endpoint
- **Generate API** — Test with `/api/generate` endpoint
- **Token extraction** — Verify token counts from actual responses

### Adapter Integration (TestOllamaAdapterPattern)

- **Observer pattern** — Verify observability adapters receive events from Ollama calls
- **Cost events** — Ensure cost updates are emitted correctly

### Cost Calculation (TestOllamaCostCalculation)

- **Free model handling** — Verify Ollama models track with appropriate costs
- **Budget accumulation** — Test accumulation across multiple sessions

### Error Handling (TestOllamaErrorHandling)

- **Malformed tokens** — Handle missing token counts gracefully
- **Unknown models** — Work with custom model names

## Using the Mock Server

### In Tests

Use the provided fixtures:

```python
def test_with_mock_ollama(ollama_mock_server):
    """Test with mock Ollama."""
    # Register a response
    from tests.integrations.ollama_mock import create_mock_ollama_response

    response = create_mock_ollama_response(
        model="llama2",
        content="Hello!",
        prompt_tokens=100,
        completion_tokens=50
    )
    ollama_mock_server.register_response("chat", "llama2", response)

    # Now test code can access server at:
    url = ollama_mock_server.get_url()  # http://127.0.0.1:11435
```

### In Your Code

The mock server mimics Ollama's HTTP API:

```python
import requests

# POST to /api/chat
response = requests.post(
    "http://127.0.0.1:11435/api/chat",
    json={
        "model": "llama2",
        "messages": [{"role": "user", "content": "Hello"}],
    }
)

# POST to /api/generate
response = requests.post(
    "http://127.0.0.1:11435/api/generate",
    json={
        "model": "llama2",
        "prompt": "Hello",
    }
)
```

## Extending Tests

### Adding New Test Cases

1. Add a test method to the appropriate test class
2. Use `from shekel._patch import _record` to simulate LLM calls
3. Or use the mock server fixtures for HTTP-level testing

Example:

```python
def test_my_ollama_scenario(self) -> None:
    """Test a new scenario."""
    with budget(max_usd=5.00, name="my_test") as b:
        from shekel._patch import _record

        _record(input_tokens=100, output_tokens=50, model="ollama:my-model")

    assert b.spent > 0
```

### Adding Real Ollama Tests

Always check if Ollama is available:

```python
def test_my_real_ollama_feature(self, ollama_available: bool) -> None:
    """Test something with real Ollama."""
    if not ollama_available:
        pytest.skip("Ollama not available")

    # Your test here...
```

### Testing New Providers

To test integration with other free LLM providers (Llama.cpp, vLLM, etc.):

1. Create a new mock server class similar to `OllamaMockServer`
2. Create test class following the same pattern
3. Tests should verify:
   - Token counting works correctly
   - Budget tracking is accurate
   - Adapter events are emitted
   - Nested budgets work correctly

## Cost Handling for Free Models

By default, free/self-hosted models have zero cost in Shekel:

```python
from shekel import budget

with budget(max_usd=1.00):  # Cost is irrelevant for free models
    # Call Ollama or other free LLM
    response = ollama_api.chat(...)
```

To assign custom costs to local models:

```python
with budget(
    max_usd=1.00,
    price_per_1k_tokens={"input": 0.0001, "output": 0.0001}
):
    # Now costs are tracked even though the model is free
    response = ollama_api.chat(...)
```

## CI/CD Integration

In CI/CD pipelines, only mock-based tests run automatically:

```bash
# This runs all tests, but real Ollama tests skip if not available
pytest tests/integrations/test_ollama_integration.py
```

To enable real Ollama tests in CI (e.g., with a Docker sidecar):

```bash
# Environment variable or Docker setup
export OLLAMA_URL=http://localhost:11434
pytest tests/integrations/test_ollama_integration.py
```

## Troubleshooting

### Mock server won't start

If you see port conflicts, the mock server uses port 11435 by default. Change it:

```python
server = OllamaMockServer("127.0.0.1", 12345)  # Custom port
```

### Real Ollama tests failing

1. Verify Ollama is running: `curl http://localhost:11434/api/tags`
2. Check that models are pulled: `ollama list`
3. Pull a model if needed: `ollama pull llama2`

### Requests timeout

Increase the timeout in tests:

```python
response = requests.post(
    "http://localhost:11434/api/chat",
    json={...},
    timeout=60  # Increased from 30
)
```

## Future Improvements

- [ ] Support more Ollama endpoints (embeddings, pull, delete)
- [ ] Test with multiple concurrent Ollama instances
- [ ] Add performance benchmarks for Ollama integration
- [ ] Support LM Studio, Llama.cpp, vLLM in tests
- [ ] Add streaming response tests
- [ ] Create Ollama provider adapter (similar to OpenAIAdapter, AnthropicAdapter)
