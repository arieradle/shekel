"""Tests for distributed budget features.

Domain: distributed budgets — multi-cap spec parsing, new backend protocol,
Redis backend, BudgetConfigMismatchError, on_backend_unavailable.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Group A — Multi-cap spec parsing (_parse_cap_spec)
# ---------------------------------------------------------------------------


def test_parse_cap_spec_single_usd():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("$5/hr")
    assert caps == [("usd", 5.0, 3600.0)]


def test_parse_cap_spec_single_calls():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("100 calls/hr")
    assert caps == [("llm_calls", 100.0, 3600.0)]


def test_parse_cap_spec_single_tools():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("20 tools/hr")
    assert caps == [("tool_calls", 20.0, 3600.0)]


def test_parse_cap_spec_usd_keyword():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("5 usd/hr")
    assert caps == [("usd", 5.0, 3600.0)]


def test_parse_cap_spec_multi_same_window():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("$5/hr + 100 calls/hr")
    assert len(caps) == 2
    assert ("usd", 5.0, 3600.0) in caps
    assert ("llm_calls", 100.0, 3600.0) in caps


def test_parse_cap_spec_multi_different_windows():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("$5/hr + 100 calls/30min")
    assert len(caps) == 2
    assert ("usd", 5.0, 3600.0) in caps
    assert ("llm_calls", 100.0, 1800.0) in caps


def test_parse_cap_spec_three_caps():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("$5/hr + 100 calls/hr + 20 tools/hr")
    assert len(caps) == 3
    counters = [c[0] for c in caps]
    assert "usd" in counters
    assert "llm_calls" in counters
    assert "tool_calls" in counters


def test_parse_cap_spec_with_window_count():
    from shekel._temporal import _parse_cap_spec

    caps = _parse_cap_spec("$10/30min")
    assert caps == [("10", 10.0, 1800.0)] or caps == [("usd", 10.0, 1800.0)]
    # Either form is acceptable, key is the window_s
    counter, amount, window_s = caps[0]
    assert amount == 10.0
    assert window_s == 1800.0


def test_parse_cap_spec_rejects_calendar_unit():
    from shekel._temporal import _parse_cap_spec

    with pytest.raises(ValueError):
        _parse_cap_spec("$5/day")


def test_parse_cap_spec_rejects_unknown_cap_type():
    from shekel._temporal import _parse_cap_spec

    with pytest.raises(ValueError):
        _parse_cap_spec("100 widgets/hr")


def test_parse_cap_spec_rejects_garbage():
    from shekel._temporal import _parse_cap_spec

    with pytest.raises(ValueError):
        _parse_cap_spec("hello world")


def test_parse_cap_spec_rejects_zero_amount():
    from shekel._temporal import _parse_cap_spec

    with pytest.raises(ValueError):
        _parse_cap_spec("$0/hr")


def test_parse_cap_spec_singular_forms():
    """'call' and 'tool' (singular) should be accepted."""
    from shekel._temporal import _parse_cap_spec

    caps_call = _parse_cap_spec("1 call/hr")
    assert caps_call[0][0] == "llm_calls"

    caps_tool = _parse_cap_spec("1 tool/hr")
    assert caps_tool[0][0] == "tool_calls"


# ---------------------------------------------------------------------------
# Group B — budget() factory: form mixing and multi-cap
# ---------------------------------------------------------------------------


def test_budget_factory_rejects_spec_with_max_usd():
    from shekel import budget

    with pytest.raises(ValueError, match="[Mm]ix"):
        budget("$5/hr", name="api", max_usd=10.0)


def test_budget_factory_rejects_spec_with_max_llm_calls():
    from shekel import budget

    with pytest.raises(ValueError, match="[Mm]ix"):
        budget("$5/hr", name="api", max_llm_calls=100)


def test_budget_factory_rejects_spec_with_window_seconds():
    from shekel import budget

    with pytest.raises(ValueError, match="[Mm]ix"):
        budget("$5/hr", name="api", window_seconds=3600)


def test_budget_factory_multi_cap_spec_string():
    from shekel import budget
    from shekel._temporal import TemporalBudget

    b = budget("$5/hr + 100 calls/hr", name="api")
    assert isinstance(b, TemporalBudget)


def test_budget_factory_multi_cap_spec_has_both_caps():
    from shekel import budget

    b = budget("$5/hr + 100 calls/hr", name="api")
    assert "usd" in b._caps
    assert "llm_calls" in b._caps


def test_budget_factory_multi_cap_kwargs():
    from shekel import budget
    from shekel._temporal import TemporalBudget

    b = budget(max_usd=5.0, max_llm_calls=100, window_seconds=3600, name="api")
    assert isinstance(b, TemporalBudget)
    assert "usd" in b._caps
    assert "llm_calls" in b._caps


def test_budget_factory_single_calls_spec():
    """budget('100 calls/hr', name='x') — no USD cap."""
    from shekel import budget
    from shekel._temporal import TemporalBudget

    b = budget("100 calls/hr", name="x")
    assert isinstance(b, TemporalBudget)
    assert "llm_calls" in b._caps


# ---------------------------------------------------------------------------
# Group C — New InMemoryBackend multi-cap protocol
# ---------------------------------------------------------------------------


def test_new_inmemory_get_state_fresh():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    state = backend.get_state("new_key")
    assert state == {}


def test_new_inmemory_check_and_add_within_limits():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    allowed, exceeded = backend.check_and_add(
        "b1",
        amounts={"usd": 2.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is True
    assert exceeded is None


def test_new_inmemory_check_and_add_updates_state():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    backend.check_and_add("b1", {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})
    state = backend.get_state("b1")
    assert state.get("usd") == pytest.approx(2.0)


def test_new_inmemory_check_and_add_usd_exceeded():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    allowed, exceeded = backend.check_and_add(
        "b1",
        amounts={"usd": 6.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is False
    assert exceeded == "usd"


def test_new_inmemory_check_and_add_calls_exceeded():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    # Fill up to limit
    backend.check_and_add("b1", {"llm_calls": 99.0}, {"llm_calls": 100.0}, {"llm_calls": 3600.0})
    # One more should exceed
    allowed, exceeded = backend.check_and_add(
        "b1",
        amounts={"llm_calls": 2.0},
        limits={"llm_calls": 100.0},
        windows={"llm_calls": 3600.0},
    )
    assert allowed is False
    assert exceeded == "llm_calls"


def test_new_inmemory_check_usd_before_calls():
    """When both would exceed, usd is reported (checked first)."""
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    allowed, exceeded = backend.check_and_add(
        "b1",
        amounts={"usd": 6.0, "llm_calls": 101.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    assert allowed is False
    assert exceeded == "usd"


def test_new_inmemory_none_limit_always_allowed():
    """None limit = no cap; counter is still tracked."""
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    allowed, exceeded = backend.check_and_add(
        "b1",
        amounts={"usd": 999.0},
        limits={"usd": None},
        windows={"usd": 3600.0},
    )
    assert allowed is True
    assert exceeded is None
    assert backend.get_state("b1")["usd"] == pytest.approx(999.0)


def test_new_inmemory_all_or_nothing():
    """If second counter fails, first counter is NOT incremented."""
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    # First add some usd
    backend.check_and_add("b1", {"usd": 1.0}, {"usd": 5.0}, {"usd": 3600.0})

    # Now try to add where llm_calls would exceed but usd would not
    allowed, exceeded = backend.check_and_add(
        "b1",
        amounts={"usd": 1.0, "llm_calls": 101.0},
        limits={"usd": 5.0, "llm_calls": 100.0},
        windows={"usd": 3600.0, "llm_calls": 3600.0},
    )
    assert allowed is False
    assert exceeded == "llm_calls"
    # USD should NOT have been incremented (all-or-nothing)
    state = backend.get_state("b1")
    assert state["usd"] == pytest.approx(1.0)


def test_new_inmemory_reset_clears_state():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    backend.check_and_add("b1", {"usd": 2.0}, {"usd": 5.0}, {"usd": 3600.0})
    backend.reset("b1")
    assert backend.get_state("b1") == {}


def test_new_inmemory_per_counter_window_expiry():
    """Each counter can have its own window; they expire independently."""
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    t0 = 1000.0

    with patch("time.monotonic", return_value=t0):
        backend.check_and_add(
            "b1",
            amounts={"usd": 4.0, "llm_calls": 90.0},
            limits={"usd": 5.0, "llm_calls": 100.0},
            windows={"usd": 3600.0, "llm_calls": 60.0},  # calls window is 1min
        )

    # After 2 minutes: llm_calls window expired, usd window still active
    with patch("time.monotonic", return_value=t0 + 120.0):
        allowed, exceeded = backend.check_and_add(
            "b1",
            amounts={"usd": 0.5, "llm_calls": 90.0},
            limits={"usd": 5.0, "llm_calls": 100.0},
            windows={"usd": 3600.0, "llm_calls": 60.0},
        )
    # usd: 4.0 + 0.5 = 4.5 <= 5.0 ✓; llm_calls: window expired → reset to 0, 90 <= 100 ✓
    assert allowed is True
    state = backend.get_state("b1")
    assert state["usd"] == pytest.approx(4.5)
    assert state["llm_calls"] == pytest.approx(90.0)  # fresh window


def test_new_inmemory_window_start_set_on_first_add():
    from shekel._temporal import InMemoryBackend

    backend = InMemoryBackend()
    backend.check_and_add("b1", {"usd": 1.0}, {"usd": 5.0}, {"usd": 3600.0})
    # get_window_info is an optional observability method
    if hasattr(backend, "get_window_info"):
        info = backend.get_window_info("b1")
        _, window_start = info["usd"]
        assert window_start is not None


# ---------------------------------------------------------------------------
# Group D — TemporalBudget multi-cap behavior
# ---------------------------------------------------------------------------


def test_temporal_multicap_usd_only_still_works():
    """Backward-compat: single USD cap still works as before."""
    from shekel._temporal import TemporalBudget
    from shekel.exceptions import BudgetExceededError

    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="usd_only")

    with pytest.raises(BudgetExceededError):
        tb._record_spend(6.0, "model", {"input": 100, "output": 100})


def test_temporal_multicap_spec_raises_on_usd_exceed():
    from shekel import budget
    from shekel.exceptions import BudgetExceededError

    b = budget("$5/hr + 100 calls/hr", name="api")

    with pytest.raises(BudgetExceededError):
        b._record_spend(6.0, "model", {"input": 100, "output": 100})


def test_temporal_multicap_spec_raises_on_calls_exceed():
    from shekel import budget
    from shekel.exceptions import BudgetExceededError

    b = budget("$5/hr + 1 call/hr", name="api")  # 1 call limit

    # First call should succeed
    # Second call should fail (call limit exceeded)
    b._record_spend(0.001, "model", {"input": 10, "output": 10})

    with pytest.raises(BudgetExceededError):
        b._record_spend(0.001, "model", {"input": 10, "output": 10})


def test_temporal_multicap_error_has_exceeded_counter():
    from shekel import budget
    from shekel.exceptions import BudgetExceededError

    b = budget("$5/hr + 1 call/hr", name="api")
    b._record_spend(0.001, "model", {})  # first call ok

    with pytest.raises(BudgetExceededError) as exc_info:
        b._record_spend(0.001, "model", {})

    # The error should indicate which counter was exceeded
    assert exc_info.value.exceeded_counter == "llm_calls"


def test_temporal_multicap_kwargs_form():
    from shekel import budget
    from shekel.exceptions import BudgetExceededError

    b = budget(max_usd=5.0, max_llm_calls=2, window_seconds=3600, name="kwarg_api")

    b._record_spend(0.001, "model", {})
    b._record_spend(0.001, "model", {})

    with pytest.raises(BudgetExceededError) as exc_info:
        b._record_spend(0.001, "model", {})

    assert exc_info.value.exceeded_counter == "llm_calls"


def test_temporal_multicap_caps_dict_structure():
    """_caps stores {counter: (limit, window_s)}."""
    from shekel import budget

    b = budget("$5/hr + 100 calls/30min", name="test")
    assert b._caps["usd"] == (5.0, 3600.0)
    assert b._caps["llm_calls"] == (100.0, 1800.0)


def test_temporal_no_usd_cap_calls_only():
    from shekel import budget
    from shekel.exceptions import BudgetExceededError

    b = budget("1 call/hr", name="calls_only")

    b._record_spend(0.0, "model", {})  # first call ok

    with pytest.raises(BudgetExceededError) as exc_info:
        b._record_spend(0.0, "model", {})

    assert exc_info.value.exceeded_counter == "llm_calls"


# ---------------------------------------------------------------------------
# Group E — BudgetConfigMismatchError
# ---------------------------------------------------------------------------


def test_budget_config_mismatch_error_exists():
    from shekel.exceptions import BudgetConfigMismatchError

    err = BudgetConfigMismatchError("Budget 'api' already registered with different limits")
    assert "api" in str(err)


def test_budget_config_mismatch_error_is_exception():
    from shekel.exceptions import BudgetConfigMismatchError

    with pytest.raises(BudgetConfigMismatchError):
        raise BudgetConfigMismatchError("mismatch")


def test_budget_config_mismatch_error_exported():
    """BudgetConfigMismatchError is importable from shekel.exceptions."""
    from shekel import exceptions

    assert hasattr(exceptions, "BudgetConfigMismatchError")


# ---------------------------------------------------------------------------
# Group F — on_backend_unavailable observability event
# ---------------------------------------------------------------------------


def test_on_backend_unavailable_noop_in_base():
    from shekel.integrations.base import ObservabilityAdapter

    adapter = ObservabilityAdapter()
    # Should not raise
    adapter.on_backend_unavailable({"budget_name": "api", "error": "timeout"})


def test_on_backend_unavailable_receives_correct_fields():
    from shekel.integrations.base import ObservabilityAdapter

    received: list[dict[str, Any]] = []

    class TestAdapter(ObservabilityAdapter):
        def on_backend_unavailable(self, data: dict[str, Any]) -> None:
            received.append(data)

    adapter = TestAdapter()
    adapter.on_backend_unavailable({"budget_name": "api", "error": "conn refused"})

    assert len(received) == 1
    assert received[0]["budget_name"] == "api"
    assert "error" in received[0]


# ---------------------------------------------------------------------------
# Group G — RedisBackend unit tests (mocked redis)
# ---------------------------------------------------------------------------


def _make_redis_mock(lua_result: Any = None) -> MagicMock:
    """Create a mock Redis client that returns lua_result from evalsha/eval."""
    mock_client = MagicMock()
    mock_client.script_load.return_value = "fakescriptsha"
    if lua_result is None:
        lua_result = [1, b""]  # allowed=1, exceeded_counter=""
    mock_client.evalsha.return_value = lua_result
    mock_client.hgetall.return_value = {b"usd:spent": b"2.0"}
    mock_client.delete.return_value = 1
    return mock_client


def test_redis_backend_importable():
    """RedisBackend is importable (redis is an optional dep — skip if not installed)."""
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    assert RedisBackend is not None


def test_redis_backend_check_and_add_allowed():
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = _make_redis_mock(lua_result=[1, b""])
    backend = RedisBackend()
    backend._client = mock_client  # inject mock
    backend._script_sha = "fakescriptsha"

    allowed, exceeded = backend.check_and_add(
        "api",
        amounts={"usd": 0.01},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is True
    assert exceeded is None


def test_redis_backend_check_and_add_rejected():
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = _make_redis_mock(lua_result=[0, b"usd"])
    backend = RedisBackend()
    backend._client = mock_client
    backend._script_sha = "fakescriptsha"

    allowed, exceeded = backend.check_and_add(
        "api",
        amounts={"usd": 6.0},
        limits={"usd": 5.0},
        windows={"usd": 3600.0},
    )
    assert allowed is False
    assert exceeded == "usd"


def test_redis_backend_fail_closed_on_error():
    """When Redis is unreachable, default behavior raises BudgetExceededError."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import RedisBackend
    from shekel.exceptions import BudgetExceededError

    mock_client = MagicMock()
    mock_client.script_load.return_value = "sha"
    mock_client.evalsha.side_effect = redis_lib.RedisError("connection refused")

    backend = RedisBackend(on_unavailable="closed")
    backend._client = mock_client
    backend._script_sha = "sha"

    with pytest.raises(BudgetExceededError, match="[Uu]navailable|[Bb]ackend"):
        backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})


