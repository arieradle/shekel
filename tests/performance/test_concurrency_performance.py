"""Performance tests for concurrency: multiple adapters, thread safety, parallel ops.

Measures:
- Multiple adapters active simultaneously
- Parallel message handling
- Thread contention on registry
- Concurrent patch installation
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import Mock

from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.base import ProviderAdapter, ProviderRegistry
from shekel.providers.openai import OpenAIAdapter


class DummyAdapter(ProviderAdapter):
    """Simple adapter for concurrency testing."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def install_patches(self) -> None:
        with self._lock:
            time.sleep(0.001)  # Simulate work

    def remove_patches(self) -> None:
        with self._lock:
            time.sleep(0.001)

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        return 0, 0, self._name

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        return False

    def wrap_stream(self, stream: Any):
        yield stream
        return 0, 0, self._name


class TestMultipleAdaptersActive:
    """Benchmark scenarios with multiple active adapters."""

    def test_simultaneous_adapter_operations(self, benchmark):
        """Measure simultaneous operations on multiple adapters."""
        adapters = [
            AnthropicAdapter(),
            OpenAIAdapter(),
            DummyAdapter("dummy1"),
            DummyAdapter("dummy2"),
        ]

        def operate():
            for adapter in adapters:
                adapter.install_patches()
            # Do work with all adapters
            for adapter in adapters:
                resp = Mock()
                resp.usage = Mock()
                resp.usage.prompt_tokens = 10
                resp.usage.completion_tokens = 20
                resp.model = "test"
                adapter.extract_tokens(resp)
            for adapter in adapters:
                adapter.remove_patches()

        benchmark(operate)

    def test_registry_with_many_adapters(self, benchmark):
        """Measure registry performance with many adapters."""
        registry = ProviderRegistry()
        for i in range(50):
            registry.register(DummyAdapter(f"adapter_{i:03d}"))

        def operate():
            for i in range(50):
                registry.get_by_name(f"adapter_{i:03d}")

        benchmark(operate)

    def test_adapter_chain_operations(self, benchmark):
        """Measure chaining operations across multiple adapters."""
        adapters = [AnthropicAdapter(), OpenAIAdapter()]

        def chain():
            results = []
            for i in range(100):
                for adapter in adapters:
                    resp = Mock()
                    resp.usage = Mock()
                    resp.usage.prompt_tokens = i
                    resp.usage.completion_tokens = i * 2
                    resp.model = adapter.name
                    result = adapter.extract_tokens(resp)
                    results.append(result)
            return results

        results = benchmark(chain)
        assert len(results) == 200


class TestParallelMessageHandling:
    """Benchmark parallel message operations."""

    def test_extract_tokens_parallel(self, benchmark):
        """Measure parallel token extraction."""
        adapter = OpenAIAdapter()
        responses = []
        for i in range(100):
            resp = Mock()
            resp.usage = Mock()
            resp.usage.prompt_tokens = 10 + i
            resp.usage.completion_tokens = 20 + i
            resp.model = "gpt-4"
            responses.append(resp)

        def extract_parallel():
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(adapter.extract_tokens, responses))
            return results

        results = benchmark(extract_parallel)
        assert len(results) == 100

    def test_detect_streaming_parallel(self, benchmark):
        """Measure parallel streaming detection."""
        adapter = OpenAIAdapter()
        kwargs_list = [{"stream": i % 2 == 0} for i in range(100)]
        responses = [Mock() for _ in range(100)]

        def detect_parallel():
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(adapter.detect_streaming, kwargs_list, responses))
            return results

        results = benchmark(detect_parallel)
        assert len(results) == 100

    def test_wrap_stream_parallel(self, benchmark):
        """Measure parallel stream wrapping."""
        adapter = OpenAIAdapter()
        streams = []
        for i in range(20):
            chunks = [Mock(usage=None) for _ in range(5)]
            final = Mock()
            final.usage = Mock()
            final.usage.prompt_tokens = 10
            final.usage.completion_tokens = 20
            final.model = "gpt-4"
            chunks.append(final)
            streams.append(iter(chunks))

        def wrap_parallel():
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = []
                for stream in streams:
                    future = executor.submit(lambda s: list(adapter.wrap_stream(s)), stream)
                    results.append(future)
                return [r.result() for r in results]

        results = benchmark(wrap_parallel)
        assert len(results) == 20


