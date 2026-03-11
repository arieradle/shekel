"""
Performance validation for Langfuse integration.

This test verifies that the Langfuse adapter adds minimal overhead (<1ms per call).
"""

import time
from unittest.mock import MagicMock

from shekel.integrations import AdapterRegistry
from shekel.integrations.langfuse import LangfuseAdapter


class TestLangfusePerformance:
    """Performance tests for Langfuse integration."""

    def setup_method(self) -> None:
        """Reset registry before each test."""
        AdapterRegistry.clear()

    def test_adapter_overhead_is_minimal(self) -> None:
        """Adapter should add <1ms overhead per cost update."""
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)
        AdapterRegistry.register(adapter)

        # Warm up
        for _ in range(10):
            adapter.on_cost_update(
                {
                    "spent": 1.0,
                    "limit": 10.0,
                    "name": "test",
                    "full_name": "test",
                    "depth": 0,
                    "model": "gpt-4o-mini",
                    "call_cost": 0.1,
                }
            )

        # Measure
        iterations = 1000
        start = time.perf_counter()

        for i in range(iterations):
            adapter.on_cost_update(
                {
                    "spent": float(i) * 0.01,
                    "limit": 10.0,
                    "name": "test",
                    "full_name": "test",
                    "depth": 0,
                    "model": "gpt-4o-mini",
                    "call_cost": 0.01,
                }
            )

        elapsed = time.perf_counter() - start
        avg_per_call = (elapsed / iterations) * 1000  # Convert to ms

        print(f"\nPerformance: {avg_per_call:.4f}ms per call (target: <1ms)")
        assert avg_per_call < 1.0, f"Overhead too high: {avg_per_call:.4f}ms"

    def test_nested_budget_overhead(self) -> None:
        """Nested budgets should have minimal additional overhead."""
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.span.return_value = mock_span

        adapter = LangfuseAdapter(client=mock_client)
        AdapterRegistry.register(adapter)

        # Warm up
        for _ in range(10):
            adapter.on_cost_update(
                {
                    "spent": 1.0,
                    "limit": 10.0,
                    "name": "child",
                    "full_name": "parent.child",
                    "depth": 1,
                    "model": "gpt-4o-mini",
                    "call_cost": 0.1,
                }
            )

        # Measure nested budget updates
        iterations = 1000
        start = time.perf_counter()

        for i in range(iterations):
            adapter.on_cost_update(
                {
                    "spent": float(i) * 0.01,
                    "limit": 10.0,
                    "name": "child",
                    "full_name": "parent.child",
                    "depth": 1,
                    "model": "gpt-4o-mini",
                    "call_cost": 0.01,
                }
            )

        elapsed = time.perf_counter() - start
        avg_per_call = (elapsed / iterations) * 1000

        print(f"\nNested budget performance: {avg_per_call:.4f}ms per call")
        assert avg_per_call < 2.0, f"Nested overhead too high: {avg_per_call:.4f}ms"

    def test_event_emission_overhead(self) -> None:
        """Events (budget_exceeded, fallback) should be fast."""
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        adapter = LangfuseAdapter(client=mock_client)
        AdapterRegistry.register(adapter)

        # Test budget_exceeded events
        iterations = 100  # Fewer iterations for event-heavy operations
        start = time.perf_counter()

        for i in range(iterations):
            adapter.on_budget_exceeded(
                {
                    "budget_name": "test",
                    "spent": 5.0 + i * 0.01,
                    "limit": 5.0,
                    "overage": i * 0.01,
                    "model": "gpt-4o",
                    "tokens": {"input": 1000, "output": 500},
                    "parent_remaining": None,
                }
            )

        elapsed = time.perf_counter() - start
        avg_per_event = (elapsed / iterations) * 1000

        print(f"\nEvent emission performance: {avg_per_event:.4f}ms per event")
        assert avg_per_event < 5.0, f"Event overhead too high: {avg_per_event:.4f}ms"

    def test_no_overhead_when_no_adapter_registered(self) -> None:
        """When no adapter is registered, there should be zero overhead."""
        AdapterRegistry.clear()

        # This should be effectively a no-op
        iterations = 10000
        start = time.perf_counter()

        for i in range(iterations):
            # Simulate what happens in _record() when no adapter is registered
            AdapterRegistry.emit_event(
                "on_cost_update",
                {
                    "spent": float(i) * 0.01,
                    "limit": 10.0,
                    "name": "test",
                    "full_name": "test",
                    "depth": 0,
                    "model": "gpt-4o-mini",
                    "call_cost": 0.01,
                },
            )

        elapsed = time.perf_counter() - start
        avg_per_call = (elapsed / iterations) * 1000

        print(f"\nNo-adapter overhead: {avg_per_call:.4f}ms per call")
        assert avg_per_call < 0.1, f"No-adapter overhead too high: {avg_per_call:.4f}ms"

    def test_multiple_adapters_overhead(self) -> None:
        """Multiple adapters should still maintain low overhead."""
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_trace = MagicMock()
        mock_client1.trace.return_value = mock_trace
        mock_client2.trace.return_value = mock_trace

        adapter1 = LangfuseAdapter(client=mock_client1)
        adapter2 = LangfuseAdapter(client=mock_client2)
        AdapterRegistry.register(adapter1)
        AdapterRegistry.register(adapter2)

        # Measure with 2 adapters
        iterations = 1000
        start = time.perf_counter()

        for i in range(iterations):
            AdapterRegistry.emit_event(
                "on_cost_update",
                {
                    "spent": float(i) * 0.01,
                    "limit": 10.0,
                    "name": "test",
                    "full_name": "test",
                    "depth": 0,
                    "model": "gpt-4o-mini",
                    "call_cost": 0.01,
                },
            )

        elapsed = time.perf_counter() - start
        avg_per_call = (elapsed / iterations) * 1000

        print(f"\nMultiple adapters performance: {avg_per_call:.4f}ms per call")
        # Should be roughly 2x single adapter overhead, but still <2ms
        assert avg_per_call < 2.0, f"Multiple adapter overhead too high: {avg_per_call:.4f}ms"


if __name__ == "__main__":
    """Run performance tests standalone."""
    import sys

    # Run tests
    test = TestLangfusePerformance()

    print("=" * 70)
    print("Langfuse Integration Performance Tests")
    print("=" * 70)

    tests = [
        ("Single adapter overhead", test.test_adapter_overhead_is_minimal),
        ("Nested budget overhead", test.test_nested_budget_overhead),
        ("Event emission overhead", test.test_event_emission_overhead),
        ("No adapter overhead", test.test_no_overhead_when_no_adapter_registered),
        ("Multiple adapters overhead", test.test_multiple_adapters_overhead),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        test.setup_method()
        print(f"\n📊 {name}...")
        try:
            test_func()
            print("✅ PASSED")
            passed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)

    print("\n✅ All performance tests passed!")
    print("🚀 Langfuse integration meets performance targets (<1ms overhead)")
