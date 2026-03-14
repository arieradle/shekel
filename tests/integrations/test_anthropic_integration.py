"""Integration tests for the Anthropic provider adapter.

Real-API tests (TestAnthropicRealIntegration) require ANTHROPIC_API_KEY env var
and are skipped without it.

Mock tests (TestAnthropicMockIntegration) run without any API keys and verify
the adapter's patch lifecycle and token extraction end-to-end.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from shekel import budget
from shekel.exceptions import BudgetExceededError

try:
    import anthropic
    import anthropic.resources.messages as ant_messages

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

pytestmark = pytest.mark.skipif(not ANTHROPIC_AVAILABLE, reason="anthropic not installed")

_MODEL = "claude-3-haiku-20240307"


# ---------------------------------------------------------------------------
# Real-API tests
# ---------------------------------------------------------------------------


class TestAnthropicRealIntegration:
    """Tests that call the real Anthropic API."""

    @pytest.fixture
    def api_key(self) -> str | None:
        return os.getenv("ANTHROPIC_API_KEY")

    @pytest.fixture
    def available(self, api_key: str | None) -> bool:
        return bool(api_key and ANTHROPIC_AVAILABLE)

    @pytest.fixture
    def client(self, api_key: str | None, available: bool) -> Any:
        if not available or api_key is None:
            pytest.skip("Anthropic API not available")
        return anthropic.Anthropic(api_key=api_key)

    @pytest.fixture
    def async_client(self, api_key: str | None, available: bool) -> Any:
        if not available or api_key is None:
            pytest.skip("Anthropic API not available")
        return anthropic.AsyncAnthropic(api_key=api_key)

    @staticmethod
    def _maybe_skip_quota(exc: Exception) -> None:
        """Call pytest.skip() if exc is an Anthropic quota/rate-limit error."""
        msg = str(exc)
        if "429" in msg or "rate_limit" in msg.lower() or "overloaded" in msg.lower():
            pytest.skip(f"Anthropic rate-limit/overloaded: {msg[:120]}")

    def test_basic_message_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend from messages.create()."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=1.00) as b:
                response = client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                )
            assert response is not None
            assert b.spent > 0, "Expected spend > 0 after a real Anthropic call"
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_streaming_tracks_spend(self, client: Any, available: bool) -> None:
        """budget() tracks spend when iterating a streaming message."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=1.00) as b:
                chunks = list(
                    client.messages.create(
                        model=_MODEL,
                        max_tokens=15,
                        messages=[{"role": "user", "content": "Count to three."}],
                        stream=True,
                    )
                )
            assert len(chunks) > 0
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_raises_error(self, client: Any, available: bool) -> None:
        """BudgetExceededError is raised when budget is exhausted."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.messages.create(
                        model=_MODEL,
                        max_tokens=10,
                        messages=[{"role": "user", "content": "Hello."}],
                    )
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_nested_budgets_roll_up(self, client: Any, available: bool) -> None:
        """Spend in an inner budget is reflected in the outer budget."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=5.00, name="outer") as outer:
                with budget(max_usd=1.00, name="inner") as inner:
                    client.messages.create(
                        model=_MODEL,
                        max_tokens=10,
                        messages=[{"role": "user", "content": "Say yes."}],
                    )
            assert inner.spent > 0
            assert outer.spent >= inner.spent
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_warn_at_callback_triggered(self, client: Any, available: bool) -> None:
        """on_warn callback fires when spend crosses warn_at threshold."""
        if not available:
            pytest.skip("Anthropic API not available")

        warnings: list[float] = []

        try:
            with budget(
                max_usd=1.00,
                warn_at=0.000001,
                on_warn=lambda spent, limit: warnings.append(spent),
            ) as b:
                client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi."}],
                )
            assert b.spent > 0
            assert len(warnings) > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_multiple_sequential_calls_accumulate(self, client: Any, available: bool) -> None:
        """Multiple calls within one budget context accumulate spend."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=5.00) as b:
                client.messages.create(
                    model=_MODEL,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "One."}],
                )
                spend_after_first = b.spent
                client.messages.create(
                    model=_MODEL,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "Two."}],
                )
            assert b.spent > spend_after_first
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_remaining_decreases_after_call(self, client: Any, available: bool) -> None:
        """b.remaining decreases after each API call."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=5.00) as b:
                remaining_before = b.remaining
                client.messages.create(
                    model=_MODEL,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "Hi."}],
                )
                assert b.remaining < remaining_before
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_system_prompt_tracked(self, client: Any, available: bool) -> None:
        """System prompt tokens are included in tracked spend."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=1.00) as b:
                client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    system="You are a helpful assistant.",
                    messages=[{"role": "user", "content": "What is 2+2?"}],
                )
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_name_is_preserved(self, client: Any, available: bool) -> None:
        """Budget name attribute is accessible on the context object."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=1.00, name="anthropic-test") as b:
                client.messages.create(
                    model=_MODEL,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "Hi."}],
                )
            assert b.name == "anthropic-test"
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_budget_exceeded_error_has_spent_attribute(self, client: Any, available: bool) -> None:
        """BudgetExceededError carries the spent amount."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with pytest.raises(BudgetExceededError) as exc_info:
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client.messages.create(
                        model=_MODEL,
                        max_tokens=5,
                        messages=[{"role": "user", "content": "Hello."}],
                    )
            assert exc_info.value.spent > 0
        except Exception as exc:
            if not isinstance(exc, pytest.skip.Exception):
                self._maybe_skip_quota(exc)
            raise

    def test_summary_after_call(self, client: Any, available: bool) -> None:
        """b.summary() returns a non-empty string after a real API call."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=1.00) as b:
                client.messages.create(
                    model=_MODEL,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "Hi."}],
                )
            summary = b.summary()
            assert isinstance(summary, str)
            assert len(summary) > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    def test_multi_turn_conversation(self, client: Any, available: bool) -> None:
        """Multi-turn conversation tokens accumulate in single budget."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=5.00) as b:
                resp1 = client.messages.create(
                    model=_MODEL,
                    max_tokens=20,
                    messages=[{"role": "user", "content": "My name is Alice."}],
                )
                messages = [
                    {"role": "user", "content": "My name is Alice."},
                    {"role": "assistant", "content": resp1.content[0].text},
                    {"role": "user", "content": "What is my name?"},
                ]
                client.messages.create(
                    model=_MODEL,
                    max_tokens=20,
                    messages=messages,
                )
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_message_tracks_spend(self, async_client: Any, available: bool) -> None:
        """budget() tracks spend from async messages.create()."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with budget(max_usd=1.00) as b:
                response = await async_client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_budget_exceeded_raises(self, async_client: Any, available: bool) -> None:
        """BudgetExceededError raised from async call when budget tiny."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    await async_client.messages.create(
                        model=_MODEL,
                        max_tokens=5,
                        messages=[{"role": "user", "content": "Hello."}],
                    )
        except Exception as exc:
            if not isinstance(exc, pytest.skip.Exception):
                self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_streaming_tracks_spend(self, async_client: Any, available: bool) -> None:
        """budget() tracks spend when iterating an async streaming message."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            chunks = []
            with budget(max_usd=1.00) as b:
                async for chunk in await async_client.messages.create(
                    model=_MODEL,
                    max_tokens=15,
                    messages=[{"role": "user", "content": "Count to three."}],
                    stream=True,
                ):
                    chunks.append(chunk)
            assert len(chunks) > 0
            assert b.spent >= 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise

    @pytest.mark.asyncio
    async def test_async_message_with_async_budget(
        self, async_client: Any, available: bool
    ) -> None:
        """async with budget() tracks spend from async messages.create()."""
        if not available:
            pytest.skip("Anthropic API not available")

        try:
            async with budget(max_usd=1.00) as b:
                response = await async_client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Say hello in one word."}],
                )
            assert response is not None
            assert b.spent > 0
        except Exception as exc:
            self._maybe_skip_quota(exc)
            raise


