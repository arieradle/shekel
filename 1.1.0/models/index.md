# Supported Models

Shekel includes built-in pricing for popular LLM models and supports 400+ additional models via tokencost.

## Built-in Models

These models have zero-dependency pricing built into shekel:

### OpenAI Models

| Model             | Input / 1K | Output / 1K | Use Case                             |
| ----------------- | ---------- | ----------- | ------------------------------------ |
| **gpt-4o**        | $0.00250   | $0.01000    | Best for complex tasks, high quality |
| **gpt-4o-mini**   | $0.000150  | $0.000600   | Fast, cheap, good for most tasks     |
| **o1**            | $0.01500   | $0.06000    | Advanced reasoning, complex problems |
| **o1-mini**       | $0.00300   | $0.01200    | Reasoning on a budget                |
| **gpt-3.5-turbo** | $0.000500  | $0.001500   | Legacy, fast responses               |

### Anthropic Models

| Model                          | Input / 1K | Output / 1K | Use Case                 |
| ------------------------------ | ---------- | ----------- | ------------------------ |
| **claude-3-5-sonnet-20241022** | $0.00300   | $0.01500    | Latest, best quality     |
| **claude-3-haiku-20240307**    | $0.000250  | $0.001250   | Fast, cheap, high volume |
| **claude-3-opus-20240229**     | $0.01500   | $0.07500    | Most capable, expensive  |

### Google Models

| Model                | Input / 1K | Output / 1K | Use Case              |
| -------------------- | ---------- | ----------- | --------------------- |
| **gemini-2.5-pro**   | $0.00125   | $0.01000    | Most capable Gemini   |
| **gemini-2.5-flash** | $0.0000750 | $0.000300   | Fast, cost-efficient  |
| **gemini-2.0-flash** | $0.0000750 | $0.000300   | Latest flash model    |
| **gemini-1.5-pro**   | $0.00125   | $0.00500    | Balanced quality/cost |
| **gemini-1.5-flash** | $0.0000750 | $0.000300   | Fastest, cheapest     |

Native Gemini SDK support

To track costs when calling Gemini via the `google-genai` SDK directly (not through LiteLLM), install `shekel[gemini]`. See [Google Gemini Integration](https://arieradle.github.io/shekel/1.1.0/integrations/gemini/index.md).

## Version Resolution

Shekel automatically resolves versioned model names:

```python
# All of these resolve to "gpt-4o" pricing
models = [
    "gpt-4o",
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-05-13",
    "gpt-4o-2024-11-20",
]

# All of these resolve to "gpt-4o-mini" pricing
models = [
    "gpt-4o-mini",
    "gpt-4o-mini-2024-07-18",
]
```

The longest matching prefix wins.

## Extended Model Support (400+)

Install `shekel[all-models]` for 400+ models via [tokencost](https://github.com/AgentOps-AI/tokencost):

```bash
pip install shekel[all-models]
```

This adds support for:

- **Cohere**: command-r, command-r-plus, command-light, etc.
- **AI21**: j2-ultra, j2-mid, jamba-instruct, etc.
- **Aleph Alpha**: luminous-base, luminous-extended, etc.
- **Mistral**: mistral-tiny, mistral-small, mistral-medium, etc.
- **Meta**: llama-2-70b, llama-2-13b, etc.
- **And many more**

See [tokencost model list](https://github.com/AgentOps-AI/tokencost#supported-models) for complete list.

## Custom Model Pricing

For unlisted or private models, provide custom pricing:

```python
from shekel import budget

# Custom model
with budget(
    max_usd=1.00,
    price_per_1k_tokens={
        "input": 0.002,   # $0.002 per 1k input tokens
        "output": 0.006,  # $0.006 per 1k output tokens
    }
) as b:
    response = client.chat.completions.create(
        model="my-custom-model",
        messages=[{"role": "user", "content": "Hello"}],
    )

print(f"Cost: ${b.spent:.4f}")
```

## Cost Comparison

### Cheapest to Most Expensive (per 1M tokens input)

1. **gemini-1.5-flash**: $0.075
1. **gpt-4o-mini**: $0.150
1. **claude-3-haiku**: $0.250
1. **gpt-3.5-turbo**: $0.500
1. **gemini-1.5-pro**: $1.250
1. **gpt-4o**: $2.500
1. **claude-3-5-sonnet**: $3.000
1. **o1-mini**: $3.000
1. **o1**: $15.000
1. **claude-3-opus**: $15.000

### Cheapest to Most Expensive (per 1M tokens output)

1. **gemini-1.5-flash**: $0.300
1. **gpt-4o-mini**: $0.600
1. **claude-3-haiku**: $1.250
1. **gpt-3.5-turbo**: $1.500
1. **gemini-1.5-pro**: $5.000
1. **gpt-4o**: $10.000
1. **o1-mini**: $12.000
1. **claude-3-5-sonnet**: $15.000
1. **o1**: $60.000
1. **claude-3-opus**: $75.000

## Fallback Model Recommendations

### Best Fallback Pairs

| Primary Model     | →   | Fallback Model | Savings     |
| ----------------- | --- | -------------- | ----------- |
| gpt-4o            | →   | gpt-4o-mini    | 94% cheaper |
| o1                | →   | gpt-4o-mini    | 97% cheaper |
| claude-3-opus     | →   | claude-3-haiku | 98% cheaper |
| claude-3-5-sonnet | →   | claude-3-haiku | 92% cheaper |

## View Pricing in CLI

```bash
# All models
shekel models

# By provider
shekel models --provider openai
shekel models --provider anthropic
shekel models --provider google

# Estimate costs
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
```

## Pricing Updates

Shekel's built-in pricing is updated with each release. To get the latest pricing:

```bash
pip install --upgrade shekel
```

Or use `shekel[all-models]` for real-time pricing via tokencost.

## Next Steps

- [CLI Tools](https://arieradle.github.io/shekel/1.1.0/cli/index.md) - Cost estimation commands
- [Extending Shekel](https://arieradle.github.io/shekel/1.1.0/extending/index.md) - Adding custom models
- [Basic Usage](https://arieradle.github.io/shekel/1.1.0/usage/basic-usage/index.md) - Using budgets in code