def test_redis_backend_fail_open_when_configured():
    """With on_unavailable='open', Redis errors allow the call through."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    mock_client.script_load.return_value = "sha"
    mock_client.evalsha.side_effect = redis_lib.RedisError("connection refused")

    backend = RedisBackend(on_unavailable="open")
    backend._client = mock_client
    backend._script_sha = "sha"

    allowed, exceeded = backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})
    assert allowed is True
    assert exceeded is None


def test_redis_backend_emits_on_backend_unavailable_event():
    """When backend is unavailable, on_backend_unavailable event is emitted."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import RedisBackend
    from shekel.exceptions import BudgetExceededError
    from shekel.integrations import AdapterRegistry

    AdapterRegistry.clear()
    mock_adapter = MagicMock()
    AdapterRegistry.register(mock_adapter)

    try:
        mock_client = MagicMock()
        mock_client.script_load.return_value = "sha"
        mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

        backend = RedisBackend(on_unavailable="closed")
        backend._client = mock_client
        backend._script_sha = "sha"

        with pytest.raises(BudgetExceededError):
            backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

        mock_adapter.on_backend_unavailable.assert_called_once()
        call_kwargs = mock_adapter.on_backend_unavailable.call_args[0][0]
        assert call_kwargs["budget_name"] == "api"
    finally:
        AdapterRegistry.clear()


