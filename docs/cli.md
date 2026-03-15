# CLI Tools

Shekel provides command-line tools for budget enforcement, cost estimation, and model information.

## Installation

```bash
pip install shekel[cli]
```

This installs the `shekel` command with Click support.

## Commands

### `shekel run`

Run a Python script with budget enforcement. Equivalent to wrapping your script
in `with budget(max_usd=N):` — zero code changes required.

#### Usage

```bash
shekel run SCRIPT [OPTIONS] [-- SCRIPT_ARGS...]
```

#### Options

| Option | Description |
|--------|-------------|
| `--budget N` | Max spend in USD. Equivalent to `AGENT_BUDGET_USD=N`. |
| `--warn-at F` | Warn fraction 0.0–1.0 (e.g. `0.8` = warn at 80% of budget). |
| `--max-llm-calls N` | Cap on LLM API calls. |
| `--max-tool-calls N` | Cap on tool invocations. |
| `--warn-only` | Warn but never exit 1 when budget exceeded. |
| `--dry-run` | Track costs only — no enforcement. Implies `--warn-only`. |
| `--output text\|json` | Output format (default: `text`). |
| `--budget-file PATH` | Path to a `shekel.toml` config file. |
| `--fallback-model M` | Cheaper model to switch to at threshold. |
| `--fallback-at F` | Fallback activation threshold (default: `0.8`). |

#### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Script completed within budget |
| `1` | Budget exceeded (unless `--warn-only`) |
| `2` | Configuration error (missing script, bad TOML, etc.) |

#### Environment variables

| Variable | Description |
|----------|-------------|
| `AGENT_BUDGET_USD` | Fallback for `--budget`. Ideal for Docker/CI operator control. |

#### Examples

```bash
# Enforce a $5 cap
shekel run agent.py --budget 5

# Warn at 80%, hard-stop at $5
shekel run agent.py --budget 5 --warn-at 0.8

# Cap LLM calls instead of spend
shekel run agent.py --max-llm-calls 20

# JSON output for CI log parsing
shekel run agent.py --budget 5 --output json

# Warn but don't fail the pipeline
shekel run agent.py --budget 5 --warn-only

# Dry-run: track costs without enforcement
shekel run agent.py --budget 5 --dry-run

# Load limits from TOML file
shekel run agent.py --budget-file shekel.toml

# Set budget via env var (Docker / CI)
AGENT_BUDGET_USD=5 shekel run agent.py
```

#### `shekel.toml` format

```toml
[budget]
max_usd       = 5.0
warn_at       = 0.8
max_llm_calls = 50
max_tool_calls = 200
```

See [Docker & Container Guardrails](docker.md) for container-specific patterns.

---

### `shekel estimate`

Estimate API call costs without making actual requests.

#### Usage

```bash
shekel estimate --model MODEL --input-tokens N --output-tokens N
```

#### Options

| Option | Required | Description |
|--------|----------|-------------|
| `--model` | Yes | Model name (e.g., `gpt-4o`, `claude-3-5-sonnet-20241022`) |
| `--input-tokens` | Yes | Number of input/prompt tokens |
| `--output-tokens` | Yes | Number of output/completion tokens |

#### Examples

```bash
# Estimate gpt-4o cost
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
```

Output:
```
Model:         gpt-4o
Input tokens:  1,000
Output tokens: 500
Estimated cost: $0.007500
```

```bash
# Estimate Claude cost
shekel estimate --model claude-3-5-sonnet-20241022 --input-tokens 2000 --output-tokens 1000
```

Output:
```
Model:         claude-3-5-sonnet-20241022
Input tokens:  2,000
Output tokens: 1,000
Estimated cost: $0.021000
```

```bash
# Very large request
shekel estimate --model gpt-4o-mini --input-tokens 100000 --output-tokens 50000
```

Output:
```
Model:         gpt-4o-mini
Input tokens:  100,000
Output tokens: 50,000
Estimated cost: $0.045000
```

### `shekel models`

List all bundled models with pricing information.

#### Usage

