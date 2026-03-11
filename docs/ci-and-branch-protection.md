# CI/CD and Branch Protection

This document describes the CI/CD pipeline and branch protection settings for shekel.

## CI Pipeline Overview

The CI pipeline runs on every pull request and push to `main`, and consists of three stages:

### 1. Quality Checks (Unit Tests Job)
Runs on Python 3.9, 3.10, 3.11, and 3.12 in parallel:
- **Format** (black): Code formatting
- **Import sort** (isort): Import ordering
- **Lint** (ruff): Code quality
- **Type check** (mypy): Type safety
- **Unit tests** (pytest): All tests except performance tests
- **Coverage**: Enforces 90% code coverage minimum

### 2. Performance Tests (Separate Job)
Runs after unit tests pass on Python 3.11:
- **Performance benchmarks**: Measures 120 performance tests across 6 domains
- **Regression detection**: Fails if any benchmark is >5% slower than baseline
- **Artifact storage**: Performance results stored for 30 days

### 3. Coverage Upload
Codecov integration runs on Python 3.11 builds.

## Running Tests Locally

**Unit tests** (fast, no API calls):
```bash
pytest tests/ -v --ignore=tests/performance
```

**Performance tests** (slower, deterministic benchmarks):
```bash
pytest tests/performance/ --benchmark-only -v
```

**Performance with detailed comparison**:
```bash
pytest tests/performance/ --benchmark-only --benchmark-compare=0
```

## Branch Protection Configuration

To enforce the CI pipeline on the `main` branch, configure these protection rules in GitHub:

### Settings → Branches → Branch protection rules

**For `main` branch:**

1. **Require a pull request before merging**
   - ✓ Dismiss stale pull request approvals when new commits are pushed
   - ✓ Require code owner reviews

2. **Require status checks to pass before merging**
   - ✓ Require branches to be up to date before merging
   - Required checks:
     - `test (3.9, 3.10, 3.11, 3.12)` — Unit tests on all Python versions
     - `performance` — Performance regression detection
     - `codecov/project/diff` — Coverage reports

3. **Require conversation resolution**
   - ✓ Require all conversations on code to be resolved

4. **Require deployments to succeed**
   - (Optional) If you have deployment jobs

### How to Set Up

1. Go to your GitHub repo → Settings → Branches
2. Click "Add rule"
3. Pattern: `main`
4. Enable "Require pull request before merging"
5. Enable "Require status checks to pass before merging"
6. Search and add these checks:
   - `test` (all Python versions)
   - `performance`
   - `codecov/project/diff` (if using Codecov)

## Performance Testing Details

### 120 Tests Across 6 Domains

The performance test suite is organized by functional domain (not generic coverage):

| Domain | Tests | Purpose |
|--------|-------|---------|
| Registry | 7 | Adapter lookup, caching, scaling |
| Lifecycle | 20 | Adapter creation, patch install/remove |
| Operations | 27 | Token extraction, streaming, parsing |
| Errors | 21 | Exception handling, error paths |
| Memory | 21 | Footprint, allocation, GC behavior |
| Concurrency | 24 | Thread safety, parallel ops, scaling |

### Regression Detection

The CI pipeline uses `--benchmark-compare-fail=min:5%` to automatically fail if any benchmark:
- Is **5% slower** than the baseline
- Has **>25% variance** (indicates flaky test)

This catches:
- Accidentally slower code
- Memory leaks
- Threading issues
- Scaling problems

### Viewing Performance Results

After a performance test run:
1. Go to the workflow run in GitHub Actions
2. Click the "Artifacts" section
3. Download `performance-results` to view:
   - `results.json` — Machine-readable benchmark data
   - `performance-report.txt` — Human-readable summary

## CI Workflow Files

- `.github/workflows/ci.yml` — Main test pipeline
- `.github/workflows/docs.yml` — Documentation build and deploy
- `.github/workflows/publish.yml` — PyPI release automation

## Skipping Checks

⚠️ **Not recommended**, but if absolutely necessary:
```bash
git push --force-with-lease                    # Bypass branch protection
git commit --no-verify                         # Bypass pre-commit hooks
```

This should only be done in emergencies by maintainers.

## References

- [GitHub Branch Protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)
- [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
- [GitHub Actions](https://docs.github.com/en/actions)
