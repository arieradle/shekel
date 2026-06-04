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


def test_models_invalid_provider(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["models", "--provider", "invalid"])
    assert result.exit_code != 0


def test_models_no_results(runner: CliRunner) -> None:
    from unittest.mock import patch

    with patch("shekel._cli._PRICES", {}):
        result = runner.invoke(cli, ["models"])
    assert result.exit_code == 0
    assert "No models found" in result.output


# ---------------------------------------------------------------------------
# SHEK-5: shekel tenants command
# ---------------------------------------------------------------------------


def test_tenants_no_redis_url_exits_nonzero(runner: CliRunner) -> None:
    """Missing REDIS_URL and no --redis-url exits 1 with error message."""
    import os
    from unittest.mock import patch

    env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(cli, ["tenants", "--name", "api"])
    assert result.exit_code != 0
    assert "Redis URL required" in result.output


def test_tenants_table_output(runner: CliRunner) -> None:
    """shekel tenants prints a table with TENANT, SPENT, LIMIT, USED% columns."""
    from unittest.mock import MagicMock, patch

    mock_backend = MagicMock()
    mock_backend.list_tenants.return_value = ["user-1", "user-2"]
    mock_backend.get_tenant_spend.side_effect = lambda name, tenant_id: (
        0.08 if tenant_id == "user-1" else 0.03
    )
    mock_backend.get_tenant_limit.side_effect = lambda name, tenant_id: 0.10

    with patch("shekel.backends.redis.RedisBackend", return_value=mock_backend):
        result = runner.invoke(
            cli, ["tenants", "--name", "api", "--redis-url", "redis://localhost"]
        )

    assert result.exit_code == 0
    assert "TENANT" in result.output
    assert "SPENT" in result.output
    assert "LIMIT" in result.output
    assert "user-1" in result.output
    assert "user-2" in result.output


def test_tenants_json_output(runner: CliRunner) -> None:
    """shekel tenants --output json prints valid JSON array."""
    import json
    from unittest.mock import MagicMock, patch

    mock_backend = MagicMock()
    mock_backend.list_tenants.return_value = ["user-1"]
    mock_backend.get_tenant_spend.return_value = 0.05
    mock_backend.get_tenant_limit.return_value = 0.10

    with patch("shekel.backends.redis.RedisBackend", return_value=mock_backend):
        result = runner.invoke(
            cli,
            ["tenants", "--name", "api", "--redis-url", "redis://localhost", "--output", "json"],
        )

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert isinstance(rows, list)
    assert rows[0]["tenant_id"] == "user-1"
    assert rows[0]["spent"] == pytest.approx(0.05)
    assert rows[0]["limit"] == pytest.approx(0.10)
    assert rows[0]["utilization"] == pytest.approx(0.50)


def test_tenants_no_limit_shows_dash(runner: CliRunner) -> None:
    """Tenant with no stored limit shows — in LIMIT and USED% columns."""
    from unittest.mock import MagicMock, patch

    mock_backend = MagicMock()
    mock_backend.list_tenants.return_value = ["user-x"]
    mock_backend.get_tenant_spend.return_value = 0.12
    mock_backend.get_tenant_limit.return_value = None

    with patch("shekel.backends.redis.RedisBackend", return_value=mock_backend):
        result = runner.invoke(
            cli, ["tenants", "--name", "api", "--redis-url", "redis://localhost"]
        )

    assert result.exit_code == 0
    assert "—" in result.output


def test_tenants_json_null_limit(runner: CliRunner) -> None:
    """JSON output has null for limit/utilization when no limit stored."""
    import json
    from unittest.mock import MagicMock, patch

    mock_backend = MagicMock()
    mock_backend.list_tenants.return_value = ["user-x"]
    mock_backend.get_tenant_spend.return_value = 0.12
    mock_backend.get_tenant_limit.return_value = None

    with patch("shekel.backends.redis.RedisBackend", return_value=mock_backend):
        result = runner.invoke(
            cli,
            ["tenants", "--name", "api", "--redis-url", "redis://localhost", "--output", "json"],
        )

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert rows[0]["limit"] is None
    assert rows[0]["utilization"] is None


def test_tenants_redis_unreachable_exits_nonzero(runner: CliRunner) -> None:
    """list_tenants raising an exception prints an error and exits non-zero."""
    from unittest.mock import MagicMock, patch

    mock_backend = MagicMock()
    mock_backend.list_tenants.side_effect = RuntimeError("connection refused")

    with patch("shekel.backends.redis.RedisBackend", return_value=mock_backend):
        result = runner.invoke(
            cli, ["tenants", "--name", "api", "--redis-url", "redis://localhost"]
        )

    assert result.exit_code != 0
    assert "Redis unreachable" in result.output
