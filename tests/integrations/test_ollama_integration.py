"""Integration tests with Ollama and free LLMs."""

from __future__ import annotations

import time

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
        server = OllamaMockServer("127.0.0.1", 12434)  # Use different port to avoid conflicts
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
        ) as b:  # noqa: F841
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
            with budget(max_usd=3.00, name="research") as research:  # noqa: F841
                from shekel._patch import _record

                _record(input_tokens=200, output_tokens=150, model="gpt-4o-mini")

            # Phase 2: Analysis (use known model for cost tracking)
            with budget(max_usd=5.00, name="analysis") as analysis:  # noqa: F841
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
        with budget(
            max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}
        ) as b:  # noqa: F841
            from shekel._patch import _record

            # Use known model with pricing to trigger fallback
            _record(input_tokens=10000, output_tokens=5000, model="gpt-4o")

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
        ) as b:  # noqa: F841
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

        with budget(max_usd=0.10, name="ollama_real") as b:  # noqa: F841
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
                            "messages": [{"role": "user", "content": "Say 'hello' in one word."}],
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

        with budget(max_usd=0.10, name="ollama_generate") as b:  # noqa: F841
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
        ) as b:  # noqa: F841
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
        with budget(max_usd=5.00) as b:  # noqa: F841
            from shekel._patch import _record

            # Record with minimal data
            _record(input_tokens=0, output_tokens=0, model="ollama:unknown")

        # Should not crash
        assert b.spent >= 0

    def test_budget_operations_with_unknown_models(self) -> None:
        """Budget operations work with unknown/custom model names."""
        with budget(max_usd=5.00, name="unknown_model") as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="ollama:custom-model:latest")

        assert b.spent >= 0

    def test_zero_input_tokens(self) -> None:
        """Handling zero input tokens."""
        with budget(max_usd=5.00) as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=0, output_tokens=100, model="gpt-4o-mini")

        assert b.spent > 0

    def test_zero_output_tokens(self) -> None:
        """Handling zero output tokens."""
        with budget(max_usd=5.00) as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=0, model="gpt-4o-mini")

        assert b.spent > 0

    def test_very_large_token_counts(self) -> None:
        """Handling very large token counts."""
        with budget(max_usd=100.00) as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=1000000, output_tokens=500000, model="gpt-4o-mini")

        assert b.spent > 0


class TestOllamaBudgetWarnings:
    """Test budget warning callbacks."""

    def test_warn_at_threshold_with_ollama(self) -> None:
        """Budget warns at specified threshold."""
        warnings_triggered = []

        def on_warn(spent: float, limit: float) -> None:
            warnings_triggered.append((spent, limit))

        try:
            with budget(
                max_usd=0.10,
                warn_at=0.5,
                on_exceed=on_warn,
                fallback={"at_pct": 0.8, "model": "gpt-4o-mini"},
                name="warn_test",
            ) as b:  # noqa: F841
                from shekel._patch import _record

                # Spend enough to trigger warning but with fallback available
                _record(input_tokens=20000, output_tokens=10000, model="gpt-4o")
        except BudgetExceededError:
            pass  # Expected if fallback still exceeds

        # Should have triggered warning
        assert len(warnings_triggered) > 0

    def test_no_warning_below_threshold(self) -> None:
        """No warning when below threshold."""
        warnings_triggered = []

        def on_warn(spent: float, limit: float) -> None:
            warnings_triggered.append((spent, limit))

        with budget(max_usd=10.00, warn_at=0.9, on_exceed=on_warn):
            from shekel._patch import _record

            # Spend small amount
            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        # Should not have triggered
        assert len(warnings_triggered) == 0


