from __future__ import annotations

from unittest.mock import patch

import pytest

from shekel import budget
from shekel._patch import _record

OPENAI_CREATE = "openai.resources.chat.completions.Completions.create"
ANTHROPIC_CREATE = "anthropic.resources.messages.Messages.create"


def test_record_with_no_active_budget_is_noop() -> None:
    """_record outside a budget() context should return silently."""
    _record(100, 50, "gpt-4o")


def test_record_unknown_model_falls_back_to_zero_cost() -> None:
    """Unknown model with no price override records $0 rather than crashing."""
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.model = "gpt-999-not-real"
    fake.usage.prompt_tokens = 100
    fake.usage.completion_tokens = 50

    with patch(OPENAI_CREATE, return_value=fake):
        with budget(max_usd=1.00) as b:
            import openai

            client = openai.OpenAI(api_key="test")
            client.chat.completions.create(model="gpt-999-not-real", messages=[])

    assert b.spent == pytest.approx(0.0)


def test_anthropic_malformed_response_records_zero() -> None:
    """Response missing .usage attribute records $0 rather than crashing."""

    class NoUsage:
        model = "claude-3-5-sonnet-20241022"

    with patch(ANTHROPIC_CREATE, return_value=NoUsage()):
        with budget(max_usd=1.00) as b:
            import anthropic

            client = anthropic.Anthropic(api_key="test")
            client.messages.create(model="claude-3-5-sonnet-20241022", messages=[], max_tokens=10)

    assert b.spent == pytest.approx(0.0)
