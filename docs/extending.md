# Extending Shekel

Learn how to extend shekel with custom models, new providers, and custom features.

## Adding Custom Model Pricing

### Method 1: Runtime Override

Use `price_per_1k_tokens` parameter for one-off custom pricing:

```python
from shekel import budget

with budget(
    max_usd=1.00,
    price_per_1k_tokens={
        "input": 0.002,   # $0.002 per 1k input tokens
        "output": 0.006,  # $0.006 per 1k output tokens
    }
) as b:
    response = client.chat.completions.create(
        model="my-fine-tuned-gpt-4",
        messages=[{"role": "user", "content": "Hello"}],
    )

print(f"Cost: ${b.spent:.4f}")
```

**When to use:**
- Private or proprietary models
- Fine-tuned models with custom pricing
- Testing with mock pricing
- One-off custom models

### Method 2: Add to prices.json

For permanent additions, edit `shekel/prices.json`:

```json
{
  "gpt-4o": {
    "input_per_1k": 0.0025,
    "output_per_1k": 0.01
  },
  "my-custom-model": {
    "input_per_1k": 0.002,
    "output_per_1k": 0.006
  }
}
```

**Testing your addition:**

```python
from shekel._pricing import calculate_cost

cost = calculate_cost("my-custom-model", input_tokens=1000, output_tokens=500)
assert cost == 0.005  # (1000/1000 * 0.002) + (500/1000 * 0.006)
```

**Contributing back:**

1. Add model to `shekel/prices.json`
2. Add test to `tests/test_pricing.py`
3. Update `README.md` and `docs/models.md`
4. Submit PR

## Supporting New LLM Providers

To add support for a new provider (e.g., Cohere, Mistral), you need to:

1. Add patching logic
2. Extract tokens from responses
3. Handle streaming
4. Validate fallback compatibility

### Step 1: Add Patching Logic

Edit `shekel/_patch.py`:

```python
def _install_patches():
    # Existing OpenAI/Anthropic patches...
    
    # Add your provider
    try:
        import cohere_sdk.resources.chat as _cohere_chat
        
        _originals["cohere_sync"] = _cohere_chat.Chat.create
        _cohere_chat.Chat.create = _cohere_sync_wrapper
    except ImportError:
        pass

def _restore_patches():
    # Existing restore logic...
    
    # Restore your provider
    try:
        import cohere_sdk.resources.chat as _cohere_chat
        
        if "cohere_sync" in _originals:
            _cohere_chat.Chat.create = _originals.pop("cohere_sync")
    except ImportError:
        pass
```

### Step 2: Extract Tokens

Add token extraction function:

```python
def _extract_cohere_tokens(response):
    """Extract tokens from Cohere response."""
    try:
        input_tokens = response.meta.tokens.input_tokens or 0
        output_tokens = response.meta.tokens.output_tokens or 0
        model = response.model or "unknown"
        return input_tokens, output_tokens, model
    except AttributeError:
        return 0, 0, "unknown"
```

### Step 3: Create Wrapper

Add sync and async wrappers:

```python
def _cohere_sync_wrapper(self, *args, **kwargs):
    original = _originals.get("cohere_sync")
    if original is None:
        raise RuntimeError("shekel: cohere original not stored")
    
    # Apply fallback if needed
    active_budget = _context.get_active_budget()
    if active_budget is not None:
        _apply_fallback_if_needed(active_budget, kwargs, "cohere")
    
    # Handle streaming
    if kwargs.get("stream") is True:
        stream = original(self, *args, **kwargs)
        return _wrap_cohere_stream(stream)
    
    # Regular call
    response = original(self, *args, **kwargs)
    input_tokens, output_tokens, model = _extract_cohere_tokens(response)
    _record(input_tokens, output_tokens, model)
    return response
```

### Step 4: Handle Streaming

Add streaming wrapper:

```python
def _wrap_cohere_stream(stream):
    """Wrap Cohere streaming response."""
    input_tokens = 0
    output_tokens = 0
    model = "unknown"
    
    try:
        for event in stream:
            # Extract tokens from stream events
            if hasattr(event, 'meta') and hasattr(event.meta, 'tokens'):
                input_tokens = event.meta.tokens.input_tokens or 0
                output_tokens = event.meta.tokens.output_tokens or 0
            if hasattr(event, 'model'):
                model = event.model or "unknown"
            yield event
    finally:
        _record(input_tokens, output_tokens, model)
```

### Step 5: Provider Detection

Add provider detection for fallback validation:

```python
def _validate_same_provider(fallback_model: str, current_provider: str):
    """Validate fallback model is same provider."""
    is_cohere = fallback_model.startswith("command-")
    is_openai = any(fallback_model.startswith(p) for p in ("gpt-", "o1"))
    is_anthropic = fallback_model.startswith("claude-")
    
    if current_provider == "cohere" and (is_openai or is_anthropic):
        raise ValueError(
            f"shekel: fallback model '{fallback_model}' appears to be from a different provider. "
            f"Use a Cohere model as fallback."
        )
    # ... other validations
```

### Complete Example: Adding Cohere