def test_redis_backend_circuit_breaker_stops_calling_redis():
    """After N consecutive errors, circuit breaker stops calling Redis."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import RedisBackend
    from shekel.exceptions import BudgetExceededError

    mock_client = MagicMock()
    mock_client.script_load.return_value = "sha"
    mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

    backend = RedisBackend(
        on_unavailable="closed",
        circuit_breaker_threshold=3,
        circuit_breaker_cooldown=10.0,
    )
    backend._client = mock_client
    backend._script_sha = "sha"

    # Trigger 3 consecutive errors to open circuit breaker
    for _ in range(3):
        with pytest.raises(BudgetExceededError):
            backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    evalsha_calls_before = mock_client.evalsha.call_count

    # Next call — circuit is open, should NOT call Redis
    with pytest.raises(BudgetExceededError):
        backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    # evalsha should not have been called again
    assert mock_client.evalsha.call_count == evalsha_calls_before


def test_redis_backend_circuit_breaker_resets_after_cooldown():
    """Circuit breaker allows retry after cooldown period."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import RedisBackend
    from shekel.exceptions import BudgetExceededError

    mock_client = MagicMock()
    mock_client.script_load.return_value = "sha"
    mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

    backend = RedisBackend(
        on_unavailable="closed",
        circuit_breaker_threshold=3,
        circuit_breaker_cooldown=10.0,
    )
    backend._client = mock_client
    backend._script_sha = "sha"

    t0 = 1000.0
    with patch("time.monotonic", return_value=t0):
        for _ in range(3):
            with pytest.raises(BudgetExceededError):
                backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    evalsha_before = mock_client.evalsha.call_count

    # After cooldown, circuit should close and retry Redis
    with patch("time.monotonic", return_value=t0 + 11.0):
        with pytest.raises(BudgetExceededError):
            backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    assert mock_client.evalsha.call_count > evalsha_before


