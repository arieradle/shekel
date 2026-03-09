from __future__ import annotations

import pytest
from click.testing import CliRunner

from shekel._cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# estimate
# ---------------------------------------------------------------------------


def test_estimate_known_model(runner: CliRunner) -> None:
    result = runner.invoke(
        cli, ["estimate", "--model", "gpt-4o", "--input-tokens", "1000", "--output-tokens", "500"]
    )
    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "$" in result.output
    assert "1,000" in result.output
    assert "500" in result.output


def test_estimate_versioned_model_name(runner: CliRunner) -> None:
    # "gpt-4o-2024-08-06" should resolve via prefix to gpt-4o pricing
    result = runner.invoke(
        cli,
        [
            "estimate",
            "--model",
            "gpt-4o-2024-08-06",
            "--input-tokens",
            "1000",
            "--output-tokens",
            "1000",
        ],
    )
    assert result.exit_code == 0
    assert "$" in result.output


def test_estimate_anthropic_model(runner: CliRunner) -> None:
    result = runner.invoke(
        cli,
        [
            "estimate",
            "--model",
            "claude-3-haiku-20240307",
            "--input-tokens",
            "500",
            "--output-tokens",
            "200",
        ],
    )
    assert result.exit_code == 0
    assert "claude-3-haiku-20240307" in result.output


def test_estimate_missing_model_arg(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["estimate", "--input-tokens", "1000", "--output-tokens", "500"])
    assert result.exit_code != 0
    assert "model" in result.output.lower()


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


def test_models_lists_all(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["models"])
    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "claude-3-5-sonnet" in result.output
    assert "gemini" in result.output


def test_models_filter_openai(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["models", "--provider", "openai"])
    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "claude" not in result.output


def test_models_filter_anthropic(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["models", "--provider", "anthropic"])
    assert result.exit_code == 0
    assert "claude" in result.output
    assert "gpt" not in result.output


def test_models_filter_google(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["models", "--provider", "google"])
    assert result.exit_code == 0
    assert "gemini" in result.output
    assert "gpt" not in result.output