See the [full example](https://github.com/arieradle/shekel/tree/main/examples/adding_provider.py) in the repo.

## Custom Budget Callbacks

### Advanced Warning System

```python
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class BudgetMonitor:
    def __init__(self):
        self.warnings = []
        self.alerts_sent = 0
    
    def on_warning(self, spent: float, limit: float):
        """Log warning with timestamp."""
        timestamp = datetime.now().isoformat()
        percentage = (spent / limit) * 100
        
        warning = {
            "timestamp": timestamp,
            "spent": spent,
            "limit": limit,
            "percentage": percentage,
        }
        self.warnings.append(warning)
        
        logger.warning(
            f"Budget warning: ${spent:.2f} / ${limit:.2f} ({percentage:.0f}%)",
            extra=warning
        )
    
    def on_fallback(self, spent: float, limit: float, fallback: str):
        """Alert when fallback is activated."""
        logger.error(
            f"Fallback activated: ${spent:.2f} exceeded ${limit:.2f}, "
            f"switching to {fallback}"
        )
        self.send_alert(spent, limit, fallback)
        self.alerts_sent += 1
    
    def send_alert(self, spent: float, limit: float, fallback: str):
        """Send alert to monitoring system."""
        # Send to Slack, PagerDuty, etc.
        pass

# Usage
monitor = BudgetMonitor()

with budget(
    max_usd=10.00,
    warn_at=0.8,
    fallback="gpt-4o-mini",
    on_exceed=monitor.on_warning,
    on_fallback=monitor.on_fallback
):
    run_my_agent()

print(f"Warnings: {len(monitor.warnings)}")
print(f"Alerts sent: {monitor.alerts_sent}")
```

### Metrics Collection

```python
from datadog import statsd

def collect_metrics(spent: float, limit: float):
    """Send metrics to DataDog."""
    statsd.gauge("llm.budget.spent", spent)
    statsd.gauge("llm.budget.limit", limit)
    statsd.gauge("llm.budget.utilization", spent / limit)

with budget(max_usd=10.00, warn_at=0.8, on_exceed=collect_metrics):
    run_my_agent()
```

## Extending the CLI

Add custom commands to `shekel/_cli.py`:

```python
import click
from shekel._pricing import calculate_cost

@cli.command()
@click.option("--model", required=True)
@click.option("--calls", type=int, required=True)
@click.option("--avg-input", type=int, required=True)
@click.option("--avg-output", type=int, required=True)
def batch_estimate(model: str, calls: int, avg_input: int, avg_output: int):
    """Estimate cost for a batch of calls."""
    per_call = calculate_cost(model, avg_input, avg_output)
    total = per_call * calls
    
    click.echo(f"Model: {model}")
    click.echo(f"Calls: {calls:,}")
    click.echo(f"Avg tokens: {avg_input:,} in / {avg_output:,} out")
    click.echo(f"Per call: ${per_call:.6f}")
    click.echo(f"Total batch: ${total:.2f}")

# Usage: shekel batch-estimate --model gpt-4o --calls 1000 --avg-input 500 --avg-output 200
```

## Integration Patterns

### Wrapping New Frameworks

Pattern for integrating with agent frameworks:

```python
from shekel import budget, BudgetExceededError

class BudgetedFrameworkWrapper:
    def __init__(self, framework_instance, max_usd: float):
        self.framework = framework_instance
        self.budget = budget(max_usd=max_usd, persistent=True)
    
    def run(self, *args, **kwargs):
        """Run framework with budget."""
        try:
            with self.budget:
                return self.framework.run(*args, **kwargs)
        except BudgetExceededError as e:
            return {
                "error": "Budget exceeded",
                "spent": e.spent,
                "limit": e.limit,
            }
    
    def get_stats(self):
        """Get budget statistics."""
        return {
            "spent": self.budget.spent,
            "limit": self.budget.limit,
            "remaining": self.budget.remaining,
        }

# Usage with any framework
framework = SomeAgentFramework()
budgeted = BudgetedFrameworkWrapper(framework, max_usd=5.00)

result = budgeted.run(task="Do something")
print(budgeted.get_stats())
```

## Testing Extensions

### Testing Custom Providers

```python
import pytest
from shekel import budget

def test_custom_provider():
    """Test custom provider integration."""
    with budget(max_usd=1.00) as b:
        # Make API call with custom provider
        response = custom_client.generate(prompt="Test")
        assert response is not None
    
    # Verify tracking
    assert b.spent > 0
    assert len(b.summary_data()["calls"]) == 1

def test_custom_provider_fallback():
    """Test fallback with custom provider."""
    with budget(max_usd=0.001, fallback="custom-cheap-model") as b:
        # Should trigger fallback
        for i in range(10):
            custom_client.generate(prompt=f"Test {i}")
    
    assert b.model_switched is True
    assert b.fallback_spent > 0
```

## Common Pitfalls

### 1. Token Extraction

❌ **Wrong:**
```python
# Assuming field names without checking
input_tokens = response.tokens.input  # Might not exist
```

✅ **Right:**
```python
try:
    input_tokens = response.usage.input_tokens or 0
except AttributeError:
    input_tokens = 0
```

### 2. Streaming

❌ **Wrong:**
```python
# Forgetting to use try/finally
for chunk in stream:
    tokens += chunk.tokens
_record(tokens)  # Might not be reached if exception
```

✅ **Right:**
```python
try:
    for chunk in stream:
        tokens += chunk.tokens
    yield chunk
finally:
    _record(tokens)  # Always called
```

### 3. Provider Detection

❌ **Wrong:**
```python
# Checking model name only
if "gpt" in fallback_model:  # Matches "gpt" in "my-custom-gpt-model"
```

✅ **Right:**
```python
if fallback_model.startswith("gpt-"):  # Exact prefix match
```

## Next Steps

- [How It Works](how-it-works.md) - Understanding internals
- [Contributing](contributing.md) - Contributing guide
- [API Reference](api-reference.md) - Complete API
