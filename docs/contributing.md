---
title: Contributing to Shekel – LLM Budget Control for Python
description: "Contribute to shekel, the open-source Python library for LLM budget control and AI agent cost governance. TDD required, 100% coverage, MIT license."
tags:
  - getting-started
---

# Contributing to Shekel

Thanks for your interest in contributing to shekel!

## Getting Started

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/arieradle/shekel
cd shekel

# Install in editable mode with all dependencies
pip install -e ".[all-models,dev]"
```

This installs:
- Shekel in editable mode
- All optional dependencies (OpenAI, Anthropic, tokencost)
- Development tools (pytest, black, ruff, mypy, etc.)

## Development Workflow

### Running Code Quality Checks

```bash
# Format code
black .

# Sort imports
isort .

# Lint
ruff check .

# Type check
mypy shekel/

# Run all checks
black . && isort . && ruff check . && mypy shekel/
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=shekel --cov-report=term-missing

# Run specific test file
pytest tests/test_budget.py -v

# Run specific test
pytest tests/test_budget.py::test_basic_tracking -v
```

### Test Coverage

Aim for >95% coverage. Check with:

```bash
pytest tests/ --cov=shekel --cov-report=html
open htmlcov/index.html
```

## Contributing Guidelines

### Adding a New Model

1. **Edit `shekel/prices.json`**:

```json
{
  "gpt-4o": {
    "input_per_1k": 0.0025,
    "output_per_1k": 0.01
  },
  "your-new-model": {
    "input_per_1k": 0.002,
    "output_per_1k": 0.006
  }
}
```

2. **Add test in `tests/test_pricing.py`**:

```python
def test_your_new_model():
    cost = calculate_cost("your-new-model", input_tokens=1000, output_tokens=500)
    expected = (1000 / 1000 * 0.002) + (500 / 1000 * 0.006)
    assert cost == expected
```

3. **Update documentation**:
   - Add model to `README.md`
   - Add model to `docs/models.md`
   - Update `CHANGELOG.md` under `[Unreleased]`

### Adding a Feature

1. **Create an issue** describing the feature
2. **Write tests first** (TDD approach)
3. **Implement the feature**
4. **Update documentation**
5. **Update `CHANGELOG.md`** under `[Unreleased]`
6. **Submit pull request**

### Fixing a Bug

1. **Create an issue** with reproduction steps
2. **Write a failing test** that demonstrates the bug
3. **Fix the bug**
4. **Verify the test passes**
5. **Update `CHANGELOG.md`** under `[Unreleased]`
6. **Submit pull request**

## Pull Request Guidelines

### Before Submitting

- [ ] All tests pass (`pytest tests/`)
- [ ] Code is formatted (`black .`)
- [ ] Imports are sorted (`isort .`)
- [ ] No linter errors (`ruff check .`)
- [ ] Type checks pass (`mypy shekel/`)
- [ ] Documentation is updated
- [ ] `CHANGELOG.md` is updated
- [ ] PR description explains the change

### PR Best Practices

1. **Keep PRs focused** - One change per PR
2. **Write clear commit messages**
3. **Add tests** for new functionality
4. **Update docs** for user-facing changes
5. **Reference issues** in PR description

### PR Title Format

Use conventional commits format:

- `feat: Add model fallback feature`
- `fix: Handle streaming edge case`
- `docs: Update installation guide`
- `test: Add coverage for async budgets`
- `chore: Update dependencies`

## Code Style

### Python Style

- Follow PEP 8
- Use type hints
- Write docstrings for public APIs
- Keep functions focused and small
- Use meaningful variable names

### Example

```python
from __future__ import annotations

def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    price_override: dict[str, float] | None = None,
) -> float:
    """Calculate the cost in USD for a given model call.
    
    Args:
        model: Model name (e.g., "gpt-4o")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        price_override: Optional custom pricing
    
    Returns:
        Cost in USD as a float
    """
    # Implementation...
```

## Testing Guidelines

### Test Structure

```python
def test_feature_name():
    """Test description."""
    # Arrange
    budget_obj = budget(max_usd=1.00)
    
    # Act
    with budget_obj:
        result = do_something()
    
    # Assert
    assert result == expected
```

### Test Categories

- **Unit tests**: Test individual functions
- **Integration tests**: Test full workflows
- **Async tests**: Test async functionality
- **Edge cases**: Test error conditions

### Mocking

Use pytest fixtures for mocking:

```python
@pytest.fixture
def mock_openai_client(monkeypatch):
    """Mock OpenAI client."""
    # Setup mock...
    return mock_client
```

## Documentation

### Docstring Format

```python
def budget(max_usd: float | None = None) -> Budget:
    """Create a budget context manager.
    
    Args:
        max_usd: Maximum spend in USD. None = track-only mode.
    
    Returns:
        Budget context manager object.
    
    Raises:
        ValueError: If max_usd is negative.
    
    Example:
        ```python
        with budget(max_usd=1.00) as b:
            run_agent()
        print(f"Spent: ${b.spent:.4f}")
        ```
    """
```

### Documentation Files

When adding features, update:

- `README.md` - If user-facing
- `docs/` - Relevant documentation pages
- `CHANGELOG.md` - Under `[Unreleased]`
- Docstrings - For public APIs

## Reporting Bugs

### Bug Report Template

Open an issue at [github.com/arieradle/shekel/issues](https://github.com/arieradle/shekel/issues) with:

**Environment:**
- Python version: `python --version`
- Shekel version: `python -c "import shekel; print(shekel.__version__)"`
- OS: macOS/Linux/Windows

**Bug Description:**
Clear description of the issue.

**Reproduction:**
```python
# Minimal code to reproduce
from shekel import budget

with budget(max_usd=1.00):
    # Bug occurs here
    ...
```

**Expected Behavior:**
What should happen.

**Actual Behavior:**
What actually happens.

**Traceback:**
```
Full error traceback
```

## Asking Questions

- **Usage questions**: Open a [Discussion](https://github.com/arieradle/shekel/discussions)
- **Bug reports**: Open an [Issue](https://github.com/arieradle/shekel/issues)
- **Feature requests**: Open an [Issue](https://github.com/arieradle/shekel/issues)

## Release Process

(For maintainers)

1. Update version in `shekel/__init__.py`
2. Update `CHANGELOG.md` with release date
3. Create git tag: `git tag v0.X.Y`
4. Push tag: `git push origin v0.X.Y`
5. GitHub Actions publishes to PyPI

## Code of Conduct

Be respectful and inclusive. We welcome contributions from everyone.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

Feel free to:
- Open a [Discussion](https://github.com/arieradle/shekel/discussions)
- Reach out to [@arieradle](https://github.com/arieradle)

Thank you for contributing to shekel! 🎉
