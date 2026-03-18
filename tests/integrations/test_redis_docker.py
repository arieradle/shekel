"""Docker-based Redis integration tests for RedisBackend and AsyncRedisBackend.

Spins up a real ``redis:alpine`` container to verify atomic enforcement,
window expiry, config mismatch detection, and the full ``budget()`` +
``RedisBackend`` flow.

Requires: Docker daemon running, ``redis`` and ``testcontainers`` packages.
Auto-skipped when either is absent or Docker is unavailable.
"""

from __future__ import annotations

import time

import pytest

testcontainers = pytest.importorskip("testcontainers", reason="testcontainers not installed")
pytest.importorskip("redis", reason="redis not installed")

from testcontainers.redis import RedisContainer  # noqa: E402

from shekel.backends.redis import AsyncRedisBackend, RedisBackend  # noqa: E402
from shekel.exceptions import BudgetConfigMismatchError, BudgetExceededError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BUDGET = "test_budget"


@pytest.fixture(scope="session")
def redis_url() -> str:  # type: ignore[return]
    """Start a redis:alpine container for the test session; yield its URL."""
    with RedisContainer(image="redis:alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(container.port)
        yield f"redis://{host}:{port}/0"


@pytest.fixture()
def backend(redis_url: str) -> RedisBackend:  # type: ignore[return]
    """Fresh RedisBackend pointing at the Docker container."""
    b = RedisBackend(url=redis_url)
    b.reset(_BUDGET)  # clean slate before each test
    yield b  # type: ignore[misc]
    b.reset(_BUDGET)
    b.close()


@pytest.fixture()
async def async_backend(redis_url: str) -> AsyncRedisBackend:  # type: ignore[return]
    """Fresh AsyncRedisBackend — pytest-asyncio manages the event loop."""
    b = AsyncRedisBackend(url=redis_url)
    await b.reset(_BUDGET)  # clean slate before each test
    yield b  # type: ignore[misc]
    await b.reset(_BUDGET)
    await b.close()


# ---------------------------------------------------------------------------
# Group A — Basic sync check-and-add
# ---------------------------------------------------------------------------


def test_sync_allowed_within_limit(backend: RedisBackend) -> None:
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 2.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is True
    assert exceeded is None


def test_sync_rejected_when_limit_exceeded(backend: RedisBackend) -> None:
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 6.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is False
    assert exceeded == "usd"


def test_sync_cumulative_spend_triggers_rejection(backend: RedisBackend) -> None:
    backend.check_and_add(_BUDGET, {"usd": 4.0}, {"usd": 5.0}, {"usd": 3600.0})
    allowed, exceeded = backend.check_and_add(_BUDGET, {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})
    assert allowed is False
    assert exceeded == "usd"


def test_sync_none_limit_never_rejected(backend: RedisBackend) -> None:
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 9999.0},
        limits={"usd": None},
        windows={"usd": 3600.0},
    )
    assert allowed is True
    assert exceeded is None


# ---------------------------------------------------------------------------
# Group B — All-or-nothing atomicity
# ---------------------------------------------------------------------------