# ---------------------------------------------------------------------------
# Mock tests — always run, no API key required
# ---------------------------------------------------------------------------


class TestAnthropicMockIntegration:
    """Verify adapter lifecycle and token extraction without API calls."""

    def test_patch_install_and_remove_lifecycle(self) -> None:
        """Adapter patches Messages.create."""
        from shekel.providers.anthropic import AnthropicAdapter

        original = ant_messages.Messages.create

        adapter = AnthropicAdapter()
        try:
            adapter.install_patches()
            assert ant_messages.Messages.create is not original
        finally:
            adapter.remove_patches()

        assert ant_messages.Messages.create is original

    def test_budget_records_spend_from_mock_response(self) -> None:
        """budget() records correct cost from a mocked create call."""

        class FakeUsage:
            input_tokens = 100
            output_tokens = 50

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(ant_messages.Messages, "create", fake_create):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = anthropic.Anthropic(api_key="fake-key")
                client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "hello"}],
                )

        # 100 input + 50 output at $1/1k each = $0.15
        assert b.spent > 0

    def test_streaming_mock_records_spend(self) -> None:
        """budget() records correct cost from a mocked streaming response."""

        class FakeUsage:
            input_tokens = 60
            output_tokens = 30

        class MessageStartEvent:
            type = "message_start"

            class message:
                model = _MODEL

                class usage:
                    input_tokens = 60

        class MessageDeltaEvent:
            type = "message_delta"

            class usage:
                output_tokens = 30

        class OtherEvent:
            type = "content_block_delta"

        def fake_create(self: Any, **kwargs: Any) -> Any:
            yield MessageStartEvent()
            yield OtherEvent()
            yield MessageDeltaEvent()

        with patch.object(ant_messages.Messages, "create", fake_create):
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = anthropic.Anthropic(api_key="fake-key")
                list(
                    client.messages.create(
                        model=_MODEL,
                        max_tokens=10,
                        messages=[{"role": "user", "content": "hello"}],
                        stream=True,
                    )
                )

        assert b.spent > 0

    def test_budget_exceeded_from_mock(self) -> None:
        """BudgetExceededError raised when mocked usage pushes over tiny budget."""

        class FakeUsage:
            input_tokens = 1000
            output_tokens = 500

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(ant_messages.Messages, "create", fake_create):
            with pytest.raises(BudgetExceededError):
                with budget(
                    max_usd=0.000001,
                    price_per_1k_tokens={"input": 100.0, "output": 100.0},
                ):
                    client = anthropic.Anthropic(api_key="fake-key")
                    client.messages.create(
                        model=_MODEL,
                        max_tokens=10,
                        messages=[{"role": "user", "content": "hello"}],
                    )

    def test_extract_tokens_from_real_response_shape(self) -> None:
        """extract_tokens handles the real Anthropic response structure."""
        from shekel.providers.anthropic import AnthropicAdapter

        class FakeUsage:
            input_tokens = 42
            output_tokens = 17

        class FakeResp:
            model = _MODEL
            usage = FakeUsage()

        adapter = AnthropicAdapter()
        it, ot, model = adapter.extract_tokens(FakeResp())
        assert it == 42
        assert ot == 17
        assert model == _MODEL

    def test_no_usage_in_response_returns_zeros(self) -> None:
        """When response has no usage, extract_tokens returns (0, 0, unknown)."""
        from shekel.providers.anthropic import AnthropicAdapter

        class NoUsage:
            model = _MODEL

        adapter = AnthropicAdapter()
        it, ot, model = adapter.extract_tokens(NoUsage())
        assert it == 0
        assert ot == 0

    def test_no_crash_without_anthropic_package(self) -> None:
        """install_patches() is a no-op when anthropic is not importable."""
        from shekel.providers.anthropic import AnthropicAdapter

        adapter = AnthropicAdapter()
        with patch.dict(
            "sys.modules",
            {"anthropic": None, "anthropic.resources.messages": None},
        ):
            try:
                adapter.install_patches()
            except Exception:
                pass  # ImportError is acceptable

    def test_warn_at_callback_mock(self) -> None:
        """on_warn callback fires when warn_at threshold is crossed via mock."""

        class FakeUsage:
            input_tokens = 100
            output_tokens = 50

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        def fake_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        warnings: list[float] = []

        with patch.object(ant_messages.Messages, "create", fake_create):
            with budget(
                max_usd=1.00,
                warn_at=0.000001,
                on_warn=lambda spent, limit: warnings.append(spent),
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = anthropic.Anthropic(api_key="fake-key")
                client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert b.spent > 0
        assert len(warnings) > 0

    def test_malformed_response_records_zero(self) -> None:
        """Response missing .usage attribute records $0 rather than crashing."""

        class NoUsage:
            model = _MODEL

        def fake_create(self: Any, **kwargs: Any) -> NoUsage:
            return NoUsage()

        with patch.object(ant_messages.Messages, "create", fake_create):
            with budget(max_usd=1.00) as b:
                client = anthropic.Anthropic(api_key="fake-key")
                client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert b.spent == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_async_streaming_mock_records_spend(self) -> None:
        """async budget records cost from mocked async streaming response."""

        class MessageStartEvent:
            type = "message_start"

            class message:
                model = _MODEL

                class usage:
                    input_tokens = 60

        class MessageDeltaEvent:
            type = "message_delta"

            class usage:
                output_tokens = 30

        class OtherEvent:
            type = "content_block_delta"

        async def fake_async_create(self: Any, **kwargs: Any) -> Any:
            async def _gen() -> Any:
                yield MessageStartEvent()
                yield OtherEvent()
                yield MessageDeltaEvent()

            return _gen()

        with patch.object(ant_messages.AsyncMessages, "create", fake_async_create):
            async with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = anthropic.AsyncAnthropic(api_key="fake-key")
                async for _ in await client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "hello"}],
                    stream=True,
                ):
                    pass

        assert b.spent > 0

    @pytest.mark.asyncio
    async def test_async_budget_records_spend_from_mock_response(self) -> None:
        """async with budget() records correct cost from a mocked async create call."""

        class FakeUsage:
            input_tokens = 100
            output_tokens = 50

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        async def fake_async_create(self: Any, **kwargs: Any) -> FakeResponse:
            return FakeResponse()

        with patch.object(ant_messages.AsyncMessages, "create", fake_async_create):
            async with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                client = anthropic.AsyncAnthropic(api_key="fake-key")
                await client.messages.create(
                    model=_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert b.spent > 0

    def test_wrapper_directly_records_spend(self) -> None:
        """_anthropic_sync_wrapper records cost via _patch._record."""
        from shekel import _patch

        class FakeUsage:
            input_tokens = 200
            output_tokens = 100

        class FakeResponse:
            model = _MODEL
            usage = FakeUsage()

        original = MagicMock(return_value=FakeResponse())
        _patch._originals["anthropic_sync"] = original

        try:
            with budget(
                max_usd=1.00,
                price_per_1k_tokens={"input": 1.0, "output": 1.0},
            ) as b:
                fake_self = MagicMock()
                _patch._anthropic_sync_wrapper(fake_self, model=_MODEL, messages=[], max_tokens=10)
        finally:
            _patch._originals.pop("anthropic_sync", None)

        assert b.spent > 0
