# Requires: pip install shekel[openai]
"""
Temporal budget: simulated API gateway with per-user hourly spend limits.

Models a realistic scenario where multiple concurrent users share an API
gateway that enforces a $0.02/hr per-user rolling window. Uses asyncio
to simulate concurrent requests and demonstrates:

- Shared InMemoryBackend across users
- Graceful 429 responses with Retry-After
- Window reset (visible when you mock time or wait)
- Mixed free/pro tier enforcement
"""

import asyncio
import os
from dataclasses import dataclass

from shekel import BudgetExceededError
from shekel._temporal import InMemoryBackend, TemporalBudget

# ---------------------------------------------------------------------------
# Gateway config
# ---------------------------------------------------------------------------

FREE_LIMIT_USD = 0.005  # $0.005/hr for free tier
PRO_LIMIT_USD = 0.05  # $0.05/hr for pro tier
WINDOW_SECONDS = 3600  # 1-hour rolling window

# One shared backend — all user window state lives here
_backend = InMemoryBackend()


@dataclass
class GatewayResponse:
    status: int  # 200 OK or 429 Too Many Requests
    body: str
    retry_after: float | None = None
    window_spent: float | None = None


def _get_budget(user_id: str, is_pro: bool) -> TemporalBudget:
    max_usd = PRO_LIMIT_USD if is_pro else FREE_LIMIT_USD
    return TemporalBudget(
        max_usd=max_usd,
        window_seconds=WINDOW_SECONDS,
        name=f"user:{user_id}",
        backend=_backend,
    )


async def handle_request(
    client,
    user_id: str,
    is_pro: bool,
    prompt: str,
) -> GatewayResponse:
    """Simulate a gateway request with per-user rolling-window enforcement."""
    user_budget = _get_budget(user_id, is_pro)
    tier = "pro" if is_pro else "free"

    try:
        async with user_budget:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=30,
            )
        text = response.choices[0].message.content or ""
        return GatewayResponse(status=200, body=text)

    except BudgetExceededError as e:
        body = (
            f"Rate limit exceeded for {tier} tier. "
            f"Window spend: ${e.window_spent:.4f}. "
            f"Retry after {e.retry_after:.0f}s."
            if e.retry_after is not None
            else f"Budget exhausted (${e.spent:.4f} spent)."
        )
        return GatewayResponse(
            status=429,
            body=body,
            retry_after=e.retry_after,
            window_spent=e.window_spent,
        )


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


async def simulate(client) -> None:
    print("=== API Gateway — per-user rolling-window enforcement ===\n")
    print(f"Free tier limit : ${FREE_LIMIT_USD:.3f}/hr")
    print(f"Pro  tier limit : ${PRO_LIMIT_USD:.3f}/hr")
    print(f"Window          : {WINDOW_SECONDS}s\n")

    users = [
        # (user_id, is_pro, prompt)
        ("alice", False, "What is Python? One sentence."),
        ("bob", True, "What is Rust? One sentence."),
        ("alice", False, "What is Go? One sentence."),  # alice's second request
        ("carol", True, "What is Julia? One sentence."),
        ("alice", False, "What is Zig? One sentence."),  # alice may be near limit
        ("bob", True, "What is Elixir? One sentence."),
        ("alice", False, "What is Haskell? One sentence."),  # alice likely over limit
    ]

    tasks = [handle_request(client, user_id, is_pro, prompt) for user_id, is_pro, prompt in users]

    results = await asyncio.gather(*tasks)

    for (user_id, is_pro, prompt), resp in zip(users, results):
        tier = "pro " if is_pro else "free"
        status_str = "200 OK " if resp.status == 200 else "429    "
        print(f"  [{tier}] {user_id:<6} {status_str}  {prompt[:30]!r}...")
        if resp.status == 200:
            print(f"           → {resp.body}")
        else:
            print(f"           → {resp.body}")
        print()

    print("Window state (final):")
    for user_id in {"alice", "bob", "carol"}:
        spent, _ = _backend.get_state(f"user:{user_id}")
        print(f"  user:{user_id}  ${spent:.4f} accumulated this window")


async def main() -> None:
    try:
        import openai
    except ImportError:
        print("Run: pip install shekel[openai]")
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY to run this demo.")
        return

    client = openai.AsyncOpenAI(api_key=api_key)
    await simulate(client)


if __name__ == "__main__":
    asyncio.run(main())