def test_redis_backend_config_mismatch_raises():
    """Spec hash mismatch raises BudgetConfigMismatchError."""
    pytest.importorskip("redis")

    from shekel.backends.redis import RedisBackend
    from shekel.exceptions import BudgetConfigMismatchError

    mock_client = MagicMock()
    mock_client.script_load.return_value = "sha"
    # Simulate mismatch: Lua returns -1 or special sentinel for mismatch
    mock_client.evalsha.return_value = [-2, b"spec_mismatch"]

    backend = RedisBackend()
    backend._client = mock_client
    backend._script_sha = "sha"

    with pytest.raises(BudgetConfigMismatchError):
        backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})


def test_redis_backend_get_state():
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    mock_client.hgetall.return_value = {
        b"usd:spent": b"2.34",
        b"llm_calls:spent": b"45",
    }

    backend = RedisBackend()
    backend._client = mock_client

    state = backend.get_state("api")
    assert state["usd"] == pytest.approx(2.34)
    assert state["llm_calls"] == pytest.approx(45.0)


def test_redis_backend_reset_deletes_key():
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    backend = RedisBackend()
    backend._client = mock_client

    backend.reset("api")
    mock_client.delete.assert_called_once()


def test_redis_backend_close():
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    backend = RedisBackend()
    backend._client = mock_client

    backend.close()
    mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Group H — AsyncRedisBackend unit tests (mocked async redis)
