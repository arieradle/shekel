# Contributing to shekel

Thanks for your interest in contributing!

## Setup

```bash
git clone https://github.com/arieradle/shekel
cd shekel
pip install -e ".[all-models,dev]"
```

## Running checks

```bash
black .                  # format
isort .                  # sort imports
ruff check .             # lint
mypy shekel/             # type check
pytest tests/ -v         # run unit tests (excludes performance tests)
pytest tests/ --cov=shekel --cov-report=term-missing  # with coverage
pytest tests/performance/ --benchmark-only -v  # run performance tests
```

## Adding a model

Edit `shekel/prices.json` and add an entry:

```json
"model-name": {"input_per_1k": 0.001, "output_per_1k": 0.003}
```

Add a test in `tests/test_pricing.py` to verify the new model's cost calculation.

## Pull requests

- Keep PRs focused — one change per PR
- Add tests for new behaviour
- All CI checks must pass
- Update `CHANGELOG.md` under `[Unreleased]`

## Reporting bugs

Open an issue at https://github.com/arieradle/shekel/issues with:
- Python version
- shekel version (`python -c "import shekel; print(shekel.__version__)"`)
- Minimal reproduction
