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

try:
    from shekel.providers.gemini import GeminiAdapter

    ADAPTER_REGISTRY.register(GeminiAdapter())
except ImportError:
    pass

try:
    from shekel.providers.huggingface import HuggingFaceAdapter

    ADAPTER_REGISTRY.register(HuggingFaceAdapter())
except ImportError:
    pass

try:
    from shekel.providers.mcp import MCPAdapter

    ADAPTER_REGISTRY.register(MCPAdapter())
except ImportError:  # pragma: no cover
    pass

try:
    from shekel.providers.langchain import LangChainAdapter

    ADAPTER_REGISTRY.register(LangChainAdapter())
except ImportError:  # pragma: no cover
    pass

try:
    from shekel.providers.crewai import CrewAIAdapter

    ADAPTER_REGISTRY.register(CrewAIAdapter())
except ImportError:  # pragma: no cover
    pass

try:
    from shekel.providers.openai_agents import OpenAIAgentsAdapter

    ADAPTER_REGISTRY.register(OpenAIAgentsAdapter())
except ImportError:  # pragma: no cover
    pass

__all__ = [
    "ADAPTER_REGISTRY",
    "ProviderAdapter",
    "ProviderRegistry",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "LiteLLMAdapter",
    "GeminiAdapter",
    "HuggingFaceAdapter",
    "MCPAdapter",
    "LangChainAdapter",
    "CrewAIAdapter",
    "OpenAIAgentsAdapter",
]