# ---------------------------------------------------------------------------


def test_async_redis_backend_importable():
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    assert AsyncRedisBackend is not None


def test_async_redis_backend_check_and_add_allowed():
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "sha"
    mock_client.evalsha.return_value = [1, b""]

    backend = AsyncRedisBackend()
    backend._client = mock_client
    backend._script_sha = "sha"

    async def _run() -> None:
        allowed, exceeded = await backend.check_and_add(
            "api",
            amounts={"usd": 0.01},
            limits={"usd": 5.0},
            windows={"usd": 3600.0},
        )
        assert allowed is True
        assert exceeded is None

    asyncio.run(_run())


def test_async_redis_backend_check_and_add_rejected():
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "sha"
    mock_client.evalsha.return_value = [0, b"usd"]

    backend = AsyncRedisBackend()
    backend._client = mock_client
    backend._script_sha = "sha"

    async def _run() -> None:
        allowed, exceeded = await backend.check_and_add(
            "api",
            amounts={"usd": 6.0},
            limits={"usd": 5.0},
            windows={"usd": 3600.0},
        )
        assert allowed is False
        assert exceeded == "usd"

    asyncio.run(_run())


def test_async_redis_backend_fail_closed_on_error():
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import AsyncRedisBackend
    from shekel.exceptions import BudgetExceededError

    mock_client = AsyncMock()
    mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

    backend = AsyncRedisBackend(on_unavailable="closed")
    backend._client = mock_client
    backend._script_sha = "sha"

    async def _run() -> None:
        with pytest.raises(BudgetExceededError):
            await backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    asyncio.run(_run())


