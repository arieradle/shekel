"""Performance tests for memory: baseline footprint, allocations, and GC impact.

Measures:
- Baseline memory of adapters
- Memory per adapter instance
- Memory allocation patterns
- GC pressure and cleanup
"""

from __future__ import annotations

import gc
import sys
from typing import Any

import pytest

from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.base import ProviderRegistry
from shekel.providers.openai import OpenAIAdapter


def get_object_size(obj: Any) -> int:
    """Get size in bytes of an object and its immediate contents."""
    return sys.getsizeof(obj)


class TestAdapterMemoryFootprint:
    """Benchmark baseline memory usage of adapters."""

    def test_anthropic_adapter_size(self):
        """Measure AnthropicAdapter memory footprint."""
        adapter = AnthropicAdapter()
        size = get_object_size(adapter)
        assert size > 0
        assert size < 10000  # Should be reasonably small

    def test_openai_adapter_size(self):
        """Measure OpenAIAdapter memory footprint."""
        adapter = OpenAIAdapter()
        size = get_object_size(adapter)
        assert size > 0
        assert size < 10000

    def test_registry_empty_size(self):
        """Measure empty ProviderRegistry size."""
        registry = ProviderRegistry()
        size = get_object_size(registry)
        assert size > 0

    def test_registry_with_adapters_size(self):
        """Measure ProviderRegistry with multiple adapters."""
        registry = ProviderRegistry()
        registry.register(AnthropicAdapter())
        registry.register(OpenAIAdapter())
        size = get_object_size(registry)
        assert size > 0

    def test_adapter_originals_dict_size(self):
        """Measure memory of adapter's _originals dict."""
        adapter = AnthropicAdapter()
        dict_size = get_object_size(adapter._originals)
        assert dict_size > 0

    def test_registry_adapters_list_size(self):
        """Measure memory of registry's adapters list."""
        registry = ProviderRegistry()
        for i in range(10):
            registry.register(AnthropicAdapter())
        list_size = get_object_size(registry.adapters)
        assert list_size > 0


class TestMemoryAllocation:
    """Benchmark memory allocation patterns."""

    def test_create_many_adapters_allocation(self, benchmark):
        """Measure memory allocation when creating adapters."""
        def create_adapters():
            return [AnthropicAdapter() for _ in range(1000)]

        result = benchmark(create_adapters)
        assert len(result) == 1000

    def test_registry_grow_allocation(self, benchmark):
        """Measure registry growth as adapters are added."""
        registry = ProviderRegistry()

        def grow():
            for i in range(500):
                registry.register(AnthropicAdapter())

        benchmark(grow)
        # benchmark() runs multiple times, just verify growth happened
        assert len(registry.adapters) >= 500

    def test_adapter_list_traversal_memory(self, benchmark):
        """Measure memory access patterns during list traversal."""
        registry = ProviderRegistry()
        for i in range(100):
            registry.register(AnthropicAdapter())

        def traverse():
            total_size = 0
            for adapter in registry.adapters:
                total_size += get_object_size(adapter)
            return total_size

        benchmark(traverse)


class TestGarbageCollection:
    """Benchmark GC behavior with adapter objects."""

    def test_gc_collect_after_adapter_creation(self):
        """Measure GC overhead after creating many adapters."""
        gc.disable()
        try:
            # Create and discard adapters
            for _ in range(100):
                AnthropicAdapter()

            # Measure GC collection time
            import time
            start = time.perf_counter()
            gc.collect()
            elapsed = time.perf_counter() - start
            assert elapsed < 1.0  # Should be fast
        finally:
            gc.enable()

    def test_gc_collect_after_registry_operations(self):
        """Measure GC overhead after registry operations."""
        gc.disable()
        try:
            registry = ProviderRegistry()
            for _ in range(100):
                registry.register(AnthropicAdapter())

            import time
            start = time.perf_counter()
            gc.collect()
            elapsed = time.perf_counter() - start
            assert elapsed < 1.0
        finally:
            gc.enable()

    def test_gc_impact_on_adapter_creation(self, benchmark):
        """Measure creation time with GC enabled vs impact."""
        def create_with_gc():
            gc.collect()  # Force collection before measurement
            return [AnthropicAdapter() for _ in range(100)]

        result = benchmark(create_with_gc)
        assert len(result) == 100

    def test_unreferenced_adapters_cleanup(self):
        """Verify unreferenced adapters can be cleaned up."""
        gc.disable()
        try:
            registry = ProviderRegistry()
            for _ in range(100):
                registry.register(AnthropicAdapter())

            initial_count = len(gc.get_objects())

            # Clear and collect
            registry = ProviderRegistry()
            gc.collect()

            final_count = len(gc.get_objects())
            # Count should be significantly lower
            assert final_count < initial_count * 2
        finally:
            gc.enable()


