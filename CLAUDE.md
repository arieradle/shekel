# CLAUDE.md — Development Guidelines

## Test File Naming

Tests must be organized **by domain**, not by implementation unit or coverage goal.

- **Good**: `test_openai_wrappers.py`, `test_gemini_wrappers.py`, `test_fallback.py`
- **Bad**: `test_patch_coverage.py`, `test_patching.py`, `test_coverage_for_x.py`

Name test files after the feature or domain being exercised, not after the module
being covered or the motivation for writing the tests.

## Code Quality

After finishing any dev work in this repo, always run the following linters and fix all errors before considering the work done:

```bash
python -m black <changed files>
python -m isort <changed files>
python -m ruff check <changed files>
python -m mypy <changed source files>
```
