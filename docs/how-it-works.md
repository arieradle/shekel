# How It Works

Understanding shekel's internals: monkey-patching, context isolation, and zero-config design.

## Architecture Overview

Shekel uses three core techniques:

1. **Monkey-patching** - Intercepts API calls at runtime
2. **ContextVar isolation** - Thread-safe per-context tracking
3. **Ref-counted patching** - Efficient nested context handling

## Monkey-Patching

Shekel wraps the OpenAI and Anthropic SDK methods to intercept API calls:

```python
# When you enter a budget context
with budget(max_usd=1.00):
    # Shekel patches:
    # - openai.ChatCompletions.create → shekel wrapper
    # - anthropic.Messages.create → shekel wrapper
    
    response = client.chat.completions.create(...)
    # Your call goes through shekel's wrapper
    # Shekel extracts tokens, calculates cost, checks budget
    # Then returns the original response

# When you exit the context
# Shekel restores the original methods
```

### What Gets Patched

**OpenAI:**
- `openai.resources.chat.completions.Completions.create` (sync)
- `openai.resources.chat.completions.AsyncCompletions.create` (async)

**Anthropic:**
- `anthropic.resources.messages.Messages.create` (sync)
- `anthropic.resources.messages.AsyncMessages.create` (async)

**LiteLLM** (when `shekel[litellm]` is installed):
- `litellm.completion` (sync)
- `litellm.acompletion` (async)

### Patching Implementation

Shekel uses a pluggable `ProviderAdapter` pattern — each provider registers itself in `ADAPTER_REGISTRY`. `shekel/_patch.py` delegates all patching to the registry:

```python
# shekel/_patch.py
def _install_patches():
    from shekel.providers import ADAPTER_REGISTRY
    ADAPTER_REGISTRY.install_all()   # calls install_patches() on each adapter

def _restore_patches():
    from shekel.providers import ADAPTER_REGISTRY
    ADAPTER_REGISTRY.remove_all()    # restores originals for each adapter
```

Each adapter (e.g. `OpenAIAdapter`) handles its own SDK:

```python
# shekel/providers/openai.py
def install_patches(self) -> None:
    from shekel import _patch
    import openai.resources.chat.completions as oai
    _patch._originals["openai_sync"] = oai.Completions.create
    oai.Completions.create = _patch._openai_sync_wrapper
```

To add a new provider, implement `ProviderAdapter` and register it — see [Extending Shekel](extending.md).

## ContextVar Isolation

Each `budget()` context is isolated using Python's `ContextVar`:

```python
from contextvars import ContextVar

_active_budget: ContextVar[Budget | None] = ContextVar("active_budget", default=None)

def set_active_budget(budget: Budget | None):
    return _active_budget.set(budget)

def get_active_budget() -> Budget | None:
    return _active_budget.get()
```

This ensures:

- **Thread safety**: Each thread has its own context
- **Async safety**: Each async task has its own context
- **No global state**: Concurrent budgets never interfere

### Example: Concurrent Budgets

```python
import concurrent.futures
from shekel import budget

def task1():
    with budget(max_usd=1.00) as b:
        # b1's spend tracked here
        ...

def task2():
    with budget(max_usd=2.00) as b:
        # b2's spend tracked here (independent)
        ...

# Run concurrently - no interference
with concurrent.futures.ThreadPoolExecutor() as executor:
    executor.submit(task1)
    executor.submit(task2)
```

## Ref-Counted Patching

Nested contexts only patch once:

```python
_patch_refcount = 0

def apply_patches():
    global _patch_refcount
    _patch_refcount += 1
    if _patch_refcount == 1:  # Only patch on first entry
        _install_patches()

def remove_patches():
    global _patch_refcount
    _patch_refcount -= 1
    if _patch_refcount == 0:  # Only restore on last exit
        _restore_patches()
```

### Why This Matters

```python
# Outer budget
with budget(max_usd=5.00):
    # Patches installed (refcount: 1)
    
    # Inner budget
    with budget(max_usd=1.00):
        # No re-patching (refcount: 2)
        ...
    # No restoration yet (refcount: 1)
    
    ...
# Patches restored (refcount: 0)
```

## Token Extraction

Shekel extracts tokens from API responses:

**OpenAI / LiteLLM:**
```python
def _extract_openai_tokens(response):
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    model = response.model
    return input_tokens, output_tokens, model
```

LiteLLM uses the same OpenAI-compatible format regardless of the underlying provider, so the same extraction logic applies.

**Anthropic:**
```python
def _extract_anthropic_tokens(response):
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    model = response.model
    return input_tokens, output_tokens, model
```

## Cost Calculation

Three-tier pricing lookup:

```python
def calculate_cost(model, input_tokens, output_tokens, price_override):
    # Tier 3: Explicit override (highest priority)
    if price_override:
        return calculate_with_override(...)
    
    # Tier 1: Built-in prices.json
    if model in PRICES:
        return calculate_with_builtin(...)
    
    # Tier 1b: Prefix match (for versioned models)
    if prefix_match := find_prefix(model):
        return calculate_with_builtin(prefix_match)
    
    # Tier 2: tokencost (if installed)
    if tokencost_available():
        return calculate_with_tokencost(...)
    
    # Fallback: warn and return 0
    warn_unknown_model(model)
    return 0.0
```

## Streaming Support

### OpenAI Streaming

Shekel wraps the stream and collects usage from the final chunk:

```python
def _wrap_openai_stream(stream):
    seen_usage = []
    
    try:
        for chunk in stream:
            if chunk.usage:  # Final chunk has usage
                seen_usage.append(chunk.usage)
            yield chunk
    finally:
        if seen_usage:
            tokens = seen_usage[-1]
            _record(tokens.prompt_tokens, tokens.completion_tokens, model)
```

### Anthropic Streaming

Shekel tracks message events:

```python
def _wrap_anthropic_stream(stream):
    input_tokens = 0
    output_tokens = 0
    
    try:
        for event in stream:
            if event.type == "message_start":
                input_tokens = event.message.usage.input_tokens
            elif event.type == "message_delta":
                output_tokens = event.usage.output_tokens
            yield event
    finally:
        _record(input_tokens, output_tokens, model)
```

## Fallback Implementation

When budget is exceeded with a fallback:

```python
def _check_limit(self):
    if self.spent > self.max_usd:
        if self.fallback and not self._using_fallback:
            # Activate fallback
            self._using_fallback = True
            self._switched_at_usd = self.spent
            warn("Switching to fallback model")
            return  # Don't raise!
        
        # No fallback or already using fallback
        raise BudgetExceededError(...)
```

The next API call automatically uses the fallback:

```python
def _apply_fallback_if_needed(budget, kwargs, provider):
    if budget._using_fallback:
        # Rewrite model parameter
        kwargs["model"] = budget.fallback['model']
```

## Zero Config

Shekel requires no configuration because:

1. **No API keys needed** - Uses your existing OpenAI/Anthropic keys
2. **No external services** - Everything runs locally
3. **No initialization** - Just import and use
4. **No global state** - Each context is independent

```python
# No setup required!
from shekel import budget

with budget(max_usd=1.00):
    # Just works
    ...
```

## Performance

Shekel adds minimal overhead:

- **Patching**: Once per budget context (~1μs)
- **Per-call overhead**: Token extraction + cost calculation (~10μs)
- **No network calls**: All pricing is local

The overhead is negligible compared to API latency (100-1000ms).

## Limitations

### What Shekel Can't Do

1. **Stop mid-stream**: Streaming calls complete before budget check
2. **Cross-provider fallback**: Can't switch from OpenAI to Anthropic
3. **Predict costs**: Only tracks actual usage
4. **Batch API**: Doesn't support OpenAI batch endpoints
5. **Function calling costs**: Tracks tokens but not function execution costs

### Thread Safety

- **ContextVar**: ✅ Thread-safe within each thread
- **Persistent budget**: ❌ Not thread-safe across threads
- **Patching**: ✅ Thread-safe (uses lock)

## Source Code

The core package is organized into focused modules:

- `_budget.py` — `Budget` and `TemporalBudget` context managers
- `_patch.py` — Ref-counted monkey-patching and wrapper logic
- `_pricing.py` — Three-tier cost calculation (override → bundled → tokencost)
- `_context.py` — `ContextVar` management for active budget tracking
- `_decorator.py` — `@with_budget` decorator
- `_tool.py` — `@tool` decorator and tool call interception
- `_temporal.py` — Rolling-window state management
- `exceptions.py` — Full exception hierarchy (10 subclasses of `BudgetExceededError`)
- `providers/` — Per-provider adapters (OpenAI, Anthropic, LiteLLM, Gemini, HuggingFace, LangChain, LangGraph, CrewAI, MCP, OpenAI Agents SDK)
- `backends/redis.py` — `RedisBackend` and `AsyncRedisBackend` for distributed enforcement
- `integrations/` — Langfuse and OpenTelemetry adapters

All code is available at [github.com/arieradle/shekel](https://github.com/arieradle/shekel).

## Next Steps

- [Extending Shekel](extending.md) - Add new providers or models
- [Contributing](contributing.md) - Contribute to the project
- [API Reference](api-reference.md) - Complete API docs
