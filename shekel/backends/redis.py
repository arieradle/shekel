"""Redis-backed TemporalBudgetBackend for distributed budget enforcement.

Requires the 'redis' optional dependency::

    pip install shekel[redis]

Usage::

    from shekel import budget
    from shekel.backends.redis import RedisBackend

    backend = RedisBackend()                    # reads REDIS_URL from env
    backend = RedisBackend(url="redis://...")   # explicit URL

    with budget("$5/hr", name="api", backend=backend):
        run_agent()

Features:
- Atomic all-or-nothing enforcement via Lua script (one round-trip).
- Lazy connection on first use; connection pool for reuse.
- Per-counter independent rolling windows.
- Fail-closed (default) or fail-open on backend unavailability.
- Circuit breaker: stops calling Redis after N consecutive errors.
- BudgetConfigMismatchError when a budget name is already registered
  with different limits/windows.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from shekel.exceptions import BudgetConfigMismatchError, BudgetExceededError

# ---------------------------------------------------------------------------
# Lua script for atomic check-and-add.
#
# Key layout (one Redis hash per budget):
#   shekel:tb:{name}
#     spec_hash          → "<hash>"   (hex digest of config; mismatch detection)
#     {counter}:max      → "5.0"      (limit, or "" for uncapped)
#     {counter}:window_s → "3600"
#     {counter}:start    → "1234567890000"  (ms, from Redis TIME)
#     {counter}:spent    → "2.34"
#
# Return values from Lua:
#   {1, ""}         allowed
#   {0, counter}    exceeded: counter name
#   {-2, "spec_mismatch"}  config mismatch detected
# ---------------------------------------------------------------------------
_LUA_SCRIPT = """
local key = KEYS[1]
local spec_hash = ARGV[1]
local n = tonumber(ARGV[2])       -- number of counters
local MISMATCH_SENTINEL = -2

-- Check spec hash (mismatch detection).
local stored_hash = redis.call('HGET', key, 'spec_hash')
if stored_hash and stored_hash ~= '' and stored_hash ~= spec_hash then
    return {MISMATCH_SENTINEL, 'spec_mismatch'}
end

-- Fetch Redis server time (milliseconds).
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

-- Counters are passed as triplets: name, amount, limit (''/nil=uncapped), window_s
-- starting at ARGV[3].
local offset = 3

-- Phase 1: check all limits.
for i = 1, n do
    local counter   = ARGV[offset]
    local amount    = tonumber(ARGV[offset + 1])
    local limit_str = ARGV[offset + 2]
    local window_ms = tonumber(ARGV[offset + 3]) * 1000
    offset = offset + 4

    -- Window reset?
    local start_ms = tonumber(redis.call('HGET', key, counter .. ':start') or '0') or 0
    local spent    = tonumber(redis.call('HGET', key, counter .. ':spent') or '0') or 0
    if start_ms > 0 and (now_ms - start_ms) >= window_ms then
        spent = 0
    end

    -- Limit check ('' or missing = uncapped).
    if limit_str ~= '' then
        local limit = tonumber(limit_str)
        if limit and spent + amount > limit then
            return {0, counter}
        end
    end
end

-- Phase 2: commit all counters.
offset = 3
local max_window_ms = 0
for i = 1, n do
    local counter   = ARGV[offset]
    local amount    = tonumber(ARGV[offset + 1])
    local limit_str = ARGV[offset + 2]
    local window_ms = tonumber(ARGV[offset + 3]) * 1000
    offset = offset + 4

    if window_ms > max_window_ms then max_window_ms = window_ms end

    local start_ms = tonumber(redis.call('HGET', key, counter .. ':start') or '0') or 0
    local spent    = tonumber(redis.call('HGET', key, counter .. ':spent') or '0') or 0
    if start_ms == 0 or (now_ms - start_ms) >= window_ms then
        -- fresh window
        redis.call('HSET', key, counter .. ':start', now_ms)
        redis.call('HSET', key, counter .. ':spent', amount)
    else
        redis.call('HINCRBYFLOAT', key, counter .. ':spent', amount)
    end
    redis.call('HSET', key, counter .. ':max', limit_str)
    redis.call('HSET', key, counter .. ':window_s', tonumber(ARGV[offset - 1]))
end

-- Store spec hash and set TTL = 2x max window.
redis.call('HSET', key, 'spec_hash', spec_hash)
redis.call('PEXPIRE', key, max_window_ms * 2)

