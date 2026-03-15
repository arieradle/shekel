from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from shekel._cli import cli
from shekel.exceptions import BudgetExceededError, ToolBudgetExceededError


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def script(tmp_path: Path):
    def _make(content: str, name: str = "agent.py") -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    return _make


# ---------------------------------------------------------------------------
# Story 8: --output json
# ---------------------------------------------------------------------------


def test_output_json_emits_valid_json(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--output", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_output_json_contains_required_keys(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--output", "json"])
    data = json.loads(result.output)
    for key in ("spent", "limit", "calls", "tool_calls", "status"):
        assert key in data, f"missing key: {key}"


def test_output_json_ok_status_on_normal_exit(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget", "5", "--output", "json"])
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["limit"] == pytest.approx(5.0)


def test_output_json_no_limit_when_no_budget_flag(runner: CliRunner, script, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BUDGET_USD", raising=False)
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--output", "json"])
    data = json.loads(result.output)
    assert data["limit"] is None


def test_output_json_exceeded_status_on_budget_exceeded(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1", "--output", "json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "exceeded"


def test_output_json_hides_human_spend_summary(runner: CliRunner, script) -> None:
    """In JSON mode, the human 'spent · calls' line should not appear."""
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--output", "json"])
    assert "spent" not in result.output.replace('"spent"', "")  # only JSON key, not label


def test_output_json_with_model_field(runner: CliRunner, script) -> None:
    """When LLM calls are recorded, model field appears in JSON."""
    s = script("pass")
    from shekel._budget import Budget, CallRecord

    original_init = Budget.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        self._calls.append(
            CallRecord(model="claude-3-5-sonnet", cost=0.02, input_tokens=100, output_tokens=50)
        )
        self._calls_made = 1
        self._spent = 0.02

    with patch.object(Budget, "__init__", patched_init):
        result = runner.invoke(cli, ["run", str(s), "--output", "json"])
    data = json.loads(result.output)
    assert data.get("model") == "claude-3-5-sonnet"


# ---------------------------------------------------------------------------
# Story 11: --warn-only
# ---------------------------------------------------------------------------


def test_warn_only_exits_zero_on_budget_exceeded(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1", "--warn-only"])
    assert result.exit_code == 0


def test_warn_only_prints_warning_on_budget_exceeded(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1", "--warn-only"])
    assert "warn" in result.output.lower() or "limit" in result.output.lower()


def test_warn_only_exits_zero_on_tool_budget_exceeded(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = ToolBudgetExceededError(
        tool_name="web_search", calls_used=5, calls_limit=5, usd_spent=0.05, usd_limit=None
    )
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--max-tool-calls", "5", "--warn-only"])
    assert result.exit_code == 0


def test_warn_only_json_status_exceeded(runner: CliRunner, script) -> None:
    """In warn-only + json mode, status should reflect that budget was exceeded."""
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(
            cli, ["run", str(s), "--budget", "1", "--warn-only", "--output", "json"]
        )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "exceeded"


# ---------------------------------------------------------------------------
# Story 9: --dry-run
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget", "5", "--dry-run"])
    assert result.exit_code == 0


def test_dry_run_prints_dry_run_indicator(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget", "5", "--dry-run"])
    assert "dry-run" in result.output.lower() or "dry run" in result.output.lower()


def test_dry_run_exits_zero_even_when_budget_would_be_exceeded(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1", "--dry-run"])
    assert result.exit_code == 0


def test_dry_run_implies_warn_only(runner: CliRunner, script) -> None:
    """--dry-run + budget exceeded should not exit 1."""
    s = script("pass")
    exc = BudgetExceededError(spent=99.0, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1", "--dry-run"])
    assert result.exit_code == 0


def test_output_json_warn_status_when_warn_threshold_fired(runner: CliRunner, script) -> None:
    """JSON status is 'warn' when warn_at threshold fired but budget not exceeded."""
    import json as _json

    s = script("pass")
    from shekel._budget import Budget

    original_init = Budget.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        self._warn_fired = True  # simulate warn threshold fired

    with patch.object(Budget, "__init__", patched_init):
        result = runner.invoke(cli, ["run", str(s), "--budget", "5", "--output", "json"])
    data = _json.loads(result.output)
    assert data["status"] == "warn"