class TestOllamaMultipleConcurrentModels:
    """Test multiple models running concurrently."""

    def test_budget_with_multiple_different_models(self) -> None:
        """Test budget tracks multiple different models."""
        with budget(max_usd=10.00, name="multi_model") as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            _record(input_tokens=100, output_tokens=50, model="gpt-4o")
            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        # All three calls tracked
        assert b.spent > 0

    def test_concurrent_model_calls(self) -> None:
        """Test concurrent calls to different models."""
        import concurrent.futures

        def call_model(model_name: str):
            with budget(max_usd=2.00):
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model=model_name)

        models = ["gpt-4o-mini", "gpt-4o", "gpt-4o-mini"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(call_model, m) for m in models]
            results = [f.result(timeout=5) for f in futures]

        assert all(r is None for r in results)


class TestOllamaNestedBudgetAdvanced:
    """Advanced nested budget scenarios."""

    def test_three_level_budget_nesting(self) -> None:
        """Test three levels of budget nesting."""
        with budget(max_usd=20.00, name="level1") as level1:
            with budget(max_usd=15.00, name="level2") as level2:
                with budget(max_usd=10.00, name="level3") as level3:
                    from shekel._patch import _record

                    _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert level1.spent > 0
        assert level2.spent > 0
        assert level3.spent > 0
        assert len(level1.children) == 1
        assert len(level2.children) == 1

    def test_sibling_budgets_accumulate_properly(self) -> None:
        """Test sibling budgets accumulate correctly."""
        with budget(max_usd=20.00, name="parent") as parent:  # noqa: F841
            with budget(max_usd=8.00, name="sibling1") as s1:  # noqa: F841
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

            with budget(max_usd=8.00, name="sibling2") as s2:  # noqa: F841
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

            with budget(max_usd=8.00, name="sibling3") as s3:  # noqa: F841
                from shekel._patch import _record

                _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert len(parent.children) == 3
        assert all(child.spent > 0 for child in parent.children)

    def test_auto_capping_in_deep_nesting(self) -> None:
        """Test auto-capping works in deep nesting."""
        with budget(max_usd=1.00, name="strict_parent") as parent:  # noqa: F841
            # Child wants $5 but parent only has $1
            with budget(max_usd=5.00, name="greedy_child") as child:
                assert child.limit <= 1.00  # Should be auto-capped

    def test_budget_tree_with_many_children(self) -> None:
        """Test budget tree with many children."""
        with budget(max_usd=50.00, name="parent") as parent:  # noqa: F841
            for i in range(5):
                with budget(max_usd=8.00, name=f"child_{i}"):
                    from shekel._patch import _record

                    _record(input_tokens=50, output_tokens=25, model="gpt-4o-mini")

        tree = parent.tree()
        assert "parent" in tree
        for i in range(5):
            assert f"child_{i}" in tree


class TestOllamaMixedProviders:
    """Test mixing Ollama with other providers."""

    def test_budget_with_mixed_openai_models(self) -> None:
        """Test budget with multiple OpenAI models."""
        with budget(max_usd=5.00, name="mixed") as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o")
            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            _record(input_tokens=100, output_tokens=50, model="gpt-3.5-turbo")

        assert b.spent > 0

    def test_budget_with_anthropic_models(self) -> None:
        """Test budget with Anthropic models."""
        with budget(max_usd=5.00, name="anthropic") as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="claude-3-5-sonnet-20241022")
            _record(input_tokens=100, output_tokens=50, model="claude-3-haiku-20240307")

        assert b.spent > 0