return {1, ''}
"""


def _build_spec_hash(
    limits: dict[str, float | None],
    windows: dict[str, float],
) -> str:
    """Stable hex hash of {counter: (limit, window_s)} for mismatch detection."""
    payload = {k: (limits.get(k), windows.get(k)) for k in sorted(limits)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _build_argv(
    spec_hash: str,
    amounts: dict[str, float],
    limits: dict[str, float | None],
    windows: dict[str, float],
) -> list[str]:
    """Build the ARGV list for the Lua script."""
    argv: list[str] = [spec_hash, str(len(amounts))]
    for counter, amount in amounts.items():
        limit = limits.get(counter)
        argv += [
            counter,
            str(amount),
            str(limit) if limit is not None else "",
            str(windows[counter]),
        ]
    return argv


def _emit_unavailable(budget_name: str, error: Exception) -> None:
    """Emit on_backend_unavailable event to all registered adapters."""
    try:
        from shekel.integrations import AdapterRegistry

        AdapterRegistry.emit_event(
            "on_backend_unavailable",
            {"budget_name": budget_name, "error": str(error)},
        )
    except Exception:  # noqa: BLE001
        pass


class RedisBackend:
    """Synchronous Redis-backed rolling-window budget backend.

    Args:
        url: Redis URL (e.g. ``redis://user:pass@host:6379/0``).
             If omitted, reads ``REDIS_URL`` from the environment.
        tls: Force TLS (sets ``ssl=True`` on the Redis connection).
        on_unavailable: ``"closed"`` (default) — raise BudgetExceededError
            when Redis is unreachable.  ``"open"`` — allow the call through.
        circuit_breaker_threshold: Consecutive errors before opening the
            circuit breaker.  Default 3.
        circuit_breaker_cooldown: Seconds to wait before retrying after
            circuit opens.  Default 10.
    """

    def __init__(
        self,
        url: str | None = None,
        tls: bool = False,
        on_unavailable: str = "closed",
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 10.0,
    ) -> None:
        self._url = url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        self._tls = tls
        self._on_unavailable = on_unavailable
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown

        self._client: Any = None  # lazily created
        self._script_sha: str | None = None
        self._consecutive_errors: int = 0
        self._circuit_open_at: float | None = None

    # ------------------------------------------------------------------
    # Lazy connection
    # ------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import redis as redis_lib  # noqa: PLC0415

                kwargs: dict[str, Any] = {"decode_responses": False}
                if self._tls:
                    kwargs["ssl"] = True
                self._client = redis_lib.Redis.from_url(self._url, **kwargs)
            except ImportError as exc:  # pragma: no cover — only reached without redis installed
                raise ImportError(
                    "RedisBackend requires 'redis': pip install shekel[redis]"
                ) from exc
        return self._client

    def _ensure_script(self) -> str:
        if self._script_sha is None:
            client = self._ensure_client()
            self._script_sha = client.script_load(_LUA_SCRIPT)
        return self._script_sha

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_at is None:
            return False
        if time.monotonic() - self._circuit_open_at >= self._cb_cooldown:
            # Cooldown elapsed — close the circuit and let the next call try.
            self._circuit_open_at = None
            self._consecutive_errors = 0
            return False
        return True

    def _record_error(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._cb_threshold:
            self._circuit_open_at = time.monotonic()

    def _record_success(self) -> None:
        self._consecutive_errors = 0
        self._circuit_open_at = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_add(
        self,
        budget_name: str,
        amounts: dict[str, float],
        limits: dict[str, float | None],
        windows: dict[str, float],
    ) -> tuple[bool, str | None]:
        key = f"shekel:tb:{budget_name}"
        spec_hash = _build_spec_hash(limits, windows)
        argv = _build_argv(spec_hash, amounts, limits, windows)

        if self._is_circuit_open():
            return self._handle_unavailable(budget_name, RuntimeError("Circuit breaker open"))

        try:
            sha = self._ensure_script()
            result = self._ensure_client().evalsha(sha, 1, key, *argv)
            self._record_success()
        except Exception as exc:
            self._record_error()
            _emit_unavailable(budget_name, exc)
            return self._handle_unavailable(budget_name, exc)

        status = int(result[0])
        counter_bytes = result[1]
        counter = counter_bytes.decode() if isinstance(counter_bytes, bytes) else str(counter_bytes)

        if status == -2:
            raise BudgetConfigMismatchError(
                f"Budget {budget_name!r} already registered with different limits/windows. "
                "Call backend.reset(budget_name) to clear the existing state."
            )
        if status == 0:
            return False, counter or None
        return True, None

    def _handle_unavailable(self, budget_name: str, exc: Exception) -> tuple[bool, str | None]:
        if self._on_unavailable == "open":
            return True, None
        raise BudgetExceededError(
            spent=0.0,
            limit=0.0,
            model="unknown",
            exceeded_counter="backend_unavailable",
        ) from exc

    def get_state(self, budget_name: str) -> dict[str, float]:
        key = f"shekel:tb:{budget_name}"
        try:
            raw = self._ensure_client().hgetall(key)
        except Exception:
            return {}
        result: dict[str, float] = {}
        for field_bytes, val_bytes in raw.items():
            field = field_bytes.decode() if isinstance(field_bytes, bytes) else str(field_bytes)
            if field.endswith(":spent"):
                counter = field[: -len(":spent")]
                try:
                    result[counter] = float(val_bytes)
                except (ValueError, TypeError):
                    pass  # corrupt/non-numeric value — skip
        return result

    def reset(self, budget_name: str) -> None:
        key = f"shekel:tb:{budget_name}"
        self._ensure_client().delete(key)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


class AsyncRedisBackend:
    """Async Redis-backed rolling-window budget backend.

    Same semantics as :class:`RedisBackend` but all public methods are
    coroutines — suitable for FastAPI, LangGraph, and other async contexts.

    Args:
        url: Redis URL. If omitted, reads ``REDIS_URL`` from the environment.
        tls: Force TLS.
        on_unavailable: ``"closed"`` (default) or ``"open"``.
        circuit_breaker_threshold: Consecutive errors before opening circuit.
        circuit_breaker_cooldown: Seconds before retrying after circuit opens.
    """

    def __init__(
        self,
        url: str | None = None,
        tls: bool = False,
        on_unavailable: str = "closed",
        circuit_breaker_threshold: int = 3,
        circuit_breaker_cooldown: float = 10.0,
    ) -> None:
        self._url = url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        self._tls = tls
        self._on_unavailable = on_unavailable
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown

        self._client: Any = None
        self._script_sha: str | None = None
        self._consecutive_errors: int = 0
        self._circuit_open_at: float | None = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis  # noqa: PLC0415

                kwargs: dict[str, Any] = {"decode_responses": False}
                if self._tls:
                    kwargs["ssl"] = True
                self._client = aioredis.Redis.from_url(self._url, **kwargs)
            except ImportError as exc:  # pragma: no cover — only reached without redis installed
                raise ImportError(
                    "AsyncRedisBackend requires 'redis[asyncio]': pip install shekel[redis]"
                ) from exc
        return self._client

    async def _ensure_script(self) -> str:
        if self._script_sha is None:
            client = await self._ensure_client()
            self._script_sha = await client.script_load(_LUA_SCRIPT)
        return self._script_sha

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_at is None:
            return False
        if time.monotonic() - self._circuit_open_at >= self._cb_cooldown:
            self._circuit_open_at = None
            self._consecutive_errors = 0
            return False
        return True

    def _record_error(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._cb_threshold:
            self._circuit_open_at = time.monotonic()

    def _record_success(self) -> None:
        self._consecutive_errors = 0
        self._circuit_open_at = None

    async def check_and_add(
        self,
        budget_name: str,
        amounts: dict[str, float],
        limits: dict[str, float | None],
        windows: dict[str, float],
    ) -> tuple[bool, str | None]:
        key = f"shekel:tb:{budget_name}"
        spec_hash = _build_spec_hash(limits, windows)
        argv = _build_argv(spec_hash, amounts, limits, windows)

        if self._is_circuit_open():
            return await self._handle_unavailable(budget_name, RuntimeError("Circuit breaker open"))

        try:
            sha = await self._ensure_script()
            client = await self._ensure_client()
            result = await client.evalsha(sha, 1, key, *argv)
            self._record_success()
        except Exception as exc:
            self._record_error()
            _emit_unavailable(budget_name, exc)
            return await self._handle_unavailable(budget_name, exc)

        status = int(result[0])
        counter_bytes = result[1]
        counter = counter_bytes.decode() if isinstance(counter_bytes, bytes) else str(counter_bytes)

        if status == -2:
            raise BudgetConfigMismatchError(
                f"Budget {budget_name!r} already registered with different limits/windows."
            )
        if status == 0:
            return False, counter or None
        return True, None

    async def _handle_unavailable(
        self, budget_name: str, exc: Exception
    ) -> tuple[bool, str | None]:
        if self._on_unavailable == "open":
            return True, None
        raise BudgetExceededError(
            spent=0.0,
            limit=0.0,
            model="unknown",
            exceeded_counter="backend_unavailable",
        ) from exc

    async def get_state(self, budget_name: str) -> dict[str, float]:
        key = f"shekel:tb:{budget_name}"
        try:
            client = await self._ensure_client()
            raw = await client.hgetall(key)
        except Exception:
            return {}
        result: dict[str, float] = {}
        for field_bytes, val_bytes in raw.items():
            field = field_bytes.decode() if isinstance(field_bytes, bytes) else str(field_bytes)
            if field.endswith(":spent"):
                counter = field[: -len(":spent")]
                try:
                    result[counter] = float(val_bytes)
                except (ValueError, TypeError):
                    pass  # corrupt/non-numeric value — skip
        return result

    async def reset(self, budget_name: str) -> None:
        key = f"shekel:tb:{budget_name}"
        client = await self._ensure_client()
        await client.delete(key)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
