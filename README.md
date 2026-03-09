# shekel

[![PyPI version](https://img.shields.io/pypi/v/shekel)](https://pypi.org/project/shekel/)
[![Python versions](https://img.shields.io/pypi/pyversions/shekel)](https://pypi.org/project/shekel/)
[![License](https://img.shields.io/pypi/l/shekel)](https://pypi.org/project/shekel/)
[![CI](https://github.com/arieradle/shekel/actions/workflows/ci.yml/badge.svg)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/arieradle/shekel/branch/main/graph/badge.svg)](https://codecov.io/gh/arieradle/shekel)
[![Downloads](https://img.shields.io/pypi/dm/shekel)](https://pypi.org/project/shekel/)

**LLM cost tracking and budget enforcement for Python. One line. Zero config.**

```python
with budget(max_usd=1.00):
    run_my_agent()  # raises BudgetExceededError if spend exceeds $1.00
```

I spent $47 debugging a LangGraph retry loop. The agent kept failing, LangGraph kept retrying, and OpenAI kept charging — all while I slept. I built shekel so you don't have to learn that lesson yourself.

---

## Install

```bash
pip install shekel[openai]       # OpenAI
pip install shekel[anthropic]    # Anthropic
pip install shekel[all]          # Both
pip install shekel[all-models]   # Both + tokencost (400+ model pricing)
pip install shekel[cli]          # CLI tools (shekel estimate, shekel models)
```

---

## Usage

```python
from shekel import budget, BudgetExceededError

# Enforce a hard cap
try:
    with budget(max_usd=1.00, warn_at=0.8) as b:
        run_my_agent()
    print(f"Spent ${b.spent:.4f}")
except BudgetExceededError as e:
    print(e)

# Fall back to a cheaper model instead of raising
with budget(max_usd=0.50, fallback="gpt-4o-mini") as b:
    run_my_agent()

# Decorator
from shekel import with_budget

@with_budget(max_usd=0.10)
def call_llm():
    ...

# Track spend without enforcing a limit
with budget() as b:
    run_my_agent()
print(f"Cost: ${b.spent:.4f}")

# Persistent budget across multiple runs
session = budget(max_usd=5.00, persistent=True)
with session:
    run_step_1()
with session:
    run_step_2()
print(f"Session total: ${session.spent:.4f}")

# Async
async with budget(max_usd=1.00) as b:
    await run_my_async_agent()

# Spend summary
with budget(max_usd=2.00) as b:
    run_my_agent()
print(b.summary())
```

Works with **LangGraph, CrewAI, AutoGen, LlamaIndex, Haystack**, and any framework that calls OpenAI or Anthropic under the hood. See [`examples/`](examples/) for runnable demos.

---

## CLI

```bash
pip install shekel[cli]

# Estimate cost before writing any code
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
# Model:          gpt-4o
# Input tokens:   1,000
# Output tokens:  500
# Estimated cost: $0.007500

# List all bundled models with pricing
shekel models
shekel models --provider openai
shekel models --provider anthropic
```

---

## API reference

### `budget(...)` / `with_budget(...)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_usd` | `float \| None` | `None` | Hard spend cap in USD. `None` = track only. |
| `warn_at` | `float \| None` | `None` | Fraction of limit (0.0–1.0) at which to warn. |
| `on_exceed` | `Callable \| None` | `None` | Callback at `warn_at` threshold. Receives `(spent, limit)`. |
| `price_per_1k_tokens` | `dict \| None` | `None` | Override pricing: `{"input": 0.001, "output": 0.003}`. |
| `fallback` | `str \| None` | `None` | Model to switch to when `max_usd` is hit. Same provider only. |
| `on_fallback` | `Callable \| None` | `None` | Callback on fallback switch. Receives `(spent, limit, fallback_model)`. |
| `hard_cap` | `float \| None` | `max_usd * 2` | Absolute ceiling when fallback is active. |
| `persistent` | `bool` | `False` | Accumulate spend across multiple `with` blocks. |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `b.spent` | `float` | Total USD spent. |
| `b.remaining` | `float \| None` | USD remaining, or `None` in track-only mode. |
| `b.limit` | `float \| None` | Configured `max_usd`. |
| `b.model_switched` | `bool` | `True` if fallback was activated. |
| `b.switched_at_usd` | `float \| None` | Spend level when fallback triggered. |
| `b.fallback_spent` | `float` | Cost on the fallback model. |

### `BudgetExceededError`

| Attribute | Description |
|-----------|-------------|
| `e.spent` | Total spend when limit was hit. |
| `e.limit` | The configured `max_usd`. |
| `e.model` | Model that triggered the error. |
| `e.tokens` | `{"input": N, "output": N}` from the last call. |

---

## Supported models

| Model | Input / 1k | Output / 1k |
|-------|-----------|-------------|
| gpt-4o | $0.00250 | $0.01000 |
| gpt-4o-mini | $0.000150 | $0.000600 |
| o1 | $0.01500 | $0.06000 |
| o1-mini | $0.00300 | $0.01200 |
| gpt-3.5-turbo | $0.000500 | $0.001500 |
| claude-3-5-sonnet-20241022 | $0.00300 | $0.01500 |
| claude-3-haiku-20240307 | $0.000250 | $0.001250 |
| claude-3-opus-20240229 | $0.01500 | $0.07500 |
| gemini-1.5-flash | $0.0000750 | $0.000300 |
| gemini-1.5-pro | $0.00125 | $0.00500 |

For unlisted models: pass `price_per_1k_tokens` or install `shekel[all-models]` for 400+ models via [tokencost](https://github.com/AgentOps-AI/tokencost).

---

## How it works

- **Monkey-patching** — wraps `openai.ChatCompletions.create` and `anthropic.Messages.create` on context entry; restores originals on exit.
- **ContextVar isolation** — each `budget()` stores its counter in a `ContextVar`; concurrent agents never share state.
- **Ref-counted patching** — nested contexts patch only once.
- **Zero config** — no API keys, no external services.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
