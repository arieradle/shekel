"""Shekel provider adapters — pluggable LLM provider integrations.

Built-in adapters (OpenAI, Anthropic) are auto-registered here.
Third-party adapters can register themselves via:

    from shekel.providers.base import ADAPTER_REGISTRY
    ADAPTER_REGISTRY.register(MyProviderAdapter())
"""

from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.base import ADAPTER_REGISTRY, ProviderAdapter, ProviderRegistry
from shekel.providers.openai import OpenAIAdapter

ADAPTER_REGISTRY.register(OpenAIAdapter())
ADAPTER_REGISTRY.register(AnthropicAdapter())

__all__ = [
    "ADAPTER_REGISTRY",
    "ProviderAdapter",
    "ProviderRegistry",
    "OpenAIAdapter",
    "AnthropicAdapter",
]