```bash
shekel models [--provider PROVIDER]
```

#### Options

| Option | Required | Description |
|--------|----------|-------------|
| `--provider` | No | Filter by provider: `openai`, `anthropic`, or `google` |

#### Examples

```bash
# List all models
shekel models
```

Output:
```
Model                         Input/1k     Output/1k
----------------------------------------------------------
gpt-4o                        $0.002500    $0.010000
gpt-4o-mini                   $0.000150    $0.000600
o1                            $0.015000    $0.060000
o1-mini                       $0.003000    $0.012000
gpt-3.5-turbo                 $0.000500    $0.001500
claude-3-5-sonnet-20241022    $0.003000    $0.015000
claude-3-haiku-20240307       $0.000250    $0.001250
claude-3-opus-20240229        $0.015000    $0.075000
gemini-1.5-flash              $0.000075    $0.000300
gemini-1.5-pro                $0.001250    $0.005000
```

```bash
# OpenAI models only
shekel models --provider openai
```

Output:
```
Model            Input/1k     Output/1k
------------------------------------------
gpt-4o           $0.002500    $0.010000
gpt-4o-mini      $0.000150    $0.000600
o1               $0.015000    $0.060000
o1-mini          $0.003000    $0.012000
gpt-3.5-turbo    $0.000500    $0.001500
```

```bash
# Anthropic models only
shekel models --provider anthropic
```

Output:
```
Model                         Input/1k     Output/1k
------------------------------------------------------
claude-3-5-sonnet-20241022    $0.003000    $0.015000
claude-3-haiku-20240307       $0.000250    $0.001250
claude-3-opus-20240229        $0.015000    $0.075000
```

```bash
# Google models only
shekel models --provider google
```

Output:
```
Model                Input/1k     Output/1k
----------------------------------------------
gemini-1.5-flash     $0.000075    $0.000300
gemini-1.5-pro       $0.001250    $0.005000
```

## Use Cases

### 1. Budget Planning

Estimate costs before implementing:

```bash
# How much will 100 API calls cost?
shekel estimate --model gpt-4o-mini --input-tokens 500 --output-tokens 200
# $0.000195 per call
# 100 calls = $0.0195
```

### 2. Model Comparison

Compare costs across models:

```bash
# Expensive model
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
# $0.007500

# Cheap model
shekel estimate --model gpt-4o-mini --input-tokens 1000 --output-tokens 500
# $0.000450

# Savings: $0.007050 per call (94% cheaper!)
```

### 3. Find Cheapest Model

```bash
shekel models --provider openai
# Compare pricing to find cheapest option
# Result: gpt-4o-mini at $0.000150 input / $0.000600 output
```

### 4. Validate Custom Pricing

Check if your custom pricing is reasonable:

```bash
shekel models
# Compare your custom model pricing against similar models
```

## Scripting

Use in shell scripts:

```bash
#!/bin/bash

# Calculate batch cost
MODEL="gpt-4o-mini"
INPUT_TOKENS=500
OUTPUT_TOKENS=200
BATCH_SIZE=1000

# Get cost per call
COST=$(shekel estimate \
  --model $MODEL \
  --input-tokens $INPUT_TOKENS \
  --output-tokens $OUTPUT_TOKENS \
  | grep "Estimated cost" \
  | awk '{print $3}' \
  | tr -d '$')

# Calculate total
TOTAL=$(echo "$COST * $BATCH_SIZE" | bc)
echo "Total batch cost: \$$TOTAL"
```

## Programmatic Access

The CLI uses the same pricing data as the Python API:

```python
from shekel._pricing import calculate_cost, list_models

# Estimate cost
cost = calculate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
print(f"Cost: ${cost:.6f}")

# List models
models = list_models()
print(f"Available models: {models}")
```

## Next Steps

- [Docker & Container Guardrails](docker.md) - Using `shekel run` in Docker
- [Supported Models](models.md) - Full model list with pricing
- [Installation](installation.md) - Installing CLI tools
- [Basic Usage](usage/basic-usage.md) - Using budgets in code