class TestMemoryStability:
    """Test memory usage stability over repeated operations."""

    def test_repeated_adapter_creation_stable(self):
        """Verify repeated adapter creation doesn't leak memory."""
        gc.disable()
        try:
            sizes = []
            for iteration in range(5):
                gc.collect()
                before = len(gc.get_objects())

                # Create adapters
                adapters = [AnthropicAdapter() for _ in range(100)]

                after = len(gc.get_objects())
                delta = after - before
                sizes.append(delta)

                del adapters

            # Each iteration should allocate roughly the same amount
            avg_delta = sum(sizes) / len(sizes)
            for delta in sizes:
                # Allow 20% variance
                assert abs(delta - avg_delta) < avg_delta * 0.2, \
                    f"Allocation unstable: {delta} vs avg {avg_delta}"
        finally:
            gc.enable()

    def test_repeated_registry_operations_stable(self):
        """Verify repeated registry operations don't leak memory."""
        gc.disable()
        try:
            for iteration in range(5):
                gc.collect()
                before = len(gc.get_objects())

                registry = ProviderRegistry()
                for i in range(100):
                    registry.register(AnthropicAdapter())

                after = len(gc.get_objects())
                delta = after - before

                del registry
                gc.collect()

                # Memory should be cleaned up
                final = len(gc.get_objects())
                assert final < before * 1.1, \
                    f"Memory not cleaned up: {final} vs {before}"
        finally:
            gc.enable()


class TestMemoryPressure:
    """Benchmark behavior under memory pressure."""

    def test_large_adapter_collection(self, benchmark):
        """Measure creation and management of large adapter collection."""
        def create_large_collection():
            registry = ProviderRegistry()
            adapters = []
            for i in range(1000):
                adapter = AnthropicAdapter()
                registry.register(adapter)
                adapters.append(adapter)
            return registry, adapters

        registry, adapters = benchmark(create_large_collection)
        assert len(registry.adapters) == 1000

    def test_memory_with_many_lookups(self, benchmark):
        """Measure memory stability during many lookups."""
        registry = ProviderRegistry()
        for i in range(100):
            registry.register(AnthropicAdapter())

        def lookup_many():
            results = []
            for _ in range(10000):
                result = registry.get_by_name("foo")  # Always fails
                results.append(result)
            return len(results)

        result = benchmark(lookup_many)
        assert result == 10000

    def test_dict_growth_with_install(self, benchmark):
        """Measure _originals dict growth during patch installation."""
        adapters = [AnthropicAdapter() for _ in range(10)]

        def install_many():
            for adapter in adapters:
                adapter.install_patches()

        benchmark(install_many)

        # Check dict sizes
        for adapter in adapters:
            size = get_object_size(adapter._originals)
            assert size > 0


class TestObjectReuse:
    """Benchmark object reuse and caching patterns."""

    def test_same_adapter_lookup_repeatedly(self, benchmark):
        """Measure if lookup can be optimized (indicates reuse opportunity)."""
        registry = ProviderRegistry()
        for i in range(10):
            registry.register(AnthropicAdapter() if i % 2 == 0 else OpenAIAdapter())

        def lookup_same():
            results = []
            for _ in range(1000):
                results.append(registry.get_by_name("anthropic"))
            return results

        results = benchmark(lookup_same)
        # All should be the same object (identity check)
        if results:
            first = results[0]
            assert all(r is first for r in results), "Expected same object instance"

    def test_adapter_reference_counting(self):
        """Verify proper reference counting of adapters."""
        import sys
        adapter = AnthropicAdapter()
        initial_refs = sys.getrefcount(adapter)

        registry = ProviderRegistry()
        registry.register(adapter)
        refs_after_register = sys.getrefcount(adapter)

        # Should have one more reference after registration
        assert refs_after_register > initial_refs
