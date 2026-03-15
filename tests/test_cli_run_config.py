from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from shekel._cli import cli
from shekel.exceptions import BudgetExceededError


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


@pytest.fixture
def budget_toml(tmp_path: Path):
    def _make(content: str) -> Path:
        p = tmp_path / "shekel.toml"
        p.write_text(content)
        return p

    return _make


# ---------------------------------------------------------------------------
# Story 10: --budget-file shekel.toml
# ---------------------------------------------------------------------------


def test_budget_file_loaded_max_usd(runner: CliRunner, script, budget_toml) -> None:
    s = script("pass")
    cfg = budget_toml("[budget]\nmax_usd = 5.0\n")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code == 0


def test_budget_file_loaded_warn_at(runner: CliRunner, script, budget_toml) -> None:
    s = script("pass")
    cfg = budget_toml("[budget]\nmax_usd = 5.0\nwarn_at = 0.8\n")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code == 0


def test_budget_file_loaded_max_llm_calls(runner: CliRunner, script, budget_toml) -> None:
    s = script("pass")
    cfg = budget_toml("[budget]\nmax_llm_calls = 20\n")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code == 0


def test_budget_file_loaded_max_tool_calls(runner: CliRunner, script, budget_toml) -> None:
    s = script("pass")
    cfg = budget_toml("[budget]\nmax_tool_calls = 50\n")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code == 0


def test_budget_file_not_found_exits_with_error(runner: CliRunner, script) -> None:
    s = script("pass")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", "/nonexistent/shekel.toml"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "no such" in result.output.lower()


def test_budget_file_invalid_toml_exits_with_error(runner: CliRunner, script, budget_toml) -> None:
    s = script("pass")
    cfg = budget_toml("this is not [ valid toml !!!")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code != 0
    assert "invalid" in result.output.lower() or "toml" in result.output.lower()


def test_budget_flag_overrides_file_max_usd(runner: CliRunner, script, budget_toml) -> None:
    """--budget CLI flag takes precedence over max_usd in config file."""
    s = script("pass")
    cfg = budget_toml("[budget]\nmax_usd = 10.0\n")
    exc = BudgetExceededError(spent=2.0, limit=1.0, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget", "1", "--budget-file", str(cfg)])
    # --budget 1 wins over file's max_usd=10; script exceeds $1 cap
    assert result.exit_code == 1


def test_budget_file_missing_budget_section_is_ok(runner: CliRunner, script, budget_toml) -> None:
    """A TOML file with no [budget] section is valid — just no budget constraints."""
    s = script("pass")
    cfg = budget_toml("[other_section]\nfoo = 'bar'\n")
    result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code == 0


def test_budget_file_enforces_limit(runner: CliRunner, script, budget_toml) -> None:
    """Budget from file is actually enforced."""
    s = script("pass")
    cfg = budget_toml("[budget]\nmax_usd = 1.0\n")
    exc = BudgetExceededError(spent=2.0, limit=1.0, model="gpt-4o")
    with patch("runpy.run_path", side_effect=exc):
        result = runner.invoke(cli, ["run", str(s), "--budget-file", str(cfg)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# load_budget_file unit tests (_run_config)
# ---------------------------------------------------------------------------


def test_load_budget_file_returns_empty_for_no_section(tmp_path: Path) -> None:
    from shekel._run_config import load_budget_file

    f = tmp_path / "shekel.toml"
    f.write_text("[other]\nfoo = 1\n")
    result = load_budget_file(str(f))
    assert result == {}


def test_load_budget_file_parses_all_keys(tmp_path: Path) -> None:
    from shekel._run_config import load_budget_file

    f = tmp_path / "shekel.toml"
    f.write_text(
        "[budget]\nmax_usd = 5.0\nwarn_at = 0.8\nmax_llm_calls = 20\nmax_tool_calls = 50\n"
    )
    result = load_budget_file(str(f))
    assert result["max_usd"] == pytest.approx(5.0)
    assert result["warn_at"] == pytest.approx(0.8)
    assert result["max_llm_calls"] == 20
    assert result["max_tool_calls"] == 50


def test_load_budget_file_file_not_found_raises(tmp_path: Path) -> None:
    from shekel._run_config import load_budget_file

    with pytest.raises(FileNotFoundError):
        load_budget_file(str(tmp_path / "missing.toml"))