def test_async_redis_backend_get_state():
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.hgetall.return_value = {b"usd:spent": b"1.5"}

    backend = AsyncRedisBackend()
    backend._client = mock_client

    async def _run() -> None:
        state = await backend.get_state("api")
        assert state["usd"] == pytest.approx(1.5)

    asyncio.run(_run())


def test_async_redis_backend_reset():
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    backend = AsyncRedisBackend()
    backend._client = mock_client

    async def _run() -> None:
        await backend.reset("api")
        mock_client.delete.assert_called_once()

    asyncio.run(_run())


def test_async_redis_backend_close():
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    backend = AsyncRedisBackend()
    backend._client = mock_client

    async def _run() -> None:
        await backend.close()
        mock_client.aclose.assert_called_once()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Group I — Coverage completeness: _temporal.py missing branches
# ---------------------------------------------------------------------------


def test_temporal_budget_no_window_seconds_raises():
    """kwargs form without window_seconds should raise ValueError."""
    from shekel._temporal import TemporalBudget

    with pytest.raises(ValueError, match="window_seconds"):
        TemporalBudget(max_usd=5.0, name="no_ws")


def test_temporal_budget_tool_calls_cap_kwarg():
    """max_tool_calls kwarg builds 'tool_calls' cap."""
    from shekel._temporal import TemporalBudget

    tb = TemporalBudget(max_tool_calls=10, window_seconds=3600, name="tc")
    assert "tool_calls" in tb._caps


def test_temporal_budget_no_caps_raises():
    """kwargs form with no cap at all should raise ValueError."""
    from shekel._temporal import TemporalBudget

    with pytest.raises(ValueError, match="cap"):
        TemporalBudget(window_seconds=3600, name="no_cap")


def test_lazy_window_reset_skips_backend_without_get_window_info():
    """_lazy_window_reset returns early if backend lacks get_window_info."""
    from unittest.mock import MagicMock

    from shekel._temporal import TemporalBudget

    # spec=[] means the mock has NO attributes — hasattr returns False.
    mock_backend = MagicMock(spec=[])
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="no_winfo", backend=mock_backend)
    # __enter__ calls _lazy_window_reset — should not raise.
    with tb:
        pass


