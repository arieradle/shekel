from __future__ import annotations

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
