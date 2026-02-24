#!/usr/bin/env python3
"""
Pytest tests for Claude API client.
"""

from unittest.mock import patch, MagicMock

from claudecode.claude_api_client import ClaudeAPIClient
from claudecode.constants import VALIDATION_MODEL


class TestValidateApiAccess:
    """Test validate_api_access uses VALIDATION_MODEL for cheap validation pings."""

    def test_validate_api_access_uses_validation_model(self):
        """Ensure validate_api_access uses VALIDATION_MODEL, not self.model."""
        custom_model = "claude-sonnet-4-20250514"
        client = ClaudeAPIClient(model=custom_model, api_key="fake-key")

        mock_response = MagicMock()
        with patch.object(client.client.messages, "create", return_value=mock_response) as mock_create:
            success, error = client.validate_api_access()

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model"] == VALIDATION_MODEL, (
            f"Expected VALIDATION_MODEL '{VALIDATION_MODEL}', got '{call_kwargs['model']}'"
        )
        assert success is True
        assert error == ""

    def test_validate_api_access_does_not_use_instance_model(self):
        """Ensure validate_api_access does not pass self.model (expensive) to the validation call."""
        expensive_model = "claude-opus-4-1-20250805"
        client = ClaudeAPIClient(model=expensive_model, api_key="fake-key")

        mock_response = MagicMock()
        with patch.object(client.client.messages, "create", return_value=mock_response) as mock_create:
            success, _ = client.validate_api_access()

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model"] == VALIDATION_MODEL
        assert call_kwargs["model"] != expensive_model
        assert success is True