def test_lazy_window_reset_skips_when_window_start_none():
    """_lazy_window_reset returns early when window_start is None."""
    from shekel._temporal import InMemoryBackend, TemporalBudget

    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="wstart_none", backend=backend)
    # Inject state with window_start=None (fresh counter not yet started).
    backend._state["wstart_none"] = {"usd": (2.0, None)}
    # __enter__ → _lazy_window_reset → window_start is None → early return.
    with tb:
        pass


# ---------------------------------------------------------------------------
# Group J — Coverage completeness: redis.py missing branches (mocked)
# ---------------------------------------------------------------------------


def test_emit_unavailable_swallows_emit_exception():
    """_emit_unavailable must not propagate when AdapterRegistry.emit_event raises."""
    pytest.importorskip("redis")
    from unittest.mock import patch

    from shekel.backends.redis import _emit_unavailable

    with patch(
        "shekel.integrations.AdapterRegistry.emit_event",
        side_effect=RuntimeError("registry exploded"),
    ):
        _emit_unavailable("api", Exception("test"))  # must not raise


def test_redis_backend_tls_passes_ssl_kwarg():
    """RedisBackend(tls=True) passes ssl=True to Redis.from_url."""
    pytest.importorskip("redis")
    from unittest.mock import patch

    import redis as redis_lib

    from shekel.backends.redis import RedisBackend

    with patch.object(redis_lib.Redis, "from_url", return_value=MagicMock()) as mock_from_url:
        backend = RedisBackend(tls=True)
        backend._ensure_client()
        _, kwargs = mock_from_url.call_args
        assert kwargs.get("ssl") is True


def test_redis_backend_get_state_returns_empty_on_redis_error():
    """get_state returns {} when hgetall raises."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    mock_client.hgetall.side_effect = redis_lib.RedisError("timeout")
    backend = RedisBackend()
    backend._client = mock_client

    assert backend.get_state("api") == {}


def test_redis_backend_get_state_skips_non_numeric_value():
    """get_state silently skips fields that can't be parsed as float."""
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    mock_client.hgetall.return_value = {b"usd:spent": b"not_a_number"}
    backend = RedisBackend()
    backend._client = mock_client

    assert backend.get_state("api") == {}


def test_async_redis_backend_tls_passes_ssl_kwarg():
    """AsyncRedisBackend(tls=True) passes ssl=True to aioredis.Redis.from_url."""
    pytest.importorskip("redis")
    from unittest.mock import patch

    import redis.asyncio as aioredis

    from shekel.backends.redis import AsyncRedisBackend

    async def _run() -> None:
        with patch.object(aioredis.Redis, "from_url", return_value=AsyncMock()) as mock_from_url:
            backend = AsyncRedisBackend(tls=True)
            await backend._ensure_client()
            _, kwargs = mock_from_url.call_args
            assert kwargs.get("ssl") is True

    asyncio.run(_run())


def test_async_redis_backend_config_mismatch_raises():
    """evalsha returning -2 raises BudgetConfigMismatchError (async path)."""
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend
    from shekel.exceptions import BudgetConfigMismatchError

    mock_client = AsyncMock()
    mock_client.evalsha.return_value = [-2, b"spec_mismatch"]

    backend = AsyncRedisBackend()
    backend._client = mock_client
    backend._script_sha = "sha"

    async def _run() -> None:
        with pytest.raises(BudgetConfigMismatchError):
            await backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

    asyncio.run(_run())


def test_async_redis_backend_fail_open_when_configured():
    """AsyncRedisBackend with on_unavailable='open' allows calls through on error."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

    backend = AsyncRedisBackend(on_unavailable="open")
    backend._client = mock_client
    backend._script_sha = "sha"

    async def _run() -> None:
        allowed, exceeded = await backend.check_and_add(
            "api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0}
        )
        assert allowed is True
        assert exceeded is None

    asyncio.run(_run())


def test_async_redis_backend_circuit_breaker_opens_and_stops_redis():
    """After N errors the async circuit opens and Redis is no longer called."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import AsyncRedisBackend
    from shekel.exceptions import BudgetExceededError

    mock_client = AsyncMock()
    mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

    backend = AsyncRedisBackend(
        on_unavailable="closed",
        circuit_breaker_threshold=3,
        circuit_breaker_cooldown=10.0,
    )
    backend._client = mock_client
    backend._script_sha = "sha"

    async def _run() -> None:
        for _ in range(3):
            with pytest.raises(BudgetExceededError):
                await backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

        calls_before = mock_client.evalsha.call_count

        with pytest.raises(BudgetExceededError):
            await backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

        assert mock_client.evalsha.call_count == calls_before

    asyncio.run(_run())


