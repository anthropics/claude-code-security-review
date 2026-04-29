"""Unit tests for ClaudeAPIClient — covering both direct API and Vertex paths."""

import os
from unittest.mock import patch, MagicMock

import pytest

from claudecode.claude_api_client import ClaudeAPIClient


class TestClaudeAPIClientDirect:
    """Tests for the default api.anthropic.com path."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_init_with_api_key(self, mock_anthropic):
        client = ClaudeAPIClient(api_key='sk-test-123')
        assert client.api_key == 'sk-test-123'
        assert client.use_vertex is False
        mock_anthropic.assert_called_once_with(api_key='sk-test-123')

    @patch('claudecode.claude_api_client.Anthropic')
    def test_init_reads_env_api_key(self, mock_anthropic):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-env-456'}, clear=True):
            client = ClaudeAPIClient()
            assert client.api_key == 'sk-env-456'

    def test_init_raises_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match='No Anthropic API key'):
                ClaudeAPIClient()


class TestClaudeAPIClientVertex:
    """Tests for the Vertex AI path."""

    @patch('claudecode.claude_api_client.AnthropicVertex')
    def test_init_with_vertex_args(self, mock_vertex):
        client = ClaudeAPIClient(
            use_vertex=True,
            vertex_region='us-east5',
            vertex_project_id='my-project',
        )
        assert client.use_vertex is True
        assert client.api_key is None
        mock_vertex.assert_called_once_with(region='us-east5', project_id='my-project')

    @patch('claudecode.claude_api_client.AnthropicVertex')
    def test_init_reads_vertex_env(self, mock_vertex):
        with patch.dict(os.environ, {
            'ANTHROPIC_VERTEX_PROJECT_ID': 'env-project',
            'CLOUD_ML_REGION': 'global',
        }, clear=True):
            client = ClaudeAPIClient(use_vertex=True)
            assert client.use_vertex is True
            mock_vertex.assert_called_once_with(region='global', project_id='env-project')

    @patch('claudecode.claude_api_client.AnthropicVertex')
    def test_init_defaults_region_to_global(self, mock_vertex):
        with patch.dict(os.environ, {}, clear=True):
            ClaudeAPIClient(use_vertex=True, vertex_project_id='my-project')
            mock_vertex.assert_called_once_with(region='global', project_id='my-project')

    def test_init_raises_without_vertex_project(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match='Vertex AI mode requires a project ID'):
                ClaudeAPIClient(use_vertex=True)

    @patch('claudecode.claude_api_client.AnthropicVertex')
    def test_validate_api_access_skipped_in_vertex_mode(self, mock_vertex):
        """Vertex mode should skip the proactive validation call (no test model
        guaranteed to be enabled in caller's GCP project)."""
        mock_client = MagicMock()
        mock_vertex.return_value = mock_client
        client = ClaudeAPIClient(use_vertex=True, vertex_project_id='my-project')

        ok, err = client.validate_api_access()

        assert ok is True
        assert err == ''
        # No call to messages.create on the underlying client.
        mock_client.messages.create.assert_not_called()
