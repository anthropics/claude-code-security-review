from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from claudecode import claude_api_client
from claudecode.constants import DEFAULT_MAX_RETRIES


@pytest.mark.parametrize("configured,attempts", [(0, 1), (1, 2), (None, DEFAULT_MAX_RETRIES + 1)])
def test_failed_calls_respect_the_wrapper_retry_limit(monkeypatch, configured, attempts):
    sdk = Mock()
    sdk.messages.create.side_effect = RuntimeError("request failed")
    monkeypatch.setattr(claude_api_client, "Anthropic", Mock(return_value=sdk))
    monkeypatch.setattr(claude_api_client.time, "sleep", Mock())
    client = claude_api_client.ClaudeAPIClient(api_key="test-key", max_retries=configured)
    success, text, error = client.call_with_retry("test prompt")
    assert success is False
    assert text == ""
    assert sdk.messages.create.call_count == attempts
    assert f"after {attempts} attempts" in error


def test_zero_retries_still_performs_the_initial_successful_call(monkeypatch):
    sdk = Mock()
    sdk.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(text="ok")])
    monkeypatch.setattr(claude_api_client, "Anthropic", Mock(return_value=sdk))
    client = claude_api_client.ClaudeAPIClient(api_key="test-key", max_retries=0)
    assert client.call_with_retry("test prompt") == (True, "ok", "")
    sdk.messages.create.assert_called_once()
