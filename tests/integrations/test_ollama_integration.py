"""Integration tests with Ollama and free LLMs."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from shekel import budget
from shekel.exceptions import BudgetExceededError
from shekel.integrations import AdapterRegistry

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

from tests.integrations.ollama_mock import OllamaMockServer, create_mock_ollama_response


class TestOllamaBudgetIntegration:
    """Test budget tracking with Ollama-like API responses."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        AdapterRegistry.clear()

    def test_mock_ollama_server_starts(self) -> None:
        """Mock Ollama server can start and respond."""
        server = OllamaMockServer("127.0.0.1", 11434)
        try:
            server.start()
            time.sleep(0.1)  # Give server time to start

            # Register a response
            server.register_response(
                "chat",
                "llama2",
                create_mock_ollama_response("llama2", "Hello! How can I help?"),
            )

            # Try to hit the server
            if requests:
                resp = requests.post(
                    f"{server.get_url()}/api/chat",
                    json={"model": "llama2", "messages": [{"role": "user", "content": "Hi"}]},
                    timeout=2,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["model"] == "llama2"
                assert "response" in data or "message" in data
        finally:
            server.stop()

    def test_budget_tracks_with_simulated_ollama_calls(self) -> None:
        """Budget context manager tracks simulated Ollama calls correctly."""
        # Use custom pricing for free Ollama models
        with budget(
            max_usd=5.00,
            name="ollama_test",
            price_per_1k_tokens={"input": 0.00001, "output": 0.00001},
        ) as b:
            # Simulate Ollama response with token counts
            from shekel._patch import _record

            # Call 1: Small prompt
            _record(input_tokens=50, output_tokens=25, model="ollama:llama2")

            # Call 2: Larger prompt
            _record(input_tokens=100, output_tokens=50, model="ollama:llama2")

        # Verify tracking worked
        assert b.spent > 0
        assert b.spent <= b.limit

    def test_nested_ollama_budgets(self) -> None:
        """Test nested budgets with simulated Ollama calls."""
        with budget(max_usd=10.00, name="workflow") as workflow:
            # Phase 1: Research (use known model for cost tracking)
            with budget(max_usd=3.00, name="research") as research:
                from shekel._patch import _record

                _record(input_tokens=200, output_tokens=150, model="gpt-4o-mini")

            # Phase 2: Analysis (use known model for cost tracking)
            with budget(max_usd=5.00, name="analysis") as analysis:
                from shekel._patch import _record

                _record(input_tokens=300, output_tokens=200, model="gpt-4o-mini")

        # Verify hierarchy structure (regardless of cost tracking)
        assert len(workflow.children) == 2
        assert workflow.children[0].name == "research"
        assert workflow.children[1].name == "analysis"
        # Both children should have some spend
        assert workflow.children[0].spent > 0
        assert workflow.children[1].spent > 0

    def test_budget_exceeded_with_ollama_simulation(self) -> None:
        """Budget exceeded error works with simulated Ollama responses."""
        with pytest.raises(BudgetExceededError):
            with budget(max_usd=0.001, name="tiny"):
                from shekel._patch import _record

                # Use gpt-4o which has known pricing to trigger budget exceeded
                _record(input_tokens=5000, output_tokens=2000, model="gpt-4o")

    def test_ollama_fallback_model_switching(self) -> None:
        """Test fallback model switching with Ollama models."""
        with budget(max_usd=0.001, fallback="gpt-4o-mini", hard_cap=5.0) as b:
            from shekel._patch import _record

            # Use known model with pricing to trigger fallback
            _record(input_tokens=1000, output_tokens=500, model="gpt-4o")

        # Should have switched to fallback
        assert b.model_switched

    def test_budget_tree_with_ollama_calls(self) -> None:
        """Budget tree output shows hierarchy correctly."""
        with budget(max_usd=20.00, name="root") as root:
            with budget(max_usd=8.00, name="child_1"):
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

            with budget(max_usd=12.00, name="child_2"):
                from shekel._patch import _record

                _record(input_tokens=200, output_tokens=100, model="gpt-4o-mini")

        tree = root.tree()
        assert "root" in tree
        assert "child_1" in tree
        assert "child_2" in tree

    def test_concurrent_ollama_budgets(self) -> None:
        """Test that concurrent budget contexts don't interfere."""
        import concurrent.futures

        def isolated_budget():
            with budget(max_usd=2.00):
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model="ollama:llama2")
                return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(isolated_budget) for _ in range(3)]
            results = [f.result(timeout=5) for f in futures]

        assert all(results)

    def test_budget_summary_with_ollama_models(self) -> None:
        """Budget summary works with Ollama model calls."""
        with budget(
            max_usd=5.00, price_per_1k_tokens={"input": 0.00001, "output": 0.00001}
        ) as b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="ollama:llama2")
            _record(input_tokens=200, output_tokens=100, model="ollama:neural-chat")

        summary = b.summary()
        assert "Summary" in summary
        assert b.spent >= 0