class TestRegistryContention:
    """Benchmark registry performance under contention."""

    def test_registry_concurrent_reads(self, benchmark):
        """Measure registry lookup contention."""
        registry = ProviderRegistry()
        for i in range(20):
            registry.register(DummyAdapter(f"adapter_{i:02d}"))

        def concurrent_reads():
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = []
                for _ in range(100):
                    future = executor.submit(registry.get_by_name, "adapter_10")
                    futures.append(future)
                results = [f.result() for f in futures]
            return results

        results = benchmark(concurrent_reads)
        assert len(results) == 100
        assert all(r.name == "adapter_10" for r in results)

    def test_registry_concurrent_registration(self, benchmark):
        """Measure registry registration under contention."""
        registry = ProviderRegistry()

        def concurrent_register():
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = []
                for i in range(100):
                    future = executor.submit(registry.register, DummyAdapter(f"concurrent_{i}"))
                    futures.append(future)
                for f in futures:
                    f.result()
            return len(registry.adapters)

        count = benchmark(concurrent_register)
        # benchmark() runs many times, just verify we registered adapters
        assert count >= 100

    def test_registry_mixed_operations(self, benchmark):
        """Measure registry with concurrent reads and writes."""
        registry = ProviderRegistry()
        for i in range(10):
            registry.register(DummyAdapter(f"initial_{i}"))

        def mixed_ops():
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = []
                # Mix reads and writes
                for i in range(50):
                    if i % 2 == 0:
                        future = executor.submit(registry.get_by_name, f"initial_{i % 10}")
                    else:
                        future = executor.submit(registry.register, DummyAdapter(f"dynamic_{i}"))
                    futures.append(future)
                for f in futures:
                    f.result()
            return len(registry.adapters)

        count = benchmark(mixed_ops)
        assert count > 10


class TestConcurrentPatchInstallation:
    """Benchmark concurrent patch installation."""

    def test_install_patches_concurrent(self, benchmark):
        """Measure concurrent patch installation."""
        adapters = [
            AnthropicAdapter(),
            OpenAIAdapter(),
            DummyAdapter("dummy1"),
            DummyAdapter("dummy2"),
            DummyAdapter("dummy3"),
        ]

        def install_concurrent():
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(a.install_patches) for a in adapters]
                for f in futures:
                    f.result()

        benchmark(install_concurrent)

    def test_remove_patches_concurrent(self, benchmark):
        """Measure concurrent patch removal."""
        adapters = [
            AnthropicAdapter(),
            OpenAIAdapter(),
            DummyAdapter("dummy1"),
            DummyAdapter("dummy2"),
            DummyAdapter("dummy3"),
        ]
        # Install first
        for adapter in adapters:
            adapter.install_patches()

        def remove_concurrent():
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(a.remove_patches) for a in adapters]
                for f in futures:
                    f.result()

        benchmark(remove_concurrent)

    def test_install_remove_lifecycle_concurrent(self, benchmark):
        """Measure full lifecycle with concurrent operations."""

        def lifecycle_task(adapter_id):
            adapter = DummyAdapter(f"lifecycle_{adapter_id}")
            adapter.install_patches()
            time.sleep(0.001)
            adapter.remove_patches()

        def concurrent_lifecycle():
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(lifecycle_task, i) for i in range(20)]
                for f in futures:
                    f.result()

        benchmark(concurrent_lifecycle)


class TestThreadSafety:
    """Benchmark thread-safe operations."""

    def test_adapter_name_access_concurrent(self, benchmark):
        """Measure concurrent access to adapter name property."""
        adapter = DummyAdapter("test")

        def access_name():
            return adapter.name

        def access_concurrent():
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(access_name) for _ in range(1000)]
                names = [f.result() for f in futures]
            return names

        results = benchmark(access_concurrent)
        assert all(n == "test" for n in results)
        assert len(results) == 1000

    def test_registry_adapters_list_concurrent_read(self, benchmark):
        """Measure concurrent read of registry adapters list."""
        registry = ProviderRegistry()
        for i in range(10):
            registry.register(DummyAdapter(f"adapter_{i}"))

        def read_concurrent():
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(lambda: len(registry.adapters)) for _ in range(1000)]
                results = [f.result() for f in futures]
            return results

        results = benchmark(read_concurrent)
        assert all(r == 10 for r in results)


class TestConcurrencyScaling:
    """Benchmark concurrency behavior at scale."""

    def test_extract_tokens_many_threads(self, benchmark):
        """Measure token extraction with many concurrent threads."""
        adapter = OpenAIAdapter()
        response = Mock()
        response.usage = Mock()
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 200
        response.model = "gpt-4"

        def extract_many_threads():
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = [executor.submit(adapter.extract_tokens, response) for _ in range(1000)]
                results = [f.result() for f in futures]
            return results

        results = benchmark(extract_many_threads)
        assert len(results) == 1000

    def test_registry_lookup_many_threads(self, benchmark):
        """Measure registry lookups with many concurrent threads."""
        registry = ProviderRegistry()
        for i in range(20):
            registry.register(DummyAdapter(f"adapter_{i:02d}"))

        def lookup_many_threads():
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = []
                for i in range(1000):
                    idx = i % 20
                    future = executor.submit(registry.get_by_name, f"adapter_{idx:02d}")
                    futures.append(future)
                results = [f.result() for f in futures]
            return results

        results = benchmark(lookup_many_threads)
        assert len(results) == 1000
