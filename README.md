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

---

## The problem

LLM agent loops can burn money fast. A retry bug, an infinite loop, an unexpectedly expensive prompt — and you wake up to a $47 bill. shekel stops that from happening by letting you set a hard spending cap around any block of code.

---

## Install

```bash
pip install shekel[openai]      # OpenAI
pip install shekel[anthropic]   # Anthropic
pip install shekel[all]         # Both
```

---

## Usage

### Enforce a budget

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=1.00) as b:
        run_my_agent()
    print(f"Done. Spent ${b.spent:.4f}")
except BudgetExceededError as e:
    print(e)
    # Budget of $1.00 exceeded ($1.0023 spent)
    #   Last call: gpt-4o — 512 input + 1024 output tokens
    #   Tip: Increase max_usd or add warn_at=0.8 to get an early warning next time.
```

### Get a warning before the limit hits

```python
def on_warning(spent: float, limit: float) -> None:
    print(f"Warning: ${spent:.4f} of ${limit:.2f} used")

with budget(max_usd=1.00, warn_at=0.8, on_exceed=on_warning) as b:
    run_my_agent()
```

Or without a callback — shekel will emit a `warnings.warn` automatically.

### Track spend without enforcing a limit

```python
with budget() as b:
    run_my_agent()

print(f"That run cost: ${b.spent:.4f}")
```

### Async support

```python
async with budget(max_usd=1.00) as b:
    await run_my_async_agent()
```

### Custom / unlisted model pricing

```python
with budget(max_usd=1.00, price_per_1k_tokens={"input": 0.001, "output": 0.003}):
    run_my_agent()
```

---

## Works with LangGraph, CrewAI, and everything else

shekel intercepts at the SDK level — it works with any framework that uses OpenAI or Anthropic under the hood.

```python
# LangGraph
with budget(max_usd=2.00, warn_at=0.8) as b:
    result = app.invoke({"input": "..."})
print(f"Graph run: ${b.spent:.4f}")

# CrewAI
with budget(max_usd=5.00) as b:
    crew.kickoff()

# Autogen, LlamaIndex, raw SDK — same pattern
with budget(max_usd=0.50) as b:
    for _ in range(100):
        client.chat.completions.create(...)  # stops when budget hit
```

---

## API reference

### `budget(max_usd, warn_at, on_exceed, price_per_1k_tokens)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_usd` | `float \| None` | `None` | Hard spend cap in USD. `None` = track only. |
| `warn_at` | `float \| None` | `None` | Fraction of limit (0.0–1.0) at which to warn. |
| `on_exceed` | `Callable[[float, float], None] \| None` | `None` | Callback fired at `warn_at` threshold. Receives `(spent, limit)`. |
| `price_per_1k_tokens` | `dict \| None` | `None` | Override pricing: `{"input": 0.001, "output": 0.003}`. |

### `budget` properties (inside `as b`)

| Property | Type | Description |
|----------|------|-------------|
| `b.spent` | `float` | Total USD spent so far. |
| `b.remaining` | `float \| None` | USD remaining, or `None` in track-only mode. |
| `b.limit` | `float \| None` | Configured `max_usd`, or `None`. |

### `BudgetExceededError`

| Attribute | Type | Description |
|-----------|------|-------------|
| `e.spent` | `float` | Total spend when limit was hit. |
| `e.limit` | `float` | The configured `max_usd`. |
| `e.model` | `str` | Model name from the call that triggered the error. |
| `e.tokens` | `dict` | `{"input": N, "output": N}` from the last call. |

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

Any other model? Use `price_per_1k_tokens` to pass custom pricing.

---

## How it works

- **Monkey-patching** — on context entry, shekel wraps `openai.ChatCompletions.create` and `anthropic.Messages.create` at the class level. Your code calls the real SDK; shekel intercepts the response, reads token counts, and records the cost. Original methods are restored on exit.
- **ContextVar isolation** — each `budget()` context stores its counter in a `contextvars.ContextVar`. Two concurrent agent runs (threads or async tasks) never share a budget counter.
- **Ref-counted patching** — nested `budget()` contexts patch only once and unpack cleanly on the last exit.
- **Zero config** — no API keys, no environment variables, no external services.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