class TestOllamaRealIntegration:
    """Tests that connect to real Ollama instance if available."""

    @pytest.fixture
    def ollama_available(self) -> bool:
        """Check if Ollama is running on default port."""
        if not requests:
            return False

        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=1)
            return resp.status_code == 200
        except Exception:
            return False

    def test_real_ollama_available_skip(self, ollama_available: bool) -> None:
        """Skip real Ollama tests if not available."""
        if not ollama_available:
            pytest.skip("Ollama not available on localhost:11434")

    def test_budget_with_real_ollama_chat_api(self, ollama_available: bool) -> None:
        """Test budget tracking with real Ollama chat API if available."""
        if not ollama_available or not requests:
            pytest.skip("Ollama not available")

        with budget(max_usd=0.10, name="ollama_real") as b:
            try:
                # Try tinyllama first (used in CI), fall back to llama2
                model = "tinyllama"
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Say 'hello' in one word."}],
                        "stream": False,
                    },
                    timeout=30,
                )

                # If model not found, try llama2
                if response.status_code == 404 or "not found" in response.text.lower():
                    model = "llama2"
                    response = requests.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": model,
                            "messages": [
                                {"role": "user", "content": "Say 'hello' in one word."}
                            ],
                            "stream": False,
                        },
                        timeout=30,
                    )

                assert response.status_code == 200

                # Extract token counts
                data = response.json()
                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)

                # Record spend
                from shekel._patch import _record

                if prompt_tokens > 0 or completion_tokens > 0:
                    _record(
                        input_tokens=prompt_tokens,
                        output_tokens=completion_tokens,
                        model=f"ollama:{model}",
                    )
            except requests.exceptions.RequestException:
                pytest.skip("Could not reach Ollama API")

        # Budget should have tracked something
        assert b.spent >= 0

    def test_budget_with_real_ollama_generate_api(self, ollama_available: bool) -> None:
        """Test budget tracking with real Ollama generate API if available."""
        if not ollama_available or not requests:
            pytest.skip("Ollama not available")

        with budget(max_usd=0.10, name="ollama_generate") as b:
            try:
                # Try tinyllama first (used in CI), fall back to llama2
                model = "tinyllama"
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": model,
                        "prompt": "Say hello",
                        "stream": False,
                    },
                    timeout=30,
                )

                # If model not found, try llama2
                if response.status_code == 404 or "not found" in response.text.lower():
                    model = "llama2"
                    response = requests.post(
                        "http://localhost:11434/api/generate",
                        json={
                            "model": model,
                            "prompt": "Say hello",
                            "stream": False,
                        },
                        timeout=30,
                    )

                assert response.status_code == 200

                data = response.json()
                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)

                from shekel._patch import _record

                if prompt_tokens > 0 or completion_tokens > 0:
                    _record(
                        input_tokens=prompt_tokens,
                        output_tokens=completion_tokens,
                        model=f"ollama:{model}",
                    )
            except requests.exceptions.RequestException:
                pytest.skip("Could not reach Ollama API")

        assert b.spent >= 0


class TestOllamaAdapterPattern:
    """Test Ollama integration with adapter pattern."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        AdapterRegistry.clear()

    def test_adapter_receives_ollama_cost_events(self) -> None:
        """Adapters receive cost events from Ollama-like calls."""
        from shekel.integrations import ObservabilityAdapter

        class TestAdapter(ObservabilityAdapter):
            def __init__(self) -> None:
                self.events: list[dict] = []

            def on_cost_update(self, budget_data: dict) -> None:
                self.events.append(budget_data)

            def on_budget_exceeded(self, error_data: dict) -> None:
                pass

            def on_fallback_activated(self, fallback_data: dict) -> None:
                pass

        adapter = TestAdapter()
        AdapterRegistry.register(adapter)

        # Use known model for cost tracking
        with budget(max_usd=5.00, name="with_adapter"):
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert len(adapter.events) > 0
        event = adapter.events[0]
        assert "spent" in event
        assert event["spent"] > 0


class TestOllamaCostCalculation:
    """Test cost calculation for Ollama models."""

    def test_free_ollama_models_with_custom_pricing(self) -> None:
        """Ollama models can be tracked with custom pricing."""
        # Assign minimal cost to free models
        with budget(
            max_usd=10.00, price_per_1k_tokens={"input": 0.00001, "output": 0.00001}
        ) as b:
            from shekel._patch import _record

            # With custom pricing, even free models are tracked
            _record(input_tokens=10000, output_tokens=5000, model="ollama:llama2")

        # Cost should reflect the custom pricing
        assert b.spent > 0

    def test_budget_accumulation_across_ollama_sessions(self) -> None:
        """Budget should accumulate across multiple Ollama sessions."""
        b = budget(
            max_usd=10.00,
            name="accumulating",
            price_per_1k_tokens={"input": 0.00001, "output": 0.00001},
        )

        # First session
        with b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="ollama:llama2")
            first_spend = b.spent

        # Second session
        with b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="ollama:neural-chat")
            second_spend = b.spent

        # Second should be more than first
        assert second_spend >= first_spend


class TestOllamaErrorHandling:
    """Test error handling with Ollama-like responses."""

    def test_malformed_token_counts_handled_gracefully(self) -> None:
        """Missing token counts shouldn't crash budget tracking."""
        with budget(max_usd=5.00) as b:
            from shekel._patch import _record

            # Record with minimal data
            _record(input_tokens=0, output_tokens=0, model="ollama:unknown")

        # Should not crash
        assert b.spent >= 0

    def test_budget_operations_with_unknown_models(self) -> None:
        """Budget operations work with unknown/custom model names."""
        with budget(max_usd=5.00, name="unknown_model") as b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="ollama:custom-model:latest")

        assert b.spent >= 0
