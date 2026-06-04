"""Tests for per-tenant budget enforcement (SHEK-1 / SHEK-3).

Uses fakeredis — no Docker or real Redis required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    import fakeredis

    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FAKEREDIS_AVAILABLE, reason="fakeredis not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_backend():
    """Return a RedisBackend wired to an in-process fakeredis server."""
    from shekel.backends.redis import RedisBackend

    server = fakeredis.FakeServer()
    backend = RedisBackend.__new__(RedisBackend)
    backend._url = "redis://localhost"
    backend._tls = False
    backend._on_unavailable = "closed"
    backend._cb_threshold = 3
    backend._cb_cooldown = 10.0
    backend._client = fakeredis.FakeRedis(server=server, decode_responses=False)
    backend._script_sha = None
    backend._consecutive_errors = 0
    backend._circuit_open_at = None
    return backend


# ---------------------------------------------------------------------------
# SHEK-3: budget() factory routing
# ---------------------------------------------------------------------------


class TestBudgetFactoryRouting:
    """budget() routes to TemporalBudget when tenant_id or backend is set."""

    def test_tenant_id_routes_to_temporal_budget(self) -> None:
        from shekel import budget
        from shekel._temporal import TemporalBudget

        b = budget(max_usd=0.10, tenant_id="user-1", name="api", backend=_make_backend())
        assert isinstance(b, TemporalBudget)

    def test_default_window_is_30_days(self) -> None:
        from shekel import budget

        b = budget(max_usd=0.10, tenant_id="user-1", name="api", backend=_make_backend())
        assert b._caps["usd"][1] == 86400 * 30

    def test_explicit_window_seconds_overrides_default(self) -> None:
        from shekel import budget

        b = budget(
            max_usd=0.10,
            tenant_id="user-1",
            name="api",
            backend=_make_backend(),
            window_seconds=3600,
        )
        assert b._caps["usd"][1] == 3600

    def test_backend_alone_routes_to_temporal_budget(self) -> None:
        from shekel import budget
        from shekel._temporal import TemporalBudget

        b = budget(max_usd=1.00, name="api", backend=_make_backend(), window_seconds=3600)
        assert isinstance(b, TemporalBudget)

    def test_no_tenant_no_backend_returns_plain_budget(self) -> None:
        from shekel import budget
        from shekel._budget import Budget
        from shekel._temporal import TemporalBudget

        b = budget(max_usd=1.00)
        assert isinstance(b, Budget)
        assert not isinstance(b, TemporalBudget)

    def test_tenant_id_without_name_raises(self) -> None:
        from shekel import budget

        with pytest.raises(ValueError, match="name"):
            budget(max_usd=0.10, tenant_id="user-1", backend=_make_backend())

    def test_tenant_id_accessible_on_instance(self) -> None:
        from shekel import budget

        b = budget(max_usd=0.10, tenant_id="user-99", name="api", backend=_make_backend())
        assert b.tenant_id == "user-99"

    def test_tenant_id_none_when_not_set(self) -> None:
        from shekel import budget

        b = budget(max_usd=1.00, name="api", backend=_make_backend(), window_seconds=3600)
        assert b.tenant_id is None


# ---------------------------------------------------------------------------
# SHEK-3: TemporalBudget validation
# ---------------------------------------------------------------------------


class TestTemporalBudgetTenantValidation:
    """tenant_id validation in TemporalBudget.__init__."""

    def test_empty_tenant_id_raises(self) -> None:
        from shekel import budget

        with pytest.raises(ValueError, match="non-empty"):
            budget(max_usd=0.10, tenant_id="", name="api", backend=_make_backend())

    def test_tenant_id_without_backend_raises(self) -> None:
        from shekel._temporal import TemporalBudget

        with pytest.raises(ValueError, match="Redis backend"):
            TemporalBudget(
                max_usd=0.10,
                tenant_id="user-1",
                name="api",
                window_seconds=3600,
                backend=None,
            )

    def test_valid_tenant_id_does_not_raise(self) -> None:
        from shekel import budget

        b = budget(max_usd=0.10, tenant_id="user-1", name="api", backend=_make_backend())
        assert b.tenant_id == "user-1"

    def test_tenant_id_with_colon_is_valid(self) -> None:
        from shekel import budget

        b = budget(max_usd=0.10, tenant_id="org:user-1", name="api", backend=_make_backend())
        assert b.tenant_id == "org:user-1"


# ---------------------------------------------------------------------------
# SHEK-3: Redis key isolation
# ---------------------------------------------------------------------------


class TestTenantKeyIsolation:
    """Different tenant_ids use distinct Redis keys and never share state."""

    def _make_shared_backend(self):
        """Return two backends sharing the same fakeredis server."""
        server = fakeredis.FakeServer()
        from shekel.backends.redis import RedisBackend

        def _backend():
            b = RedisBackend.__new__(RedisBackend)
            b._url = "redis://localhost"
            b._tls = False
            b._on_unavailable = "closed"
            b._cb_threshold = 3
            b._cb_cooldown = 10.0
            b._client = fakeredis.FakeRedis(server=server, decode_responses=False)
            b._script_sha = None
            b._consecutive_errors = 0
            b._circuit_open_at = None
            return b

        return _backend

    def test_two_tenants_do_not_share_state(self) -> None:
        from shekel import budget

        make = self._make_shared_backend()

        # User A: tiny budget
        with budget(max_usd=0.001, tenant_id="user-a", name="api", backend=make()) as b_a:
            pass

        # User B: generous budget — should not be affected by user-a's spend
        with budget(max_usd=10.00, tenant_id="user-b", name="api", backend=make()) as b_b:
            pass

        assert b_a.spent == pytest.approx(0.0)
        assert b_b.spent == pytest.approx(0.0)

    def test_tenant_a_exceeded_does_not_block_tenant_b(self) -> None:
        from unittest.mock import patch

        import openai

        from shekel import budget
        from shekel.exceptions import BudgetExceededError

        make = self._make_shared_backend()
        mock_resp = _fake_openai_response(100, 50)

        # Apply mock OUTSIDE budget context so shekel wraps it, not replaces it
        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            client = openai.OpenAI(api_key="test")

            # Exhaust tenant-a
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.001,
                    tenant_id="user-a",
                    name="api",
                    backend=make(),
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
                    )

        # Tenant-b must still work
        with budget(max_usd=5.00, tenant_id="user-b", name="api", backend=make()) as b_b:
            pass
        assert b_b is not None

    def test_redis_key_includes_tenant_id(self) -> None:
        import openai

        from shekel import budget

        server = fakeredis.FakeServer()
        from shekel.backends.redis import RedisBackend

        backend = RedisBackend.__new__(RedisBackend)
        backend._url = "redis://localhost"
        backend._tls = False
        backend._on_unavailable = "closed"
        backend._cb_threshold = 3
        backend._cb_cooldown = 10.0
        redis_client = fakeredis.FakeRedis(server=server, decode_responses=False)
        backend._client = redis_client
        backend._script_sha = None
        backend._consecutive_errors = 0
        backend._circuit_open_at = None

        mock_resp = _fake_openai_response(100, 50)
        # Mock OUTSIDE budget so shekel's patch wraps the mock
        with patch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            client = openai.OpenAI(api_key="test")
            with budget(
                max_usd=1.00,
                tenant_id="user-123",
                name="api",
                backend=backend,
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ):
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hi"}],
                )

        keys = [k.decode() for k in redis_client.keys("shekel:tb:*")]
        assert any("api:user-123" in k for k in keys)
        assert not any(k == "shekel:tb:api" for k in keys)


# ---------------------------------------------------------------------------
# SHEK-3: BudgetConfigMismatchError
# ---------------------------------------------------------------------------


class TestTenantConfigMismatch:
    """Same (name, tenant_id) with different max_usd raises BudgetConfigMismatchError."""

    def _seed_tenant(self, make, tenant_id: str, max_usd: float) -> None:
        """Open a budget and make a tiny LLM call to seed the Redis spec_hash."""
        from unittest.mock import patch as upatch

        import openai

        from shekel import budget

        mock_resp = _fake_openai_response(1, 1)
        with upatch(
            "openai.resources.chat.completions.Completions.create",
            return_value=mock_resp,
        ):
            client = openai.OpenAI(api_key="test")
            with budget(
                max_usd=max_usd,
                tenant_id=tenant_id,
                name="api",
                backend=make(),
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ):
                client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                )

    def test_mismatch_on_different_limit(self) -> None:
        import openai

        from shekel import budget
        from shekel.exceptions import BudgetConfigMismatchError

        make = self._make_shared_backend()
        # Seed spec_hash for user-1 with limit 0.10
        self._seed_tenant(make, "user-1", 0.10)

        mock_resp = _fake_openai_response(1, 1)
        with patch("openai.resources.chat.completions.Completions.create", return_value=mock_resp):
            client = openai.OpenAI(api_key="test")
            with pytest.raises(BudgetConfigMismatchError):
                with budget(
                    max_usd=0.20,
                    tenant_id="user-1",
                    name="api",
                    backend=make(),
                    price_per_1k_tokens={"input": 0.001, "output": 0.001},
                ):
                    client.chat.completions.create(
                        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                    )

    def test_same_limit_does_not_raise(self) -> None:
        import openai

        from shekel import budget

        make = self._make_shared_backend()
        self._seed_tenant(make, "user-1", 0.10)

        mock_resp = _fake_openai_response(1, 1)
        with patch("openai.resources.chat.completions.Completions.create", return_value=mock_resp):
            client = openai.OpenAI(api_key="test")
            # Same limit — must not raise
            with budget(
                max_usd=0.10,
                tenant_id="user-1",
                name="api",
                backend=make(),
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ):
                client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                )

    def test_mismatch_is_per_tenant_not_global(self) -> None:
        import openai

        from shekel import budget

        make = self._make_shared_backend()
        self._seed_tenant(make, "user-1", 0.10)

        mock_resp = _fake_openai_response(1, 1)
        with patch("openai.resources.chat.completions.Completions.create", return_value=mock_resp):
            client = openai.OpenAI(api_key="test")
            # user-2 can use a different limit — no mismatch (different key)
            with budget(
                max_usd=0.50,
                tenant_id="user-2",
                name="api",
                backend=make(),
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ):
                client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                )

    def _make_shared_backend(self):
        server = fakeredis.FakeServer()
        from shekel.backends.redis import RedisBackend

        def _backend():
            b = RedisBackend.__new__(RedisBackend)
            b._url = "redis://localhost"
            b._tls = False
            b._on_unavailable = "closed"
            b._cb_threshold = 3
            b._cb_cooldown = 10.0
            b._client = fakeredis.FakeRedis(server=server, decode_responses=False)
            b._script_sha = None
            b._consecutive_errors = 0
            b._circuit_open_at = None
            return b

        return _backend


# ---------------------------------------------------------------------------
# SHEK-3: async parity
# ---------------------------------------------------------------------------


class TestTenantAsync:
    """async with budget(..., tenant_id=...) enforces identically to sync."""

    @pytest.mark.asyncio
    async def test_async_budget_with_tenant_id(self) -> None:
        from shekel import budget
        from shekel._temporal import TemporalBudget

        b = budget(max_usd=1.00, tenant_id="user-1", name="api", backend=_make_backend())
        assert isinstance(b, TemporalBudget)
        async with b:
            pass

    @pytest.mark.asyncio
    async def test_async_tenant_id_accessible(self) -> None:
        from shekel import budget

        async with budget(
            max_usd=1.00, tenant_id="async-user", name="api", backend=_make_backend()
        ) as b:
            assert b.tenant_id == "async-user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_openai_response(input_tokens: int, output_tokens: int):
    from unittest.mock import MagicMock

    m = MagicMock()
    m.choices[0].message.content = "hi"
    m.usage.prompt_tokens = input_tokens
    m.usage.completion_tokens = output_tokens
    m.model = "gpt-4o-mini"
    return m


def _shared_fakeredis_backend():
    """Return a factory that produces backends sharing one FakeServer."""
    server = fakeredis.FakeServer()
    from shekel.backends.redis import RedisBackend

    def _make():
        b = RedisBackend.__new__(RedisBackend)
        b._url = "redis://localhost"
        b._tls = False
        b._on_unavailable = "closed"
        b._cb_threshold = 3
        b._cb_cooldown = 10.0
        b._client = fakeredis.FakeRedis(server=server, decode_responses=False)
        b._script_sha = None
        b._consecutive_errors = 0
        b._circuit_open_at = None
        return b

    return _make


def _shared_async_fakeredis_backend():
    """Return a factory that produces async backends sharing one FakeServer."""
    server = fakeredis.FakeServer()
    from shekel.backends.redis import AsyncRedisBackend

    def _make():
        b = AsyncRedisBackend.__new__(AsyncRedisBackend)
        b._url = "redis://localhost"
        b._tls = False
        b._on_unavailable = "closed"
        b._cb_threshold = 3
        b._cb_cooldown = 10.0
        b._client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
        b._script_sha = None
        b._consecutive_errors = 0
        b._circuit_open_at = None
        return b

    return _make


def _seed_spend(make, name: str, tenant_id: str, max_usd: float) -> None:
    """Open a budget and make a tiny LLM call to seed Redis spend + spec_hash."""
    import openai

    from shekel import budget

    mock_resp = _fake_openai_response(1, 1)
    with patch("openai.resources.chat.completions.Completions.create", return_value=mock_resp):
        client = openai.OpenAI(api_key="test")
        with budget(
            max_usd=max_usd,
            tenant_id=tenant_id,
            name=name,
            backend=make(),
            price_per_1k_tokens={"input": 0.001, "output": 0.001},
        ):
            client.chat.completions.create(
                model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
            )


# ---------------------------------------------------------------------------
# SHEK-4: sync quota management API
# ---------------------------------------------------------------------------


class TestTenantQuotaManagement:
    """RedisBackend quota management methods: get_tenant_spend, get_tenant_limit,
    set_tenant_limit, reset_tenant, list_tenants."""

    def test_get_tenant_spend_unknown_tenant_returns_zero(self) -> None:

        backend = _make_backend()
        assert backend.get_tenant_spend(name="api", tenant_id="nobody") == 0.0

    def test_get_tenant_spend_returns_accumulated_spend(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 1.00)

        backend = make()
        spent = backend.get_tenant_spend(name="api", tenant_id="user-1")
        assert spent > 0.0

    def test_get_tenant_limit_unknown_tenant_returns_none(self) -> None:
        backend = _make_backend()
        assert backend.get_tenant_limit(name="api", tenant_id="nobody") is None

    def test_get_tenant_limit_returns_limit_after_set(self) -> None:
        backend = _make_backend()
        backend.set_tenant_limit(name="api", tenant_id="user-1", max_usd=0.50)
        assert backend.get_tenant_limit(name="api", tenant_id="user-1") == pytest.approx(0.50)

    def test_set_tenant_limit_allows_budget_with_new_limit(self) -> None:
        make = _shared_fakeredis_backend()
        # Seed with 0.10
        _seed_spend(make, "api", "user-1", 0.10)

        # Admin raises limit to 0.20
        make().set_tenant_limit(name="api", tenant_id="user-1", max_usd=0.20)

        # budget(max_usd=0.20) must now succeed without BudgetConfigMismatchError
        import openai

        from shekel import budget

        mock_resp = _fake_openai_response(1, 1)
        with patch("openai.resources.chat.completions.Completions.create", return_value=mock_resp):
            client = openai.OpenAI(api_key="test")
            with budget(
                max_usd=0.20,
                tenant_id="user-1",
                name="api",
                backend=make(),
                price_per_1k_tokens={"input": 0.001, "output": 0.001},
            ):
                client.chat.completions.create(
                    model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                )

    def test_set_tenant_limit_old_limit_raises_mismatch(self) -> None:
        from shekel import budget
        from shekel.exceptions import BudgetConfigMismatchError

        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 0.10)

        # Admin raises limit to 0.20
        make().set_tenant_limit(name="api", tenant_id="user-1", max_usd=0.20)

        # budget with OLD limit must raise BudgetConfigMismatchError
        import openai

        mock_resp = _fake_openai_response(1, 1)
        with patch("openai.resources.chat.completions.Completions.create", return_value=mock_resp):
            client = openai.OpenAI(api_key="test")
            with pytest.raises(BudgetConfigMismatchError):
                with budget(
                    max_usd=0.10,
                    tenant_id="user-1",
                    name="api",
                    backend=make(),
                    price_per_1k_tokens={"input": 0.001, "output": 0.001},
                ):
                    client.chat.completions.create(
                        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
                    )

    def test_reset_tenant_zeroes_spend(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 1.00)

        backend = make()
        assert backend.get_tenant_spend(name="api", tenant_id="user-1") > 0.0

        backend.reset_tenant(name="api", tenant_id="user-1")
        assert backend.get_tenant_spend(name="api", tenant_id="user-1") == pytest.approx(0.0)

    def test_reset_tenant_preserves_limit(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 0.50)

        backend = make()
        backend.reset_tenant(name="api", tenant_id="user-1")

        # Limit should still be readable after reset
        limit = backend.get_tenant_limit(name="api", tenant_id="user-1")
        assert limit == pytest.approx(0.50)

    def test_reset_tenant_allows_re_accumulation(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 1.00)

        make().reset_tenant(name="api", tenant_id="user-1")

        # Can accumulate spend again from zero without BudgetConfigMismatchError
        _seed_spend(make, "api", "user-1", 1.00)
        spent = make().get_tenant_spend(name="api", tenant_id="user-1")
        assert spent > 0.0

    def test_list_tenants_empty_when_no_tenants(self) -> None:
        backend = _make_backend()
        assert backend.list_tenants(name="api") == []

    def test_list_tenants_returns_all_tenant_ids(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 1.00)
        _seed_spend(make, "api", "user-2", 1.00)
        _seed_spend(make, "api", "user-3", 1.00)

        tenants = make().list_tenants(name="api")
        assert sorted(tenants) == ["user-1", "user-2", "user-3"]

    def test_list_tenants_excludes_other_budget_names(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "user-1", 1.00)
        _seed_spend(make, "other", "user-9", 1.00)

        tenants = make().list_tenants(name="api")
        assert tenants == ["user-1"]

    def test_list_tenants_handles_colon_in_tenant_id(self) -> None:
        make = _shared_fakeredis_backend()
        _seed_spend(make, "api", "org:user-1", 1.00)

        tenants = make().list_tenants(name="api")
        assert tenants == ["org:user-1"]


# ---------------------------------------------------------------------------
# SHEK-4: async quota management API
# ---------------------------------------------------------------------------


class TestAsyncTenantQuotaManagement:
    """AsyncRedisBackend mirrors all five sync methods."""

    @pytest.mark.asyncio
    async def test_async_get_tenant_spend_unknown_returns_zero(self) -> None:
        make = _shared_async_fakeredis_backend()
        backend = make()
        assert await backend.get_tenant_spend(name="api", tenant_id="nobody") == 0.0

    @pytest.mark.asyncio
    async def test_async_get_tenant_limit_unknown_returns_none(self) -> None:
        make = _shared_async_fakeredis_backend()
        backend = make()
        assert await backend.get_tenant_limit(name="api", tenant_id="nobody") is None

    @pytest.mark.asyncio
    async def test_async_set_and_get_tenant_limit(self) -> None:
        make = _shared_async_fakeredis_backend()
        backend = make()
        await backend.set_tenant_limit(name="api", tenant_id="user-1", max_usd=0.75)
        limit = await backend.get_tenant_limit(name="api", tenant_id="user-1")
        assert limit == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_async_reset_tenant_zeroes_spend(self) -> None:
        make = _shared_async_fakeredis_backend()
        backend = make()
        # Seed spend via the async set
        key = "shekel:tb:api:user-1"
        await backend._client.hset(key, "usd:spent", "0.42")

        await backend.reset_tenant(name="api", tenant_id="user-1")
        assert await backend.get_tenant_spend(name="api", tenant_id="user-1") == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_async_list_tenants(self) -> None:
        make = _shared_async_fakeredis_backend()
        backend = make()
        # Seed two tenant keys via async client
        await backend._client.hset("shekel:tb:api:user-a", "usd:spent", "0.10")
        await backend._client.hset("shekel:tb:api:user-b", "usd:spent", "0.20")

        tenants = await backend.list_tenants(name="api")
        assert sorted(tenants) == ["user-a", "user-b"]