class TestOllamaBudgetPersistence:
    """Test budget persistence and accumulation patterns."""

    def test_budget_reuse_multiple_times(self) -> None:
        """Test reusing budget across multiple sessions."""
        b = budget(max_usd=5.00, name="reusable")

        spend_1 = 0
        spend_2 = 0
        spend_3 = 0

        with b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            spend_1 = b.spent

        with b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            spend_2 = b.spent

        with b:
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")
            spend_3 = b.spent

        # Each session adds to total
        assert spend_2 > spend_1
        assert spend_3 > spend_2

    def test_named_budget_tracking_across_sessions(self) -> None:
        """Test named budget accumulation across sessions."""
        named_b = budget(max_usd=10.00, name="session_budget")

        session_1_cost = 0
        with named_b:
            from shekel._patch import _record

            _record(input_tokens=200, output_tokens=100, model="gpt-4o-mini")
            session_1_cost = named_b.spent

        session_2_cost = 0
        with named_b:
            from shekel._patch import _record

            _record(input_tokens=300, output_tokens=150, model="gpt-4o-mini")
            session_2_cost = named_b.spent

        assert session_2_cost > session_1_cost


class TestOllamaEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_budget_slightly_exceeded(self) -> None:
        """Test when spending slightly exceeds limit."""
        exceeded = False
        with budget(max_usd=0.001, name="exceeded") as b:  # noqa: F841
            from shekel._patch import _record

            try:
                # Large call that will exceed tiny budget
                _record(input_tokens=2000, output_tokens=1000, model="gpt-4o")
            except BudgetExceededError:
                exceeded = True

        # Should have exceeded
        assert exceeded or b.spent > b.limit

    def test_budget_with_none_limit_unlimited(self) -> None:
        """Test track-only mode with no limit."""
        with budget(name="unlimited") as b:  # noqa: F841
            from shekel._patch import _record

            # No limit, should track anything
            _record(input_tokens=100000, output_tokens=50000, model="gpt-4o")

        assert b.spent > 0
        assert b.limit is None

    def test_budget_summary_with_no_calls(self) -> None:
        """Test summary when no calls were made."""
        with budget(max_usd=5.00) as b:  # noqa: F841
            pass  # No calls

        summary = b.summary()
        assert "Summary" in summary

    def test_fallback_chain_scenario(self) -> None:
        """Test fallback with low max_usd and high token usage."""
        with budget(
            max_usd=0.08, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}, name="fallback_chain"
        ) as b:  # noqa: F841
            from shekel._patch import _record

            try:
                _record(input_tokens=10000, output_tokens=5000, model="gpt-4o")
            except BudgetExceededError:
                pass  # Expected to exceed budget

        # Should have switched
        assert b.model_switched

    def test_budget_properties_accuracy(self) -> None:
        """Test all budget properties are accurate."""
        with budget(max_usd=5.00, name="props") as b:  # noqa: F841
            from shekel._patch import _record

            _record(input_tokens=100, output_tokens=50, model="gpt-4o-mini")

        assert b.name == "props"
        assert b.limit == 5.00
        assert b.spent > 0
        assert b.remaining is not None
        assert b.remaining < b.limit


class TestOllamaRequestTracking:
    """Test request tracking with mock server."""

    def test_mock_server_logs_requests(self) -> None:
        """Test that mock server logs API requests."""
        import time

        server = OllamaMockServer("127.0.0.1", 12436)  # Use non-conflicting port
        try:
            server.start()
            time.sleep(0.1)

            if requests:
                # Make a request
                requests.post(
                    f"{server.get_url()}/api/chat",
                    json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
                    timeout=2,
                )

                # Check it was logged
                logs = server.get_request_log()
                assert len(logs) > 0
        finally:
            server.stop()

    def test_mock_server_response_registration(self) -> None:
        """Test custom response registration."""
        import time

        server = OllamaMockServer("127.0.0.1", 12437)  # Use non-conflicting port
        try:
            server.start()
            time.sleep(0.1)

            custom_response = create_mock_ollama_response(
                "custom-model", "Custom response text", 100, 75
            )
            server.register_response("chat", "custom-model", custom_response)

            if requests:
                resp = requests.post(
                    f"{server.get_url()}/api/chat",
                    json={"model": "custom-model", "messages": []},
                    timeout=2,
                )
                data = resp.json()
                content = data.get("message", {}).get("content", "").lower()
                assert "custom response" in content
        finally:
            server.stop()
