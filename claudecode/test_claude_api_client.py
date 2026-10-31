#!/usr/bin/env python3
"""
Unit tests for ClaudeAPIClient.
"""

from unittest.mock import Mock, patch

from claudecode.claude_api_client import ClaudeAPIClient
from claudecode.constants import DEFAULT_CLAUDE_MODEL
from claudecode.findings_filter import FindingsFilter


class TestValidateAPIAccess:
    """Test that the API access probe uses the configured model."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_probe_uses_configured_model(self, mock_anthropic):
        """The probe must call the model the client was configured with."""
        mock_client = Mock()
        mock_anthropic.return_value = mock_client

        client = ClaudeAPIClient(model='custom-model', api_key='test-key')
        success, error = client.validate_api_access()

        assert success is True
        assert error == ''
        assert mock_client.messages.create.call_args.kwargs['model'] == 'custom-model'

    @patch('claudecode.claude_api_client.Anthropic')
    def test_probe_uses_default_model_when_unset(self, mock_anthropic):
        """With no model configured, the probe falls back to the default model."""
        mock_client = Mock()
        mock_anthropic.return_value = mock_client

        client = ClaudeAPIClient(api_key='test-key')
        client.validate_api_access()

        assert mock_client.messages.create.call_args.kwargs['model'] == DEFAULT_CLAUDE_MODEL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_probe_failure_is_reported(self, mock_anthropic):
        """A failing probe reports the error rather than raising."""
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception('not_found_error')
        mock_anthropic.return_value = mock_client

        client = ClaudeAPIClient(model='custom-model', api_key='test-key')
        success, error = client.validate_api_access()

        assert success is False
        assert 'not_found_error' in error


class TestFindingsFilterProbe:
    """Test that filtering stays enabled when the configured model is valid."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_claude_filtering_stays_enabled(self, mock_anthropic):
        """A model only the caller configures must not disable Claude filtering.

        The probe previously called a hardcoded model. Once that model was
        retired the probe failed, and FindingsFilter silently set
        use_claude_filtering = False on every run.
        """
        mock_client = Mock()
        mock_anthropic.return_value = mock_client

        findings_filter = FindingsFilter(
            use_claude_filtering=True,
            api_key='test-key',
            model='custom-model',
        )

        assert findings_filter.use_claude_filtering is True
        assert findings_filter.claude_client is not None
        assert mock_client.messages.create.call_args.kwargs['model'] == 'custom-model'
