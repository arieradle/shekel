# Quick Start

This guide will get you up and running with shekel in 5 minutes.

## Step 1: Install Shekel

Choose the installation that matches your LLM provider:

```bash
pip install shekel[openai]       # For OpenAI
pip install shekel[anthropic]    # For Anthropic
pip install shekel[litellm]      # For 100+ providers via LiteLLM
pip install shekel[all]          # For OpenAI + Anthropic + LiteLLM
```

## Step 2: Import and Use

```python
from shekel import budget, BudgetExceededError
```

That's it! No API keys, no configuration files, no external services.

## Step 3: Track Your First Call

### OpenAI Example

```python
import openai
from shekel import budget

client = openai.OpenAI()  # Your API key from environment

# Track cost without enforcing a limit
with budget() as b:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello! How are you?"}],
    )
    print(response.choices[0].message.content)

print(f"That cost: ${b.spent:.4f}")
# Output: That cost: $0.0002
```

### Anthropic Example

```python
import anthropic
from shekel import budget

client = anthropic.Anthropic()  # Your API key from environment

with budget() as b:
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hello!"}],
    )
    print(response.content[0].text)

print(f"That cost: ${b.spent:.4f}")
```

## Step 4: Enforce a Budget

Add a hard cap to prevent runaway costs — two ways:

**In code:**

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=0.50) as b:
        run_my_agent()  # Your agent code here
    print(f"Success! Spent: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Budget exceeded: {e}")
    print(f"Spent: ${e.spent:.4f} / ${e.limit:.2f}")
```

**From the CLI — zero code changes:**

```bash
pip install shekel[cli]
shekel run agent.py --budget 0.50
# exits with code 1 if budget exceeded — CI-friendly
```

## Step 5: Add Early Warnings

Get warned before you hit the limit:

```python
with budget(max_usd=1.00, warn_at=0.8) as b:
    run_my_agent()
# Prints warning at $0.80 (80% of $1.00)
```

## Common Patterns

### Pattern 1: Track-Only Mode

No enforcement, just track spending:

```python
with budget() as b:
    run_my_agent()
print(f"Total cost: ${b.spent:.4f}")
```

### Pattern 2: Hard Cap with Early Warning

Enforce a limit with advance warning:

```python
with budget(max_usd=2.00, warn_at=0.8) as b:
    run_my_agent()
# Warns at $1.60, raises at $2.00
```

### Pattern 3: Fallback to Cheaper Model

Switch models instead of crashing:

```python
with budget(max_usd=1.00, fallback={"at_pct": 0.8, "model": "gpt-4o-mini"}) as b:
    response = client.chat.completions.create(
        model="gpt-4o",  # Starts with expensive model
        messages=[{"role": "user", "content": "Hello"}],
    )
# Automatically switches to gpt-4o-mini at 80% of $1.00 ($0.80)

if b.model_switched:
    print(f"Switched to fallback at ${b.switched_at_usd:.4f}")
```

### Pattern 4: Nested Budgets

Control costs for multi-stage workflows:

```python
with budget(max_usd=10.00, name="workflow") as workflow:
    # Research phase: $2 budget
    with budget(max_usd=2.00, name="research"):
        research_results = search_and_analyze()
    
    # Processing phase: $5 budget
    with budget(max_usd=5.00, name="processing"):
        processed = process_results(research_results)
    
    # Finalization (parent budget)
    final = finalize(processed)

print(f"Total cost: ${workflow.spent:.2f}")
print(workflow.tree())
# workflow: $7.20 / $10.00 (direct: $0.20)
#   research: $2.00 / $2.00 (direct: $2.00)
#   processing: $5.00 / $5.00 (direct: $5.00)
```

**Why this matters:**
- Each stage has its own budget limit
- Children auto-capped to parent's remaining budget
- Clear cost attribution per stage
- Perfect for complex multi-stage agents

[Learn more about nested budgets →](usage/nested-budgets.md)

### Pattern 5: Accumulating Sessions

Track spending across multiple runs:

```python
session = budget(max_usd=5.00, name="session")

# First run
with session:
    process_batch_1()
print(f"After batch 1: ${session.spent:.4f}")

# Second run - spend accumulates
with session:
    process_batch_2()
print(f"After batch 2: ${session.spent:.4f}")

# Third run
with session:
    process_batch_3()
print(f"Total session spend: ${session.spent:.4f}")
```

**Note:** Budget variables always accumulate across uses.

### Pattern 6: Decorator

Wrap functions with a budget:

```python
from shekel import with_budget

@with_budget(max_usd=0.10)
def generate_summary(text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize: {text}"}],
    )
    return response.choices[0].message.content

# Budget enforced on every call
summary = generate_summary("Long text here...")
```

### Pattern 6: Async Support

Full async/await support:

```python
async def process_items():
    async with budget(max_usd=1.00) as b:
        for item in items:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": item}],
            )
            await process(response)
    print(f"Processed {len(items)} items for ${b.spent:.4f}")
```

### Pattern 7: Streaming

Budget tracking works with streaming:

```python
with budget(max_usd=0.50) as b:
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Count to 10"}],
        stream=True,
    )
    for chunk in stream:
        print(chunk.choices[0].delta.content or "", end="", flush=True)