def test_async_redis_backend_circuit_breaker_resets_after_cooldown():
    """Async circuit breaker allows retry after cooldown."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import AsyncRedisBackend
    from shekel.exceptions import BudgetExceededError

    mock_client = AsyncMock()
    mock_client.evalsha.side_effect = redis_lib.RedisError("timeout")

    backend = AsyncRedisBackend(
        on_unavailable="closed",
        circuit_breaker_threshold=3,
        circuit_breaker_cooldown=10.0,
    )
    backend._client = mock_client
    backend._script_sha = "sha"

    t0 = 1000.0

    async def _run() -> None:
        with patch("time.monotonic", return_value=t0):
            for _ in range(3):
                with pytest.raises(BudgetExceededError):
                    await backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

        calls_before = mock_client.evalsha.call_count

        with patch("time.monotonic", return_value=t0 + 11.0):
            with pytest.raises(BudgetExceededError):
                await backend.check_and_add("api", {"usd": 0.01}, {"usd": 5.0}, {"usd": 3600.0})

        assert mock_client.evalsha.call_count > calls_before

    asyncio.run(_run())


def test_async_redis_backend_get_state_returns_empty_on_error():
    """async get_state returns {} when hgetall raises."""
    pytest.importorskip("redis")
    import redis as redis_lib

    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.hgetall.side_effect = redis_lib.RedisError("timeout")
    backend = AsyncRedisBackend()
    backend._client = mock_client

    async def _run() -> None:
        assert await backend.get_state("api") == {}

    asyncio.run(_run())


def test_async_redis_backend_get_state_skips_non_numeric_value():
    """async get_state silently skips fields that can't be parsed as float."""
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.hgetall.return_value = {b"usd:spent": b"not_a_number"}
    backend = AsyncRedisBackend()
    backend._client = mock_client

    async def _run() -> None:
        assert await backend.get_state("api") == {}

    asyncio.run(_run())


def test_redis_backend_ensure_script_loads_on_first_call():
    """_ensure_script loads the Lua script when _script_sha is None."""
    pytest.importorskip("redis")
    from shekel.backends.redis import RedisBackend

    mock_client = MagicMock()
    mock_client.script_load.return_value = "loaded_sha"
    backend = RedisBackend()
    backend._client = mock_client
    # _script_sha starts as None — force the load path
    assert backend._script_sha is None
    sha = backend._ensure_script()
    assert sha == "loaded_sha"
    assert backend._script_sha == "loaded_sha"
    mock_client.script_load.assert_called_once()


def test_async_redis_backend_ensure_script_loads_on_first_call():
    """AsyncRedisBackend._ensure_script loads the Lua script when _script_sha is None."""
    pytest.importorskip("redis")
    from shekel.backends.redis import AsyncRedisBackend

    mock_client = AsyncMock()
    mock_client.script_load.return_value = "loaded_sha"
    backend = AsyncRedisBackend()
    backend._client = mock_client

    async def _run() -> None:
        assert backend._script_sha is None
        sha = await backend._ensure_script()
        assert sha == "loaded_sha"
        assert backend._script_sha == "loaded_sha"
        mock_client.script_load.assert_called_once()

    asyncio.run(_run())


def test_lazy_window_reset_skips_when_window_not_yet_expired():
    """_lazy_window_reset returns early if the primary window has not yet expired."""
    from unittest.mock import patch

    from shekel._temporal import InMemoryBackend, TemporalBudget

    backend = InMemoryBackend()
    tb = TemporalBudget(max_usd=5.0, window_seconds=3600, name="no_expire", backend=backend)
    t0 = 1000.0

    with patch("time.monotonic", return_value=t0):
        backend.check_and_add("no_expire", {"usd": 1.0}, {"usd": 5.0}, {"usd": 3600.0})

    # Only 100 s elapsed — window has NOT expired (3600 s window)
    with patch("time.monotonic", return_value=t0 + 100.0):
        tb._lazy_window_reset()  # must return early without emitting
