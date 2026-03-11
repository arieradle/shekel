"""Provider adapter interface for Shekel LLM cost tracking.

Defines the ProviderAdapter ABC that all provider integrations must implement,
and the ProviderRegistry singleton that manages them.

To add a new provider, implement ProviderAdapter and register it:

    from shekel.providers.base import ADAPTER_REGISTRY
    from my_provider import MyProviderAdapter

    ADAPTER_REGISTRY.register(MyProviderAdapter())
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Tuple

if TYPE_CHECKING:
    pass


class ProviderAdapter(ABC):
    """Abstract base class for all LLM provider integrations.

    Each provider (OpenAI, Anthropic, Cohere, etc.) implements this interface
    to teach Shekel how to:

    - Patch the provider's SDK methods to intercept API calls
    - Extract token counts from responses
    - Detect and handle streaming responses
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. 'openai', 'anthropic').

        Used by ProviderRegistry.get_by_name() and fallback validation.
        """
        ...

    @abstractmethod
    def install_patches(self) -> None:
        """Monkey-patch the provider's SDK methods.

        Store originals before patching so remove_patches() can restore them.
        Must be idempotent — safe to call multiple times.
        """
        ...

    @abstractmethod
    def remove_patches(self) -> None:
        """Restore original SDK methods.

        Reverses what install_patches() did.
        Must be safe to call even if install_patches() was never called.
        """
        ...

    @abstractmethod
    def extract_tokens(self, response: Any) -> Tuple[int, int, str]:
        """Extract token counts from a non-streaming API response.

        Args:
            response: The raw response object from the provider SDK.

        Returns:
            Tuple of (input_tokens, output_tokens, model_name).
            On any error, return (0, 0, 'unknown') — never raise.
        """
        ...

    @abstractmethod
    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        """Determine whether a response is a streaming response.

        Some providers (OpenAI) detect streaming via kwargs before the call.
        Others (Anthropic) detect it by inspecting the response object.

        Args:
            kwargs: The kwargs passed to the original SDK method.
            response: The response object (may be None for pre-call detection).

        Returns:
            True if this is a streaming response.
        """
        ...

    @abstractmethod
    def wrap_stream(self, stream: Any) -> Generator[Any, None, Tuple[int, int, str]]:
        """Wrap a streaming response to collect token counts.

        Yields chunks/events to the caller unchanged, then returns token
        counts in the finally block via GeneratorExit semantics.

        Usage in a wrapper:
            gen = adapter.wrap_stream(stream)
            try:
                for chunk in gen:
                    yield chunk
            except StopIteration as e:
                input_tok, output_tok, model = e.value

        Args:
            stream: The raw streaming object from the provider SDK.

        Yields:
            Raw chunks/events, unchanged.

        Returns (via StopIteration.value):
            Tuple of (input_tokens, output_tokens, model_name).
        """
        ...


class ProviderRegistry:
    """Manages the set of registered provider adapters.

    Shekel's _patch.py delegates all patching to the registry,
    so new providers can be added without touching core code.
    """

    def __init__(self) -> None:
        self.adapters: list[ProviderAdapter] = []

    def register(self, adapter: ProviderAdapter) -> None:
        """Register a provider adapter.

        Args:
            adapter: Fully implemented ProviderAdapter instance.
        """
        self.adapters.append(adapter)

    def get_by_name(self, name: str) -> ProviderAdapter | None:
        """Look up an adapter by its name.

        Args:
            name: Provider name (e.g. 'openai', 'anthropic').

        Returns:
            The matching adapter, or None if not found.
        """
        for adapter in self.adapters:
            if adapter.name == name:
                return adapter
        return None

    def install_all(self) -> None:
        """Install patches for all registered adapters."""
        for adapter in self.adapters:
            adapter.install_patches()

    def remove_all(self) -> None:
        """Remove patches for all registered adapters."""
        for adapter in self.adapters:
            adapter.remove_patches()


ADAPTER_REGISTRY = ProviderRegistry()
