"""Performance tests for ProviderRegistry initialization, resolution, and caching.

Measures:
- Registry creation time
- Adapter resolution speed (cache cold/warm)
- Lookup performance with many adapters
- Registry state mutations
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from shekel.providers.base import ProviderAdapter, ProviderRegistry


class DummyAdapter(ProviderAdapter):
    """Minimal adapter for performance testing."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def install_patches(self) -> None:
        pass

    def remove_patches(self) -> None:
        pass

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        return 0, 0, self._name

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        return False

    def wrap_stream(self, stream: Any):
        yield stream
        return 0, 0, self._name


class TestRegistryInitialization:
    """Benchmark registry creation and initial state."""

    def test_registry_creation_time(self, benchmark):
        """Measure registry instantiation overhead."""
        def create_registry():
            return ProviderRegistry()

        result = benchmark(create_registry)
        assert result is not None
        assert len(result.adapters) == 0

    def test_registry_creation_with_adapters(self, benchmark):
        """Measure registry creation and immediate registration."""
        def create_with_adapters():
            reg = ProviderRegistry()
            for i in range(10):
                reg.register(DummyAdapter(f"provider_{i}"))
            return reg

        result = benchmark(create_with_adapters)
        assert len(result.adapters) == 10


class TestAdapterResolution:
    """Benchmark lookup performance for adapters."""

    @pytest.fixture
    def registry_with_adapters(self):
        """Registry with multiple adapters for resolution tests."""
        reg = ProviderRegistry()
        for i in range(20):
            reg.register(DummyAdapter(f"provider_{i:02d}"))
        return reg

    def test_get_by_name_first_adapter(self, benchmark, registry_with_adapters):
        """Measure lookup of first registered adapter."""
        def lookup():
            return registry_with_adapters.get_by_name("provider_00")

        result = benchmark(lookup)
        assert result is not None
        assert result.name == "provider_00"

    def test_get_by_name_middle_adapter(self, benchmark, registry_with_adapters):
        """Measure lookup of middle adapter (typical case)."""
        def lookup():
            return registry_with_adapters.get_by_name("provider_10")

        result = benchmark(lookup)
        assert result is not None
        assert result.name == "provider_10"

    def test_get_by_name_last_adapter(self, benchmark, registry_with_adapters):
        """Measure lookup of last registered adapter (worst case)."""
        def lookup():
            return registry_with_adapters.get_by_name("provider_19")

        result = benchmark(lookup)
        assert result is not None
        assert result.name == "provider_19"

    def test_get_by_name_not_found(self, benchmark, registry_with_adapters):
        """Measure lookup of non-existent adapter (full scan)."""
        def lookup():
            return registry_with_adapters.get_by_name("nonexistent")

        result = benchmark(lookup)
        assert result is None

    def test_repeated_lookups_same_adapter(self, benchmark, registry_with_adapters):
        """Measure repeated lookups (indicates caching opportunity)."""
        def lookup_many():
            results = []
            for _ in range(100):
                results.append(registry_with_adapters.get_by_name("provider_05"))
            return results

        results = benchmark(lookup_many)
        assert len(results) == 100
        assert all(r.name == "provider_05" for r in results)


class TestRegistryMutations:
    """Benchmark registration and state changes."""

    def test_single_adapter_registration(self, benchmark):
        """Measure time to register one adapter."""
        reg = ProviderRegistry()

        def register():
            reg.register(DummyAdapter("test_provider"))

        benchmark(register)
        # benchmark() runs the function many times, so just verify it worked
        assert len(reg.adapters) > 0

    def test_bulk_adapter_registration(self, benchmark):
        """Measure registration of many adapters."""
        reg = ProviderRegistry()

        def register_many():
            for i in range(50):
                reg.register(DummyAdapter(f"provider_{i}"))

        benchmark(register_many)
        # benchmark() runs the function many times, verify it's working
        assert len(reg.adapters) >= 50

    def test_install_all_patches(self, benchmark):
        """Measure time to install patches on all adapters."""
        reg = ProviderRegistry()
        for i in range(20):
            reg.register(DummyAdapter(f"provider_{i}"))

        def install():
            reg.install_all()

        benchmark(install)

    def test_remove_all_patches(self, benchmark):
        """Measure time to remove patches from all adapters."""
        reg = ProviderRegistry()
        for i in range(20):
            reg.register(DummyAdapter(f"provider_{i}"))
        reg.install_all()

        def remove():
            reg.remove_all()

        benchmark(remove)


class TestRegistryScaling:
    """Test registry performance as it scales."""

    def test_lookup_with_100_adapters(self, benchmark):
        """Measure lookup performance with 100 adapters."""
        reg = ProviderRegistry()
        for i in range(100):
            reg.register(DummyAdapter(f"provider_{i:03d}"))

        def lookup():
            return reg.get_by_name("provider_050")

        result = benchmark(lookup)
        assert result.name == "provider_050"

    def test_registration_scales_linearly(self):
        """Verify registration time scales roughly with batch size."""
        times = []
        for batch_size in [10, 50, 100]:
            reg = ProviderRegistry()
            start = time.perf_counter()
            for i in range(batch_size):
                reg.register(DummyAdapter(f"provider_{i}"))
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        # Verify rough scaling: larger batch should take longer
        # Allow high variance due to system noise and GC
        assert times[1] > times[0], f"Batch 50 should be > batch 10"
        assert times[2] > times[1], f"Batch 100 should be > batch 50"
