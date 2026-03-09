# CrewAI Integration

Shekel integrates seamlessly with [CrewAI](https://github.com/joaomdmoura/crewAI) to track and enforce budgets on multi-agent workflows.

## Installation

```bash
pip install shekel[openai] crewai
```

## Basic Integration

Wrap your Crew execution with a budget context:

```python
from crewai import Agent, Task, Crew
from shekel import budget

# Define your agent
researcher = Agent(
    role='Researcher',
    goal='Research and provide accurate information',
    backstory='Expert researcher with attention to detail',
    verbose=True
)

# Define task
task = Task(
    description='Research the history of artificial intelligence',
    agent=researcher,
    expected_output='A comprehensive overview of AI history'
)

# Create crew
crew = Crew(
    agents=[researcher],
    tasks=[task],
    verbose=True
)

# Execute with budget
with budget(max_usd=1.00) as b:
    result = crew.kickoff()
    print(f"Crew execution cost: ${b.spent:.4f}")
```

## Multi-Agent Crews

Track costs across multiple agents:

```python
from crewai import Agent, Task, Crew, Process
from shekel import budget

# Define agents
researcher = Agent(
    role='Researcher',
    goal='Gather comprehensive information',
    backstory='Experienced researcher',
)

writer = Agent(
    role='Writer',
    goal='Create engaging content',
    backstory='Professional content writer',
)

editor = Agent(
    role='Editor',
    goal='Ensure quality and accuracy',
    backstory='Meticulous editor',
)

# Define tasks
research_task = Task(
    description='Research AI developments in 2024',
    agent=researcher,
    expected_output='Research findings'
)

write_task = Task(
    description='Write an article based on research',
    agent=writer,
    expected_output='Draft article',
)

edit_task = Task(
    description='Edit and finalize the article',
    agent=editor,
    expected_output='Final article'
)

# Create crew
crew = Crew(
    agents=[researcher, writer, editor],
    tasks=[research_task, write_task, edit_task],
    process=Process.sequential,
    verbose=True
)

# All agents tracked under one budget
with budget(max_usd=5.00) as b:
    result = crew.kickoff()
    print(f"Total crew cost: ${b.spent:.4f}")
    print(b.summary())
```

## Budget Protection for Crews

Prevent runaway costs from agent loops:

```python
from shekel import budget, BudgetExceededError

try:
    with budget(max_usd=2.00, warn_at=0.8) as b:
        result = crew.kickoff()
        print(f"Success! Cost: ${b.spent:.4f}")
except BudgetExceededError as e:
    print(f"Crew stopped due to budget: ${e.spent:.4f}")
```

## Fallback Models

Use cheaper models when budget is reached:

```python
with budget(max_usd=1.00, fallback="gpt-4o-mini") as b:
    result = crew.kickoff()
    
    if b.model_switched:
        print(f"Switched to cheaper model at ${b.switched_at_usd:.4f}")
```

## Per-Crew Budgets

Different budgets for different crew types:

```python
CREW_BUDGETS = {
    "research": 0.50,
    "writing": 1.00,
    "analysis": 2.00,
}

def run_crew(crew_type: str, crew: Crew):
    budget_limit = CREW_BUDGETS.get(crew_type, 1.00)
    
    with budget(max_usd=budget_limit) as b:
        result = crew.kickoff()
        return result, b.spent

result, cost = run_crew("research", research_crew)
print(f"{crew_type} crew cost: ${cost:.4f}")
```

## Next Steps

- [OpenAI Integration](openai.md)
- [LangGraph Integration](langgraph.md)
- [Budget Enforcement](../usage/budget-enforcement.md)
