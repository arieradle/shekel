"""Shekel provider adapters — pluggable LLM provider integrations.

Built-in adapters (OpenAI, Anthropic) are auto-registered here.
Third-party adapters can register themselves via:

    from shekel.providers.base import ADAPTER_REGISTRY
    ADAPTER_REGISTRY.register(MyProviderAdapter())
"""

from __future__ import annotations

from shekel.providers.anthropic import AnthropicAdapter
from shekel.providers.base import ADAPTER_REGISTRY, ProviderAdapter, ProviderRegistry
from shekel.providers.openai import OpenAIAdapter

ADAPTER_REGISTRY.register(OpenAIAdapter())
ADAPTER_REGISTRY.register(AnthropicAdapter())

try:
    from shekel.providers.litellm import LiteLLMAdapter

    ADAPTER_REGISTRY.register(LiteLLMAdapter())
except ImportError:
    pass

__all__ = [
    "ADAPTER_REGISTRY",
    "ProviderAdapter",
    "ProviderRegistry",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "LiteLLMAdapter",
]
