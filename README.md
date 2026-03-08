[![PyPI version](https://badge.fury.io/py/shekel.svg)](https://badge.fury.io/py/shekel)
[![Python versions](https://img.shields.io/pypi/pyversions/shekel.svg)](https://pypi.org/project/shekel/)
[![CI](https://github.com/arieradle/shekel/actions/workflows/ci.yml/badge.svg)](https://github.com/arieradle/shekel/actions/workflows/ci.yml)

```python
with budget(max_usd=1.00):
    run_my_agent()  # raises BudgetExceededError if spend exceeds $1.00
```

I spent $47 debugging a LangGraph retry loop. The agent kept failing, LangGraph kept retrying, and OpenAI kept charging — all while I slept. I built shekel so you don't have to learn that lesson yourself.

---

## Install

```bash
pip install shekel[openai]      # OpenAI only
pip install shekel[anthropic]   # Anthropic only
pip install shekel[all]         # Both SDKs
```

*Advanced: `pip install shekel` installs the core with no SDK deps (track-only mode).*

---

## Quick start

```python
from shekel import budget, BudgetExceededError
import openai

client = openai.OpenAI()

try:
    with budget(max_usd=1.00, warn_at=0.8) as b:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello!"}],
        )
    print(f"Spent: ${b.spent:.4f} of ${b.limit:.2f}")
except BudgetExceededError as e:
    print(e)
```

---

## Track-only mode

No `max_usd` = track spend without enforcing a limit. Great for profiling agents.

```python
with budget() as b:
    run_my_agent()

print(f"That run cost: ${b.spent:.4f}")
```

---

## How it works

- **Monkey-patching**: When you enter a `budget()` context, shekel wraps `openai.ChatCompletions.create` and `anthropic.Messages.create` at the class level. Your code calls the real SDK — shekel intercepts the response, reads the token counts, and calculates cost. On context exit, original methods are restored.
- **ContextVar isolation**: Each `budget()` context tracks its own spend using Python's `contextvars.ContextVar`. Two concurrent agent runs never share a budget counter, even in async or multi-threaded code.
- **Zero config**: No API keys, no external services, no config files. `pip install` + `with budget(...)` is all you need.

---

## Model support

| Model | Input (per 1k) | Output (per 1k) |
|-------|---------------|-----------------|
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

**Model not listed?** Pass a price override:

```python
with budget(max_usd=1.00, price_per_1k_tokens={"input": 0.001, "output": 0.003}):
    run_my_agent()
```

---

## Works with LangGraph, CrewAI, and any framework

shekel is framework-agnostic. It intercepts at the SDK level, so it works with anything that calls OpenAI or Anthropic under the hood:

```python
# LangGraph
with budget(max_usd=2.00, warn_at=0.8) as b:
    result = langgraph_app.invoke({"input": "..."})
print(f"Graph run cost: ${b.spent:.4f}")

# CrewAI
with budget(max_usd=5.00) as b:
    crew.kickoff()

# Raw SDK
with budget(max_usd=0.50) as b:
    for _ in range(100):
        client.chat.completions.create(...)  # stops when budget hit
```

---

## License

MIT
