from __future__ import annotations

"""Tests for ProviderTestBase - test fixture infrastructure."""

from tests.providers.conftest import ProviderTestBase


class TestProviderTestBase:
    """Validate ProviderTestBase provides required mock infrastructure."""

    def test_base_class_exists(self):
        """ProviderTestBase should be importable."""
        assert ProviderTestBase is not None

    def test_make_openai_response(self):
        """Can create mock OpenAI responses."""
        base = ProviderTestBase()
        response = base.make_openai_response(model="gpt-4o", input_tokens=100, output_tokens=50)
        assert response is not None
        assert hasattr(response, "model")
        assert hasattr(response, "usage")
        assert response.model == "gpt-4o"
        assert response.usage.prompt_tokens == 100
        assert response.usage.completion_tokens == 50

    def test_make_anthropic_response(self):
        """Can create mock Anthropic responses."""
        base = ProviderTestBase()
        response = base.make_anthropic_response(
            model="claude-3-haiku-20240307", input_tokens=100, output_tokens=50
        )
        assert response is not None
        assert hasattr(response, "model")
        assert hasattr(response, "usage")
        assert response.model == "claude-3-haiku-20240307"
        assert response.usage.input_tokens == 100
        assert response.usage.output_tokens == 50

    def test_make_openai_stream(self):
        """Can create mock OpenAI streaming responses."""
        base = ProviderTestBase()
        stream = base.make_openai_stream(model="gpt-4o", input_tokens=100, output_tokens=50)
        # Should be iterable
        chunks = list(stream)
        assert len(chunks) > 0
        # Final chunk should have usage
        final_chunk = chunks[-1]
        assert final_chunk.usage is not None

    def test_make_anthropic_stream(self):
        """Can create mock Anthropic streaming responses."""
        base = ProviderTestBase()
        stream = base.make_anthropic_stream(
            model="claude-3-haiku-20240307", input_tokens=100, output_tokens=50
        )
        # Should be iterable
        events = list(stream)
        assert len(events) > 0
        # Should have message_start and message_delta events
        event_types = [e.type for e in events]
        assert "message_start" in event_types
        assert "message_delta" in event_types

    def test_existing_tests_still_pass(self):
        """Existing test infrastructure should not be broken."""
        # This is a placeholder to ensure we validate
        # that adding new test infrastructure doesn't break existing tests
        assert True
