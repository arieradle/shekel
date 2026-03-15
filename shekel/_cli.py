from __future__ import annotations

import os
import runpy
import sys

try:
    import click
except ImportError:  # pragma: no cover
    raise SystemExit("shekel CLI requires click. Install with: pip install shekel[cli]")

from shekel._pricing import _PRICES, calculate_cost


@click.group()
def cli() -> None:
    """shekel — LLM cost tracking and budget enforcement."""


@cli.command()
@click.option("--model", required=True, help="Model name (e.g. gpt-4o, claude-3-5-sonnet-20241022)")
@click.option("--input-tokens", required=True, type=int, help="Number of input tokens")
@click.option("--output-tokens", required=True, type=int, help="Number of output tokens")
def estimate(model: str, input_tokens: int, output_tokens: int) -> None:
    """Estimate the cost of an API call without making one."""
    cost = calculate_cost(model, input_tokens, output_tokens)
    click.echo(f"Model:         {model}")
    click.echo(f"Input tokens:  {input_tokens:,}")
    click.echo(f"Output tokens: {output_tokens:,}")
    click.echo(f"Estimated cost: ${cost:.6f}")


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["openai", "anthropic", "google"], case_sensitive=False),
    default=None,
    help="Filter by provider",
)
def models(provider: str | None) -> None:
    """List bundled models and their pricing."""
    provider_prefixes = {
        "openai": ("gpt-", "o1", "o3"),
        "anthropic": ("claude-",),
        "google": ("gemini-",),
    }

    rows = []
    for name, entry in _PRICES.items():
        if provider is not None:
            prefixes = provider_prefixes.get(provider.lower(), ())
            if not any(name.startswith(p) for p in prefixes):
                continue
        rows.append((name, entry["input_per_1k"], entry["output_per_1k"]))

    if not rows:
        click.echo("No models found.")
        return

    col1 = max(len(r[0]) for r in rows)
    header = f"{'Model':<{col1}}  {'Input/1k':>12}  {'Output/1k':>12}"
    click.echo(header)
    click.echo("-" * len(header))
    for name, inp, out in rows:
        click.echo(f"{name:<{col1}}  ${inp:>11.6f}  ${out:>11.6f}")


