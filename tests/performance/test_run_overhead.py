"""Performance test: shekel run overhead should be sub-100 ms for a no-op script.

Uses pytest-benchmark when available (CI), falls back to a wall-clock assertion
so the test still passes in environments without the benchmark plugin.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from shekel._cli import cli


@pytest.fixture
def noop_script(tmp_path: Path) -> Path:
    p = tmp_path / "noop.py"
    p.write_text("pass")
    return p


def _run_once(noop_script: Path) -> float:
    runner = CliRunner()
    t0 = time.perf_counter()
    result = runner.invoke(cli, ["run", str(noop_script)])
    elapsed = time.perf_counter() - t0
    assert result.exit_code == 0
    return elapsed


def test_run_overhead_under_100ms(noop_script: Path) -> None:
    """shekel run on a no-op script must complete in under 100 ms (wall clock)."""
    # Warm-up: first call may pay import costs
    _run_once(noop_script)
    # Measure: take the minimum of 5 runs to reduce noise
    times = [_run_once(noop_script) for _ in range(5)]
    best = min(times)
    assert best < 0.1, f"shekel run overhead too high: best={best*1000:.1f} ms (limit 100 ms)"


def test_run_overhead_benchmark(benchmark: pytest.fixture, noop_script: Path) -> None:  # type: ignore[type-arg]
    """Benchmark version — only runs when pytest-benchmark is active."""
    runner = CliRunner()

    def _invoke() -> None:
        result = runner.invoke(cli, ["run", str(noop_script)])
        assert result.exit_code == 0

    benchmark(_invoke)