def test_sync_all_or_nothing_second_counter_fails(backend: RedisBackend) -> None:
    """When llm_calls exceeds limit, usd must NOT be committed."""
    # Pre-fill with both counters so spec_hash is consistent across calls.
    backend.check_and_add(
        _BUDGET,
        amounts={"usd": 1.0, "llm_calls": 1.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )

    # usd would be ok (1+1=2≤5) but llm_calls would exceed (1+101=102>100).
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 1.0, "llm_calls": 101.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    assert allowed is False
    assert exceeded == "llm_calls"

    # usd must still be 1.0 — all-or-nothing means nothing was committed.
    state = backend.get_state(_BUDGET)
    assert state["usd"] == pytest.approx(1.0)
    assert state["llm_calls"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Group C — Multi-cap
# ---------------------------------------------------------------------------


def test_sync_multi_cap_both_within_limit(backend: RedisBackend) -> None:
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 0.5, "llm_calls": 1.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    assert allowed is True
    assert exceeded is None


def test_sync_multi_cap_calls_counter_rejected(backend: RedisBackend) -> None:
    backend.check_and_add(
        _BUDGET,
        amounts={"usd": 0.01, "llm_calls": 99.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 0.01, "llm_calls": 2.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    assert allowed is False
    assert exceeded == "llm_calls"


# ---------------------------------------------------------------------------
# Group D — Window expiry (real clock, short window)
# ---------------------------------------------------------------------------


def test_sync_window_resets_after_expiry(backend: RedisBackend) -> None:
    """Spend inside a 1 s window; after 1.1 s the counter resets."""
    backend.check_and_add(_BUDGET, {"usd": 4.5}, {"usd": 5.0}, {"usd": 1.0})

    time.sleep(1.5)

    # New window: 4.5 should not carry over.
    allowed, exceeded = backend.check_and_add(_BUDGET, {"usd": 4.5}, {"usd": 5.0}, {"usd": 1.0})
    assert allowed is True
    assert exceeded is None


def test_sync_per_counter_independent_windows(backend: RedisBackend) -> None:
    """usd window = 10 s, llm_calls window = 1 s.  Only calls expire."""
    backend.check_and_add(
        _BUDGET,
        amounts={"usd": 4.0, "llm_calls": 90.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 10.0, "llm_calls": 1.0},
    )

    time.sleep(1.5)

    # usd still accumulates (4.0 + 0.5 = 4.5 ≤ 5.0); calls start fresh (90 ≤ 100).
    allowed, exceeded = backend.check_and_add(
        _BUDGET,
        amounts={"usd": 0.5, "llm_calls": 90.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 10.0, "llm_calls": 1.0},
    )
    assert allowed is True
    assert exceeded is None

    state = backend.get_state(_BUDGET)
    assert state["usd"] == pytest.approx(4.5)
    assert state["llm_calls"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Group E — State & reset
# ---------------------------------------------------------------------------


def test_sync_get_state_reflects_spend(backend: RedisBackend) -> None:
    backend.check_and_add(
        _BUDGET,
        amounts={"usd": 1.23, "llm_calls": 7.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    state = backend.get_state(_BUDGET)
    assert state["usd"] == pytest.approx(1.23)
    assert state["llm_calls"] == pytest.approx(7.0)


def test_sync_reset_clears_all_counters(backend: RedisBackend) -> None:
    backend.check_and_add(_BUDGET, {"usd": 3.0}, {"usd": 5.0}, {"usd": 3600.0})
    backend.reset(_BUDGET)
    state = backend.get_state(_BUDGET)
    assert state == {}


def test_sync_get_state_empty_for_unknown_budget(backend: RedisBackend) -> None:
    state = backend.get_state("no_such_budget_xyz")
    assert state == {}


# ---------------------------------------------------------------------------
# Group F — Config mismatch
# ---------------------------------------------------------------------------


def test_config_mismatch_raises_error(backend: RedisBackend) -> None:
    """Re-using a budget name with different limits raises BudgetConfigMismatchError."""
    backend.check_and_add(_BUDGET, {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    with pytest.raises(BudgetConfigMismatchError):
        backend.check_and_add(
            _BUDGET,
            amounts={"usd": 0.01},
            limits={"usd": 10.0},  # different limit
            windows={"usd": 3600.0},
        )


# ---------------------------------------------------------------------------
# Group G — Multi-instance isolation
# ---------------------------------------------------------------------------


def test_two_budget_names_are_isolated(redis_url: str) -> None:
    b = RedisBackend(url=redis_url)
    try:
        b.reset("budget_a")
        b.reset("budget_b")

        b.check_and_add("budget_a", {"usd": 4.9}, {"usd": 5.0}, {"usd": 3600.0})

        # budget_b is fresh — should be allowed.
        allowed, exceeded = b.check_and_add("budget_b", {"usd": 4.9}, {"usd": 5.0}, {"usd": 3600.0})
        assert allowed is True

        state_a = b.get_state("budget_a")
        state_b = b.get_state("budget_b")
        assert state_a["usd"] == pytest.approx(4.9)
        assert state_b["usd"] == pytest.approx(4.9)
    finally:
        b.reset("budget_a")
        b.reset("budget_b")
        b.close()


def test_shared_name_two_backend_instances(redis_url: str) -> None:
    """Two independent RedisBackend objects share state when using the same budget name."""
    b1 = RedisBackend(url=redis_url)
    b2 = RedisBackend(url=redis_url)
    shared = "shared_budget"
    try:
        b1.reset(shared)
        b1.check_and_add(shared, {"usd": 3.0}, {"usd": 5.0}, {"usd": 3600.0})

        # b2 reads the same Redis key — sees the existing 3.0 spend.
        allowed, exceeded = b2.check_and_add(shared, {"usd": 3.0}, {"usd": 5.0}, {"usd": 3600.0})
        assert allowed is False
        assert exceeded == "usd"
    finally:
        b1.reset(shared)
        b1.close()
        b2.close()


# ---------------------------------------------------------------------------
# Group H — Async check-and-add
# ---------------------------------------------------------------------------


async def test_async_allowed_within_limit(async_backend: AsyncRedisBackend) -> None:
    allowed, exceeded = await async_backend.check_and_add(
        _BUDGET,
        amounts={"usd": 2.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is True
    assert exceeded is None


async def test_async_rejected_when_limit_exceeded(async_backend: AsyncRedisBackend) -> None:
    allowed, exceeded = await async_backend.check_and_add(
        _BUDGET,
        amounts={"usd": 6.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is False
    assert exceeded == "usd"


async def test_async_window_resets_after_expiry(async_backend: AsyncRedisBackend) -> None:
    await async_backend.check_and_add(_BUDGET, {"usd": 4.5}, {"usd": 5.0}, {"usd": 1.0})
    time.sleep(1.5)
    allowed, exceeded = await async_backend.check_and_add(
        _BUDGET, {"usd": 4.5}, {"usd": 5.0}, {"usd": 1.0}
    )
    assert allowed is True
    assert exceeded is None


async def test_async_get_state(async_backend: AsyncRedisBackend) -> None:
    await async_backend.check_and_add(
        _BUDGET,
        amounts={"usd": 2.5, "llm_calls": 10.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    state = await async_backend.get_state(_BUDGET)
    assert state["usd"] == pytest.approx(2.5)
    assert state["llm_calls"] == pytest.approx(10.0)


async def test_async_reset(async_backend: AsyncRedisBackend) -> None:
    await async_backend.check_and_add(_BUDGET, {"usd": 1.0}, {"usd": 5.0}, {"usd": 3600.0})
    await async_backend.reset(_BUDGET)
    state = await async_backend.get_state(_BUDGET)
    assert state == {}


# ---------------------------------------------------------------------------
# Group I — Full budget() factory integration
# ---------------------------------------------------------------------------


def test_budget_factory_enforces_usd_cap_with_redis(redis_url: str) -> None:
    from shekel import budget

    b = budget("$0.001/hr", name="docker_usd", backend=RedisBackend(url=redis_url))
    b._backend.reset("docker_usd")
    try:
        with pytest.raises(BudgetExceededError):
            b._record_spend(0.002, "gpt-4o-mini", {"input": 10, "output": 5})
    finally:
        b._backend.reset("docker_usd")
        b._backend.close()  # type: ignore[union-attr]


def test_budget_factory_multi_cap_with_redis(redis_url: str) -> None:
    from shekel import budget

    b = budget(
        "$5/hr + 1 call/hr",
        name="docker_multicap",
        backend=RedisBackend(url=redis_url),
    )
    b._backend.reset("docker_multicap")
    try:
        # First call allowed.
        b._record_spend(0.001, "gpt-4o-mini", {"input": 10, "output": 5})

        # Second call: llm_calls limit (1) exceeded.
        with pytest.raises(BudgetExceededError) as exc_info:
            b._record_spend(0.001, "gpt-4o-mini", {"input": 10, "output": 5})

        assert exc_info.value.exceeded_counter == "llm_calls"
    finally:
        b._backend.reset("docker_multicap")
        b._backend.close()  # type: ignore[union-attr]


def test_budget_factory_window_reset_allows_new_spend(redis_url: str) -> None:
    """After a 1 s window expires, spend is allowed again."""
    from shekel import budget

    b = budget("$0.001/s", name="docker_window", backend=RedisBackend(url=redis_url))
    b._backend.reset("docker_window")
    try:
        with pytest.raises(BudgetExceededError):
            b._record_spend(0.002, "gpt-4o-mini", {})

        time.sleep(1.5)

        # Fresh window — should succeed.
        b._record_spend(0.0005, "gpt-4o-mini", {})
    finally:
        b._backend.reset("docker_window")
        b._backend.close()  # type: ignore[union-attr]
