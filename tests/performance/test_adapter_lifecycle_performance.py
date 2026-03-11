"""Performance tests for adapter lifecycle: instantiation, configuration, teardown.

Measures:
- Adapter instantiation overhead
- Patch installation time
- Patch removal time
- Memory allocation during lifecycle
"""

from __future__ import annotations

from typing import Any

import pytest

from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.base import ProviderAdapter
from shekel.providers.openai import OpenAIAdapter


class DummyStatefulAdapter(ProviderAdapter):
    """Adapter with state for lifecycle testing."""

    def __init__(self, name: str, state_size: int = 100) -> None:
        self._name = name
        self._state = {"data": [i for i in range(state_size)]}
        self._patched = False

    @property
    def name(self) -> str:
        return self._name

    def install_patches(self) -> None:
        self._patched = True

    def remove_patches(self) -> None:
        self._patched = False

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        return 0, 0, self._name

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        return False

    def wrap_stream(self, stream: Any):
        yield stream
        return 0, 0, self._name


class TestAdapterInstantiation:
    """Benchmark adapter creation and initialization."""

    def test_instantiate_anthropic_adapter(self, benchmark):
        """Measure AnthropicAdapter creation."""
        def create():
            return AnthropicAdapter()

        result = benchmark(create)
        assert result is not None
        assert result.name == "anthropic"

    def test_instantiate_openai_adapter(self, benchmark):
        """Measure OpenAIAdapter creation."""
        def create():
            return OpenAIAdapter()

        result = benchmark(create)
        assert result is not None
        assert result.name == "openai"

    def test_instantiate_dummy_adapter_minimal(self, benchmark):
        """Measure minimal adapter creation (no state)."""
        def create():
            return DummyStatefulAdapter("test", state_size=0)

        result = benchmark(create)
        assert result.name == "test"

    def test_instantiate_dummy_adapter_with_state(self, benchmark):
        """Measure adapter creation with state initialization."""
        def create():
            return DummyStatefulAdapter("test", state_size=1000)

        result = benchmark(create)
        assert result.name == "test"
        assert len(result._state["data"]) == 1000

    def test_instantiate_many_adapters(self, benchmark):
        """Measure batch instantiation."""
        def create_many():
            return [DummyStatefulAdapter(f"adapter_{i}") for i in range(100)]

        results = benchmark(create_many)
        assert len(results) == 100


class TestPatchInstallation:
    """Benchmark patch installation on adapters."""

    def test_install_anthropic_patches(self, benchmark):
        """Measure Anthropic patch installation."""
        adapter = AnthropicAdapter()

        def install():
            adapter.install_patches()

        benchmark(install)

    def test_install_openai_patches(self, benchmark):
        """Measure OpenAI patch installation."""
        adapter = OpenAIAdapter()

        def install():
            adapter.install_patches()

        benchmark(install)

    def test_install_patches_idempotent(self, benchmark):
        """Measure idempotent patch installation (second call)."""
        adapter = AnthropicAdapter()
        adapter.install_patches()

        def install_again():
            adapter.install_patches()

        benchmark(install_again)

    def test_install_dummy_patches(self, benchmark):
        """Measure dummy adapter patch installation."""
        adapter = DummyStatefulAdapter("test")

        def install():
            adapter.install_patches()

        benchmark(install)
        assert adapter._patched is True


class TestPatchRemoval:
    """Benchmark patch removal and teardown."""

    def test_remove_anthropic_patches(self, benchmark):
        """Measure Anthropic patch removal."""
        adapter = AnthropicAdapter()
        adapter.install_patches()

        def remove():
            adapter.remove_patches()

        benchmark(remove)

    def test_remove_openai_patches(self, benchmark):
        """Measure OpenAI patch removal."""
        adapter = OpenAIAdapter()
        adapter.install_patches()

        def remove():
            adapter.remove_patches()

        benchmark(remove)

    def test_remove_patches_without_install(self, benchmark):
        """Measure patch removal when no patches were installed."""
        adapter = AnthropicAdapter()

        def remove():
            adapter.remove_patches()

        benchmark(remove)

    def test_remove_dummy_patches(self, benchmark):
        """Measure dummy adapter patch removal."""
        adapter = DummyStatefulAdapter("test")
        adapter.install_patches()

        def remove():
            adapter.remove_patches()

        benchmark(remove)
        assert adapter._patched is False


class TestAdapterLifecycle:
    """Benchmark complete lifecycle sequences."""

    def test_full_lifecycle_anthropic(self, benchmark):
        """Measure complete install → remove cycle for Anthropic."""
        def lifecycle():
            adapter = AnthropicAdapter()
            adapter.install_patches()
            adapter.remove_patches()

        benchmark(lifecycle)

    def test_full_lifecycle_openai(self, benchmark):
        """Measure complete install → remove cycle for OpenAI."""
        def lifecycle():
            adapter = OpenAIAdapter()
            adapter.install_patches()
            adapter.remove_patches()

        benchmark(lifecycle)

    def test_full_lifecycle_dummy(self, benchmark):
        """Measure complete lifecycle with dummy adapter."""
        def lifecycle():
            adapter = DummyStatefulAdapter("test", state_size=500)
            adapter.install_patches()
            adapter.remove_patches()

        benchmark(lifecycle)

    def test_multiple_install_remove_cycles(self, benchmark):
        """Measure repeated install/remove cycles."""
        adapter = AnthropicAdapter()

        def cycles():
            for _ in range(5):
                adapter.install_patches()
                adapter.remove_patches()

        benchmark(cycles)

    def test_install_multiple_adapters(self, benchmark):
        """Measure installing patches on multiple adapters."""
        adapters = [
            AnthropicAdapter(),
            OpenAIAdapter(),
            DummyStatefulAdapter("dummy1"),
            DummyStatefulAdapter("dummy2"),
        ]

        def install_all():
            for adapter in adapters:
                adapter.install_patches()

        benchmark(install_all)

    def test_remove_multiple_adapters(self, benchmark):
        """Measure removing patches from multiple adapters."""
        adapters = [
            AnthropicAdapter(),
            OpenAIAdapter(),
            DummyStatefulAdapter("dummy1"),
            DummyStatefulAdapter("dummy2"),
        ]
        for adapter in adapters:
            adapter.install_patches()

        def remove_all():
            for adapter in adapters:
                adapter.remove_patches()

        benchmark(remove_all)