@cli.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("script")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.option(
    "--budget", "max_usd", type=float, default=None, help="Max spend in USD (maps to max_usd)."
)
@click.option(
    "--warn-at", type=float, default=None, help="Warn fraction 0.0–1.0 (maps to warn_at)."
)
@click.option(
    "--max-llm-calls", type=int, default=None, help="Cap on LLM API calls (maps to max_llm_calls)."
)
@click.option(
    "--max-tool-calls",
    type=int,
    default=None,
    help="Cap on tool invocations (maps to max_tool_calls).",
)
@click.option(
    "--fallback-model",
    type=str,
    default=None,
    help="Fallback model name (maps to fallback['model']).",
)
@click.option(
    "--fallback-at",
    type=float,
    default=0.8,
    show_default=True,
    help="Fallback activation threshold 0.0–1.0 (maps to fallback['at_pct']).",
)
@click.option(
    "--output",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--warn-only",
    is_flag=True,
    default=False,
    help="Never exit 1; warn but continue when budget exceeded.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Track costs without enforcement. Implies --warn-only.",
)
@click.option(
    "--budget-file", type=str, default=None, help="Path to TOML budget config file (shekel.toml)."
)
def run(
    script: str,
    args: tuple[str, ...],
    max_usd: float | None,
    warn_at: float | None,
    max_llm_calls: int | None,
    max_tool_calls: int | None,
    fallback_model: str | None,
    fallback_at: float,
    output: str,
    warn_only: bool,
    dry_run: bool,
    budget_file: str | None,
) -> None:
    """Run a Python script with budget enforcement. No code changes required.

    Equivalent to wrapping your script in ``with budget(max_usd=N):``.
    Exits with code 1 if the budget is exceeded (CI-friendly).

    \b
    Examples:
      shekel run agent.py --budget 5
      shekel run agent.py --budget 5 --warn-at 0.8
      shekel run agent.py --max-llm-calls 20
      shekel run agent.py --budget 5 --output json
      shekel run agent.py --budget 5 --warn-only
      shekel run agent.py --budget 5 --dry-run
      shekel run agent.py --budget-file shekel.toml
      AGENT_BUDGET_USD=5 shekel run agent.py
    """
    import json as _json

    from shekel import budget as make_budget
    from shekel._run_utils import detect_patched_providers, format_spend_summary
    from shekel.exceptions import BudgetExceededError, ToolBudgetExceededError

    # --dry-run implies --warn-only
    if dry_run:
        warn_only = True

    # Load budget file if specified (CLI flags take precedence)
    file_kwargs: dict[str, object] = {}
    if budget_file is not None:
        from shekel._run_config import load_budget_file

        try:
            file_kwargs = load_budget_file(budget_file)
        except FileNotFoundError:
            click.echo(f"shekel: budget file not found: {budget_file}", err=True)
            sys.exit(2)
        except Exception as exc:
            click.echo(f"shekel: invalid budget file — {exc}", err=True)
            sys.exit(2)

    # Env var fallback for --budget
    if max_usd is None:
        env_val = os.environ.get("AGENT_BUDGET_USD")
        if env_val is not None:
            try:
                max_usd = float(env_val)
            except ValueError:
                click.echo(
                    f"shekel: invalid AGENT_BUDGET_USD={env_val!r} — must be a number",
                    err=True,
                )
                sys.exit(1)

    # Build budget kwargs: file values first, then explicit CLI flags override
    budget_kwargs: dict[str, object] = {"name": "shekel-run", **file_kwargs}
    if max_usd is not None:
        budget_kwargs["max_usd"] = max_usd
    if warn_at is not None:
        budget_kwargs["warn_at"] = warn_at
    if max_llm_calls is not None:
        budget_kwargs["max_llm_calls"] = max_llm_calls
    if max_tool_calls is not None:
        budget_kwargs["max_tool_calls"] = max_tool_calls
    if fallback_model is not None:
        budget_kwargs["fallback"] = {"model": fallback_model, "at_pct": fallback_at}
    if warn_only:
        budget_kwargs["warn_only"] = True

    has_limit = (
        budget_kwargs.get("max_usd") is not None
        or budget_kwargs.get("max_llm_calls") is not None
        or budget_kwargs.get("max_tool_calls") is not None
    )

    original_argv = sys.argv[:]
    sys.argv = [script, *args]

    script_exit_code = 0
    exceeded = False
    b = make_budget(**budget_kwargs)  # type: ignore[arg-type]
    try:
        with b:
            if dry_run and output == "text":
                click.echo("[dry-run] cost tracking only — budget limits will not be enforced")
            if output == "text":
                providers = detect_patched_providers()
                if providers:
                    click.echo(f"Patching: {', '.join(providers)}")
            runpy.run_path(script, run_name="__main__")
    except BudgetExceededError as exc:
        exceeded = True
        if output == "text":
            if warn_only:
                click.echo(
                    f"⚠ Budget limit reached (warn-only): {exc.model}"
                    f" · ${exc.spent:.4f} / ${exc.limit:.2f}",
                    err=True,
                )
            else:
                click.echo(
                    f"✗ Budget exceeded: {exc.model} · {b.calls_used} calls"
                    f" · ${exc.spent:.4f} / ${exc.limit:.2f}",
                    err=True,
                )
        if not warn_only:
            script_exit_code = 1
    except ToolBudgetExceededError as exc:
        exceeded = True
        if output == "text":
            limit_str = str(exc.calls_limit) if exc.calls_limit is not None else "∞"
            if warn_only:
                click.echo(
                    f"⚠ Tool limit reached (warn-only): {exc.tool_name}"
                    f" · {exc.calls_used}/{limit_str} calls",
                    err=True,
                )
            else:
                click.echo(
                    f"✗ Tool budget exceeded: {exc.tool_name}"
                    f" · {exc.calls_used}/{limit_str} calls",
                    err=True,
                )
        if not warn_only:
            script_exit_code = 1
    except FileNotFoundError:
        click.echo(f"shekel: script not found: {script}", err=True)
        script_exit_code = 2
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            script_exit_code = code
        elif code is None:
            script_exit_code = 0
        else:
            script_exit_code = 1
    finally:
        sys.argv = original_argv
        # Determine status for both text and JSON output
        if exceeded or (has_limit and b.max_usd is not None and b.spent > b.max_usd):
            status = "exceeded"
        elif b._warn_fired:
            status = "warn"
        else:
            status = "ok"

        if output == "json":
            data = b.summary_data()
            by_model: dict[str, object] = data["by_model"]  # type: ignore[assignment]
            json_out: dict[str, object] = {
                "spent": data["total_spent"],
                "limit": data["limit"],
                "calls": data["calls_used"],
                "tool_calls": data["tool_calls_used"],
                "status": status,
            }
            if by_model:
                top_model = max(
                    by_model.items(),
                    key=lambda kv: kv[1]["calls"],  # type: ignore[index]
                )[0]
                json_out["model"] = top_model
            click.echo(_json.dumps(json_out))
        else:
            click.echo(format_spend_summary(b))
            if has_limit and b.calls_used == 0 and b.tool_calls_used == 0:
                click.echo(
                    "Warning: 0 LLM calls intercepted — budget may not be enforced.",
                    err=True,
                )

    sys.exit(script_exit_code)
