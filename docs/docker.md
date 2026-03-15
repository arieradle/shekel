# Docker & Container Guardrails

Use `shekel run` as an entrypoint wrapper to enforce LLM cost limits on any agent
running inside a Docker container — zero code changes required.

## Quick start

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install your agent and shekel CLI
COPY requirements.txt .
RUN pip install -r requirements.txt shekel[cli]

COPY agent.py .

# shekel run becomes the entrypoint; AGENT_BUDGET_USD sets the cap at runtime
ENTRYPOINT ["shekel", "run", "agent.py"]
```

Run with a $5 cap:

```bash
docker run -e AGENT_BUDGET_USD=5 my-agent-image
```

The container exits with code 1 if the budget is exceeded, so your orchestration
layer (ECS, Kubernetes, Compose) can detect it as a failed task.

---

## Patterns

### Budget via environment variable

The `AGENT_BUDGET_USD` env var is equivalent to `--budget N`. This is the
preferred pattern for containers because the budget can be set by the operator
without rebuilding the image.

```bash
# docker run
docker run -e AGENT_BUDGET_USD=10 my-agent-image

# docker-compose
services:
  agent:
    image: my-agent-image
    environment:
      AGENT_BUDGET_USD: "10"
```

### Budget via CLI flag (baked into image)

```dockerfile
ENTRYPOINT ["shekel", "run", "agent.py", "--budget", "5"]
```

### TOML config file

Mount a `shekel.toml` at runtime for fine-grained control:

```bash
docker run -v $(pwd)/shekel.toml:/app/shekel.toml \
  my-agent-image shekel run agent.py --budget-file /app/shekel.toml
```

```toml
# shekel.toml
[budget]
max_usd       = 5.0
warn_at       = 0.8
max_llm_calls = 50
max_tool_calls = 200
```

### Warn-only mode (log but don't kill)

```dockerfile
ENTRYPOINT ["shekel", "run", "agent.py", "--warn-only"]
```

With `--warn-only`, the container exits 0 even if the budget is exceeded.
Use this during development to observe spend without blocking the run.

### JSON output for structured logging

```bash
docker run my-agent-image shekel run agent.py --budget 5 --output json \
  | tee /logs/spend.json
```

The JSON line emitted at the end:

```json
{
  "spent": 1.23,
  "limit": 5.0,
  "calls": 12,
  "tool_calls": 4,
  "status": "ok",
  "model": "gpt-4o"
}
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | Script completed within budget (or `--warn-only` mode) |
| `1`  | Budget exceeded (default mode) |
| `2`  | Configuration error (missing script, bad TOML, etc.) |

---

## Shell script wrapper

For non-Docker environments (e.g. bare VMs, `.sh` CI scripts):

```bash
#!/usr/bin/env bash
set -euo pipefail

BUDGET="${AGENT_BUDGET_USD:-5}"

shekel run agent.py \
  --budget "$BUDGET" \
  --warn-at 0.8 \
  --output json \
  | tee spend.json

status=$(jq -r '.status' spend.json)
if [ "$status" = "exceeded" ]; then
  echo "Budget exceeded — check spend.json for details" >&2
  exit 1
fi
```

---

## GitHub Actions

See the [CLI reference](cli.md) or use the bundled composite action:

```yaml
- uses: ./.github/actions/enforce
  with:
    script: agent.py
    budget: "5"
    warn-at: "0.8"
```
