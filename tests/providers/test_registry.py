from __future__ import annotations

"""TDD tests for ProviderAdapter interface and ProviderRegistry."""

from unittest.mock import MagicMock

import pytest


class TestProviderAdapterInterface:
    """ProviderAdapter must be an ABC with 6 required methods."""

    def test_is_abstract(self):
        """ProviderAdapter cannot be instantiated directly."""
        from shekel.providers.base import ProviderAdapter

        with pytest.raises(TypeError):
            ProviderAdapter()  # type: ignore

    def test_requires_name(self):
        """Concrete adapter must implement name property."""
        from shekel.providers.base import ProviderAdapter

        class NoName(ProviderAdapter):
            def install_patches(self):
                pass

            def remove_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "x"

            def detect_streaming(self, k, r):
                return False

            def wrap_stream(self, s):
                return iter([])

        with pytest.raises(TypeError):
            NoName()

    def test_requires_install_patches(self):
        """Concrete adapter must implement install_patches."""
        from shekel.providers.base import ProviderAdapter

        class NoInstall(ProviderAdapter):
            @property
            def name(self):
                return "test"

            def remove_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "x"

            def detect_streaming(self, k, r):
                return False

            def wrap_stream(self, s):
                return iter([])

        with pytest.raises(TypeError):
            NoInstall()

    def test_requires_remove_patches(self):
        """Concrete adapter must implement remove_patches."""
        from shekel.providers.base import ProviderAdapter

        class NoRemove(ProviderAdapter):
            @property
            def name(self):
                return "test"

            def install_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "x"

            def detect_streaming(self, k, r):
                return False

            def wrap_stream(self, s):
                return iter([])

        with pytest.raises(TypeError):
            NoRemove()

    def test_requires_extract_tokens(self):
        """Concrete adapter must implement extract_tokens."""
        from shekel.providers.base import ProviderAdapter

        class NoExtract(ProviderAdapter):
            @property
            def name(self):
                return "test"

            def install_patches(self):
                pass

            def remove_patches(self):
                pass

            def detect_streaming(self, k, r):
                return False

            def wrap_stream(self, s):
                return iter([])

        with pytest.raises(TypeError):
            NoExtract()

    def test_requires_detect_streaming(self):
        """Concrete adapter must implement detect_streaming."""
        from shekel.providers.base import ProviderAdapter

        class NoDetect(ProviderAdapter):
            @property
            def name(self):
                return "test"

            def install_patches(self):
                pass

            def remove_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "x"

            def wrap_stream(self, s):
                return iter([])

        with pytest.raises(TypeError):
            NoDetect()

    def test_requires_wrap_stream(self):
        """Concrete adapter must implement wrap_stream."""
        from shekel.providers.base import ProviderAdapter

        class NoWrap(ProviderAdapter):
            @property
            def name(self):
                return "test"

            def install_patches(self):
                pass

            def remove_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "x"

            def detect_streaming(self, k, r):
                return False

        with pytest.raises(TypeError):
            NoWrap()

    def test_concrete_adapter_can_be_instantiated(self):
        """A fully implemented adapter can be instantiated."""
        from shekel.providers.base import ProviderAdapter

        class FullAdapter(ProviderAdapter):
            @property
            def name(self):
                return "test"

            def install_patches(self):
                pass

            def remove_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "unknown"

            def detect_streaming(self, k, r):
                return False

            def wrap_stream(self, s):
                return iter([])

        adapter = FullAdapter()
        assert adapter.name == "test"


class TestProviderRegistry:
    """ProviderRegistry manages adapter registration and lifecycle."""

    def setup_method(self):
        """Create fresh registry for each test."""
        from shekel.providers.base import ProviderRegistry

        self.registry = ProviderRegistry()
        self._make_adapter = self._build_adapter

    def _build_adapter(self, name: str):
        from shekel.providers.base import ProviderAdapter

        class TestAdapter(ProviderAdapter):
            @property
            def name(self):
                return name

            def install_patches(self):
                pass

            def remove_patches(self):
                pass

            def extract_tokens(self, r):
                return 0, 0, "unknown"

            def detect_streaming(self, k, r):
                return False

            def wrap_stream(self, s):
                return iter([])

        return TestAdapter()

    def test_register_adds_adapter(self):
        adapter = self._build_adapter("test")
        self.registry.register(adapter)
        assert len(self.registry.adapters) == 1

    def test_register_multiple_adapters(self):
        self.registry.register(self._build_adapter("a"))
        self.registry.register(self._build_adapter("b"))
        assert len(self.registry.adapters) == 2

    def test_get_by_name_returns_adapter(self):
        adapter = self._build_adapter("openai")
        self.registry.register(adapter)
        found = self.registry.get_by_name("openai")
        assert found is adapter

    def test_get_by_name_returns_none_if_missing(self):
        found = self.registry.get_by_name("missing")
        assert found is None

    def test_install_all_calls_each_adapter(self):
        a = MagicMock()
        b = MagicMock()
        self.registry.adapters = [a, b]
        self.registry.install_all()
        a.install_patches.assert_called_once()
        b.install_patches.assert_called_once()

    def test_remove_all_calls_each_adapter(self):
        a = MagicMock()
        b = MagicMock()
        self.registry.adapters = [a, b]
        self.registry.remove_all()
        a.remove_patches.assert_called_once()
        b.remove_patches.assert_called_once()

    def test_install_all_empty_registry_is_safe(self):
        self.registry.install_all()  # Should not raise

    def test_remove_all_empty_registry_is_safe(self):
        self.registry.remove_all()  # Should not raise


class TestAdapterRegistrySingleton:
    """ADAPTER_REGISTRY singleton is importable and pre-populated."""

    def test_adapter_registry_is_importable(self):
        from shekel.providers import ADAPTER_REGISTRY

        assert ADAPTER_REGISTRY is not None

    def test_openai_adapter_registered(self):
        from shekel.providers import ADAPTER_REGISTRY

        openai_adapter = ADAPTER_REGISTRY.get_by_name("openai")
        assert openai_adapter is not None

    def test_anthropic_adapter_registered(self):
        from shekel.providers import ADAPTER_REGISTRY

        anthropic_adapter = ADAPTER_REGISTRY.get_by_name("anthropic")
        assert anthropic_adapter is not None