print(f"\nStreaming cost: ${b.spent:.4f}")
```

## Working with Frameworks

Shekel works automatically with any framework that uses OpenAI, Anthropic, or LiteLLM under the hood.

### LiteLLM

Track costs across 100+ providers with a single adapter:

```python
import litellm
from shekel import budget

with budget(max_usd=0.50) as b:
    response = litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello!"}],
    )
print(f"Cost: ${b.spent:.4f}")
```

### LangGraph

Shekel works with LangGraph out of the box — just wrap with `budget()`:

```python
from shekel import budget

# Your graph definition here
app = graph.compile()

with budget(max_usd=0.50, name="my-graph") as b:
    result = app.invoke({"question": "What is 2+2?"})
print(f"Graph execution cost: ${b.spent:.4f}")
```

### CrewAI

Shekel auto-detects CrewAI and enforces caps with zero crew changes. Use `b.agent()` and `b.task()` for per-component circuit breaking:

```python
from crewai import Agent, Task, Crew
from shekel import budget
from shekel.exceptions import AgentBudgetExceededError, TaskBudgetExceededError

researcher = Agent(role="Researcher", goal="...", backstory="...", llm="gpt-4o-mini")
writer = Agent(role="Writer", goal="...", backstory="...", llm="gpt-4o-mini")

research_task = Task(name="research", description="Research: {topic}", expected_output="...", agent=researcher)
write_task = Task(name="write", description="Write a summary.", expected_output="...", agent=writer)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task])

try:
    with budget(max_usd=5.00) as b:
        b.agent(researcher.role, max_usd=2.00)   # AgentBudgetExceededError if exceeded
        b.task(research_task.name, max_usd=1.50)  # TaskBudgetExceededError if exceeded
        crew.kickoff(inputs={"topic": "AI"})
    print(f"Done. Spent: ${b.spent:.4f}")
    print(b.tree())
except TaskBudgetExceededError as e:
    print(f"Task '{e.task_name}' exceeded cap")
except AgentBudgetExceededError as e:
    print(f"Agent '{e.agent_name}' exceeded cap")
```

See [CrewAI Integration](integrations/crewai.md) for the full reference.

## Viewing Spend Summary

Get a detailed breakdown of your spending:

```python
with budget(max_usd=5.00) as b:
    run_my_agent()

# Print formatted summary
print(b.summary())
```

Output:

```
┌─ Shekel Budget Summary ────────────────────────────────────┐
│ Total: $1.2340  Limit: $5.00  Calls: 15  Status: OK
├────────────────────────────────────────────────────────────┤
│  #    Model                        Input  Output      Cost
│  ────────────────────────────────────────────────────────
│  1    gpt-4o-mini                  1,200     300  $0.0003
│  2    gpt-4o-mini                  1,500     450  $0.0004
│  ...
├────────────────────────────────────────────────────────────┤
│  gpt-4o-mini: 15 calls  $1.2340
└────────────────────────────────────────────────────────────┘
```

## CLI Tools

### Budget enforcement from the command line

Run any Python agent with a hard cap — no code changes required:

```bash
pip install shekel[cli]

shekel run agent.py --budget 5           # hard stop at $5, exit 1
shekel run agent.py --budget 5 --warn-at 0.8  # warn at 80%
shekel run agent.py --max-llm-calls 20   # cap by call count
shekel run agent.py --warn-only          # log, never exit 1
shekel run agent.py --output json        # machine-readable spend line
AGENT_BUDGET_USD=5 shekel run agent.py  # Docker / CI env var
```

### Cost estimation

```bash
# Estimate cost before making API calls
shekel estimate --model gpt-4o --input-tokens 1000 --output-tokens 500
# Model:          gpt-4o
# Input tokens:   1,000
# Output tokens:  500
# Estimated cost: $0.007500

# List all supported models
shekel models

# Filter by provider
shekel models --provider openai
shekel models --provider anthropic
```

## Next Steps

Now that you've seen the basics, dive deeper:

- **[CLI Reference](cli.md)** - Full `shekel run` options, flags, and exit codes
- **[Docker & Containers](docker.md)** - Entrypoint patterns, env vars, JSON logging
- **[Nested Budgets](usage/nested-budgets.md)** - Hierarchical tracking for multi-stage workflows
- **[Budget Enforcement](usage/budget-enforcement.md)** - Learn about hard caps, warnings, and callbacks
- **[Fallback Models](usage/fallback-models.md)** - Automatic model switching
- **[Streaming](usage/streaming.md)** - Budget tracking for streaming responses
- **[API Reference](api-reference.md)** - Complete API documentation
- **[Integrations](integrations/langgraph.md)** - Framework-specific guides

## Common Questions

### Does shekel require API keys?

No. Shekel uses your existing OpenAI or Anthropic API keys. It doesn't require any additional authentication.

### Does shekel send my data anywhere?

No. Shekel works entirely locally by monkey-patching the OpenAI and Anthropic SDKs. No data leaves your system.

### What happens when I hit the budget limit?

By default, shekel raises a `BudgetExceededError`. You can catch this exception or use the `fallback` parameter to automatically switch to a cheaper model instead.

### Can I use shekel with my custom models?

Yes! Use the `price_per_1k_tokens` parameter to provide custom pricing. See [Extending Shekel](extending.md) for details.

### Does shekel work with streaming?

Yes! Shekel fully supports streaming responses from both OpenAI and Anthropic.
