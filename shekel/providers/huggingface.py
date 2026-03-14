"""HuggingFace provider adapter for Shekel LLM cost tracking.

Patches huggingface_hub.inference._client.InferenceClient.chat_completion to
intercept API calls and record token costs inside active budgets.

HuggingFace uses an OpenAI-compatible response format:
  - response.usage.prompt_tokens
  - response.usage.completion_tokens
  - response.model

Note: Many HuggingFace models do not return usage data in streaming responses.
Shekel handles this gracefully by recording zero tokens when usage is absent.

Since HuggingFace Inference API pricing varies per model and is not standardised,
you should always pass price_per_1k_tokens to budget() when tracking costs:

    with budget(max_usd=0.10, price_per_1k_tokens={"input": 0.001, "output": 0.001}):
        client.chat_completion(...)
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from shekel.providers.base import ProviderAdapter


class HuggingFaceAdapter(ProviderAdapter):
    """Adapter for HuggingFace Inference API (huggingface-hub SDK)."""

    def __init__(self) -> None:
        self._originals: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "huggingface"

    def install_patches(self) -> None:
        """Monkey-patch InferenceClient.chat_completion and AsyncInferenceClient.chat_completion."""
        from shekel import _patch

        try:
            from huggingface_hub import AsyncInferenceClient
            from huggingface_hub.inference import _client

            if "huggingface_sync" not in _patch._originals:
                _patch._originals["huggingface_sync"] = _client.InferenceClient.chat_completion
                _patch._originals["huggingface_async"] = AsyncInferenceClient.chat_completion
                _client.InferenceClient.chat_completion = _patch._huggingface_sync_wrapper  # type: ignore[method-assign]
                AsyncInferenceClient.chat_completion = _patch._huggingface_async_wrapper  # type: ignore[method-assign]
        except ImportError:
            pass

    def remove_patches(self) -> None:
        """Restore original InferenceClient and AsyncInferenceClient chat_completion."""
        from shekel import _patch

        try:
            from huggingface_hub import AsyncInferenceClient
            from huggingface_hub.inference import _client

            if "huggingface_sync" in _patch._originals:
                _client.InferenceClient.chat_completion = _patch._originals.pop("huggingface_sync")  # type: ignore[method-assign]
            if "huggingface_async" in _patch._originals:
                AsyncInferenceClient.chat_completion = _patch._originals.pop("huggingface_async")  # type: ignore[method-assign]
        except ImportError:
            pass

    def extract_tokens(self, response: Any) -> tuple[int, int, str]:
        """Extract tokens from HuggingFace non-streaming response.

        Uses OpenAI-compatible format:
          response.usage.prompt_tokens / response.usage.completion_tokens
        """
        try:
            usage = response.usage
            if usage is None:
                model = getattr(response, "model", None) or "unknown"
                return 0, 0, model
            input_tokens = usage.prompt_tokens or 0
            output_tokens = usage.completion_tokens or 0
            model = getattr(response, "model", None) or "unknown"
            return input_tokens, output_tokens, model
        except AttributeError:
            return 0, 0, "unknown"

    def detect_streaming(self, kwargs: dict[str, Any], response: Any) -> bool:
        """Detect streaming via the 'stream' kwarg."""
        return kwargs.get("stream") is True

    def wrap_stream(self, stream: Any) -> Generator[Any, None, tuple[int, int, str]]:
        """Wrap HuggingFace streaming response to collect token counts.

        Many HuggingFace models do not return usage in streaming chunks.
        Returns (0, 0, 'unknown') gracefully when usage is absent.
        """
        seen: list[tuple[int, int, str]] = []
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                try:
                    it = usage.prompt_tokens or 0
                    ot = usage.completion_tokens or 0
                    m = getattr(chunk, "model", None) or "unknown"
                    seen.append((it, ot, m))
                except AttributeError:
                    pass
            yield chunk
        return seen[-1] if seen else (0, 0, "unknown")

    def validate_fallback(self, fallback_model: str) -> None:
        """Validate that fallback model is a HuggingFace model (org/model format)."""
        is_openai = any(
            fallback_model.startswith(p) for p in ("gpt-", "o1", "o2", "o3", "o4", "text-")
        )
        is_anthropic = fallback_model.startswith("claude-")
        is_gemini = fallback_model.startswith("gemini-")

        if is_openai or is_anthropic or is_gemini:
            raise ValueError(
                f"shekel: fallback model '{fallback_model}' does not appear to be a "
                f"HuggingFace model but the current call is to HuggingFace. "
                f"Cross-provider fallback is not supported. "
                f"Use a HuggingFace model as fallback "
                f"(e.g. fallback='HuggingFaceH4/zephyr-7b-beta')."
            )
