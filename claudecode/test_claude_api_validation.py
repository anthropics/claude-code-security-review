from types import SimpleNamespace
from unittest.mock import Mock

from claudecode import claude_api_client


def test_validate_api_access_uses_configured_model(monkeypatch):
    sdk = Mock()
    sdk.messages.create.return_value = SimpleNamespace()
    anthropic_factory = Mock(return_value=sdk)
    monkeypatch.setattr(claude_api_client, "Anthropic", anthropic_factory)

    client = claude_api_client.ClaudeAPIClient(
        model="claude-sonnet-4-20250514",
        api_key="test-key",
    )

    assert client.validate_api_access() == (True, "")
    sdk.messages.create.assert_called_once_with(
        model="claude-sonnet-4-20250514",
        max_tokens=10,
        messages=[{"role": "user", "content": "Hello"}],
        timeout=10,
    )
