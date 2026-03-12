# Installation

!!! success "Zero external dependencies"
    Shekel requires **no API keys**, **no external services**, and **no configuration**. Install, wrap your calls in `with budget():`, and you're done.

## Requirements

- Python 3.9 or higher
- OpenAI SDK (optional) — for OpenAI models
- Anthropic SDK (optional) — for Anthropic models
- LiteLLM (optional) — budget enforcement and circuit-breaking across 100+ providers via a unified interface

## Install Shekel

Choose the installation option that matches your LLM provider:

### OpenAI Only

If you're only using OpenAI models (GPT-4o, GPT-4o-mini, o1, etc.):

```bash
pip install shekel[openai]
```

### Anthropic Only

If you're only using Anthropic models (Claude 3.5 Sonnet, Claude 3 Haiku, etc.):

```bash
pip install shekel[anthropic]
```

### Both OpenAI and Anthropic

If you're using models from both providers:

```bash
pip install shekel[all]
```

### Google Gemini

For Google Gemini via the `google-genai` SDK:

```bash
pip install shekel[gemini]
```

### HuggingFace Inference API

For HuggingFace's `InferenceClient`:

```bash
pip install shekel[huggingface]
```

### LiteLLM (100+ Providers)

To enforce hard spend limits and circuit-break across OpenAI, Anthropic, Gemini, Cohere, Ollama, Azure, Bedrock, and 90+ more through a unified interface:

```bash
pip install shekel[litellm]
```

### Extended Model Support (400+ Models)

For support of 400+ models via [tokencost](https://github.com/AgentOps-AI/tokencost):

```bash
pip install shekel[all-models]
```

This includes models from Google (Gemini), Cohere, AI21, Aleph Alpha, and many more.

### CLI Tools

To use the `shekel` command-line tools:

```bash
pip install shekel[cli]
```

This enables commands like:

```bash
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
shekel models
shekel models --provider openai
```

### Development Installation

If you want to contribute to shekel or modify the source:

```bash
git clone https://github.com/arieradle/shekel
cd shekel
pip install -e ".[all-models,dev]"
```

This installs shekel in editable mode with all development dependencies.

## Verify Installation

After installation, verify that shekel is installed correctly:

```python
import shekel
print(shekel.__version__)
```

You should see the version number printed (e.g., `0.2.2`).

## No API Keys Required

Unlike other cost tracking tools, shekel requires **no API keys** and **no external services**. It works by monkey-patching the OpenAI and Anthropic SDKs to track token usage and calculate costs locally.

Your existing API keys for OpenAI or Anthropic work as-is — shekel doesn't interfere with authentication.

## Minimal Dependencies

Shekel has zero required dependencies beyond the Python standard library. The OpenAI and Anthropic SDKs are optional — install only what you need.

| Package | Required? | Purpose |
|---------|-----------|---------|
| `openai>=1.0.0` | Optional | Track OpenAI API costs |
| `anthropic>=0.7.0` | Optional | Track Anthropic API costs |
| `litellm>=1.0.0` | Optional | Budget enforcement and circuit-breaking via LiteLLM (100+ providers) |
| `google-genai>=1.0.0` | Optional | Track Google Gemini costs (native SDK) |
| `huggingface-hub>=0.20.0` | Optional | Track HuggingFace Inference API costs |
| `tokencost>=0.1.0` | Optional | Support 400+ models |
| `click>=8.0.0` | Optional | CLI tools |

## Troubleshooting

### ImportError: No module named 'openai'

If you see this error, install the OpenAI SDK:

```bash
pip install shekel[openai]
```

### ImportError: No module named 'anthropic'

If you see this error, install the Anthropic SDK:

```bash
pip install shekel[anthropic]
```

### ImportError: No module named 'litellm'

If you see this error, install LiteLLM:

```bash
pip install shekel[litellm]
```

### Model pricing not found

For models not in shekel's built-in pricing table:

1. Install extended model support: `pip install shekel[all-models]`
2. Or provide custom pricing: `budget(price_per_1k_tokens={"input": 0.001, "output": 0.003})`

See [Extending Shekel](extending.md) for more details.

## Next Steps

- [Quick Start Guide](quickstart.md) - Get started with basic examples
- [Basic Usage](usage/basic-usage.md) - Learn the fundamentals
- [API Reference](api-reference.md) - Full API documentation
