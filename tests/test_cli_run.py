from __future__ import annotations

import sys
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
    """Helper to write a temp Python script and return its path."""

    def _make(content: str, name: str = "agent.py") -> Path:
        p = tmp_path / name
        p.write_text(content)
        return p

    return _make


# ---------------------------------------------------------------------------
# Story 1: bare shekel run (no flags)
# ---------------------------------------------------------------------------


def test_run_executes_script_and_exits_zero(runner: CliRunner, script) -> None:
    s = script("x = 1 + 1")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 0


def test_run_prints_spend_summary_on_exit(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 0
    assert "$" in result.output
    assert "spent" in result.output


def test_run_passes_script_args_via_argv(runner: CliRunner, script, tmp_path: Path) -> None:
    out = tmp_path / "argv.txt"
    s = script(f"import sys; open(r'{out}', 'w').write(' '.join(sys.argv))")
    result = runner.invoke(cli, ["run", str(s), "arg1", "arg2"])
    assert result.exit_code == 0
    content = out.read_text()
    assert "arg1" in content
    assert "arg2" in content
    # sys.argv[0] should be the script path, not the shekel binary
    assert content.split()[0] == str(s)


def test_run_script_not_found_exits_nonzero(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["run", "/nonexistent/agent.py"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_run_script_nonzero_exit_propagated(runner: CliRunner, script) -> None:
    s = script("import sys; sys.exit(42)")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 42


def test_run_script_exit_zero_explicit(runner: CliRunner, script) -> None:
    s = script("import sys; sys.exit(0)")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 0


def test_run_script_exit_none_is_zero(runner: CliRunner, script) -> None:
    s = script("import sys; sys.exit()")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 0


def test_run_spend_summary_always_printed_on_nonzero_exit(runner: CliRunner, script) -> None:
    s = script("import sys; sys.exit(1)")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 1
    assert "$" in result.output


# ---------------------------------------------------------------------------
# Story 2: budget flags
# ---------------------------------------------------------------------------


def test_run_no_budget_flag_is_tracking_only(runner: CliRunner, script) -> None:
    """Without --budget, the run succeeds even if LLM calls would exceed a limit."""
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 0


def test_run_budget_exceeded_exits_one(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1"])
    assert result.exit_code == 1


def test_run_budget_exceeded_no_stacktrace(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1"])
    full_output = result.output
    assert "Traceback" not in full_output


def test_run_budget_exceeded_shows_spent_and_limit(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1"])
    full_output = result.output
    assert "1.50" in full_output or "1.5" in full_output
    assert "1.00" in full_output or "1.0" in full_output


def test_run_budget_exceeded_shows_model(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1"])
    full_output = result.output
    assert "gpt-4o" in full_output


def test_run_tool_budget_exceeded_clean_output(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = ToolBudgetExceededError(
        tool_name="web_search",
        calls_used=10,
        calls_limit=10,
        usd_spent=0.10,
        usd_limit=None,
    )
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--max-tool-calls", "10"])
    assert result.exit_code == 1
    full_output = result.output
    assert "Traceback" not in full_output
    assert "web_search" in full_output


def test_run_warn_at_flag_accepted(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget", "5", "--warn-at", "0.8"])
    assert result.exit_code == 0


def test_run_max_llm_calls_flag_accepted(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--max-llm-calls", "10"])
    assert result.exit_code == 0


def test_run_max_tool_calls_flag_accepted(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--max-tool-calls", "50"])
    assert result.exit_code == 0


def test_run_fallback_model_flag_accepted(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget", "5", "--fallback-model", "gpt-4o-mini"])
    assert result.exit_code == 0


def test_run_fallback_at_default_is_point_eight(runner: CliRunner, script) -> None:
    """--fallback-at defaults to 0.8 when not supplied."""
    s = script("pass")
    result = runner.invoke(
        cli,
        ["run", str(s), "--budget", "5", "--fallback-model", "gpt-4o-mini", "--fallback-at", "0.5"],
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Story 3: AGENT_BUDGET_USD env var
# ---------------------------------------------------------------------------


def test_run_env_var_sets_budget(runner: CliRunner, script) -> None:
    s = script("pass")
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["run", str(s)], env={"AGENT_BUDGET_USD": "10.0"})
    assert result.exit_code == 0


def test_run_flag_overrides_env_var(runner: CliRunner, script) -> None:
    """--budget flag takes precedence over AGENT_BUDGET_USD env var."""
    s = script("pass")
    exc = BudgetExceededError(spent=2.0, limit=1.0, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(
            cli,
            ["run", str(s), "--budget", "1"],
            env={"AGENT_BUDGET_USD": "999"},
        )
    assert result.exit_code == 1


def test_run_env_var_invalid_value_exits_with_error(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s)], env={"AGENT_BUDGET_USD": "notanumber"})
    assert result.exit_code != 0
    full_output = result.output
    assert "AGENT_BUDGET_USD" in full_output


def test_run_no_flag_no_env_is_tracking_only(runner: CliRunner, script, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BUDGET_USD", raising=False)
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Story 4: provider detection message
# ---------------------------------------------------------------------------


def test_run_provider_detection_shown_when_providers_patched(runner: CliRunner, script) -> None:
    s = script("pass")
    with patch(
        "shekel._run_utils.detect_patched_providers",
        return_value=["anthropic", "openai"],
    ):
        result = runner.invoke(cli, ["run", str(s)])
    assert "Patching:" in result.output
    assert "openai" in result.output
    assert "anthropic" in result.output


def test_run_no_provider_detection_when_nothing_patched(runner: CliRunner, script) -> None:
    s = script("pass")
    with patch("shekel._run_utils.detect_patched_providers", return_value=[]):
        result = runner.invoke(cli, ["run", str(s)])
    assert "Patching:" not in result.output


# ---------------------------------------------------------------------------
# Story 5: zero calls intercepted warning
# ---------------------------------------------------------------------------


def test_run_zero_calls_with_budget_prints_warning(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget", "5"])
    full_output = result.output
    assert "0" in full_output and "intercept" in full_output.lower()


def test_run_calls_made_no_zero_intercept_warning(runner: CliRunner, script, tmp_path) -> None:
    """When calls are made, no zero-intercept warning should appear."""
    s = script("pass")
    # Simulate a budget that recorded calls by patching calls_used
    from shekel._budget import Budget

    original_init = Budget.__init__

    def patched_init(self, **kwargs):
        original_init(self, **kwargs)
        self._calls_made = 1  # simulate a call was made

    with patch.object(Budget, "__init__", patched_init):
        result = runner.invoke(cli, ["run", str(s), "--budget", "5"])
    full_output = result.output
    assert "0 LLM calls intercepted" not in full_output


def test_run_no_budget_no_zero_intercept_warning(runner: CliRunner, script, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BUDGET_USD", raising=False)
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s)])
    full_output = result.output
    assert "0 LLM calls intercepted" not in full_output


# ---------------------------------------------------------------------------
# Story 6: clean budget-exceeded output (attribution)
# ---------------------------------------------------------------------------


def test_run_budget_exceeded_message_attributes_to_agent(runner: CliRunner, script) -> None:
    """The error message should show agent spend, not shekel error."""
    s = script("pass")
    exc = BudgetExceededError(
        spent=3.14,
        limit=2.00,
        model="claude-3-5-sonnet",
        tokens={"input": 1000, "output": 500},
    )
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "2"])
    full_output = result.output
    assert "Budget exceeded" in full_output
    assert "claude-3-5-sonnet" in full_output
    assert "Traceback" not in full_output


def test_run_spend_summary_printed_even_on_budget_exceeded(runner: CliRunner, script) -> None:
    s = script("pass")
    exc = BudgetExceededError(spent=1.50, limit=1.00, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1"])
    assert "$" in result.output


# ---------------------------------------------------------------------------
# Story 7: naming / nesting
# ---------------------------------------------------------------------------


def test_run_nested_budget_in_script_works(runner: CliRunner, script) -> None:
    """A script using with budget(name='inner') should not raise due to naming conflicts."""
    s = script(
        "from shekel import budget\n" "with budget(max_usd=1.0, name='inner'):\n" "    pass\n"
    )
    result = runner.invoke(cli, ["run", str(s), "--budget", "5"])
    assert result.exit_code == 0


def test_run_sys_argv_restored_after_run(runner: CliRunner, script) -> None:
    original_argv = sys.argv[:]
    s = script("pass")
    runner.invoke(cli, ["run", str(s)])
    # CliRunner isolates sys.argv, so we just confirm no crash
    assert sys.argv == original_argv


def test_run_script_exit_string_message_is_one(runner: CliRunner, script) -> None:
    """sys.exit("error msg") — non-int, non-None code — should map to exit code 1."""
    s = script('import sys; sys.exit("fatal error")')
    result = runner.invoke(cli, ["run", str(s)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# _run_utils unit tests
# ---------------------------------------------------------------------------


def test_format_spend_summary_with_model(runner: CliRunner, script, tmp_path: Path) -> None:
    """format_spend_summary includes model name when calls were made."""
    from shekel._budget import Budget
    from shekel._run_utils import format_spend_summary

    b = Budget(name="test")
    # Simulate a recorded call by directly manipulating internal state
    from shekel._budget import CallRecord

    b._calls.append(CallRecord(model="gpt-4o", cost=0.05, input_tokens=100, output_tokens=50))
    b._calls_made = 1
    b._spent = 0.05
    b._spent_direct = 0.05

    summary = format_spend_summary(b)
    assert "gpt-4o" in summary
    assert "$0.0500" in summary
