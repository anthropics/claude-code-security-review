#!/usr/bin/env python3
"""
Comprehensive tests for multi-provider Claude Code functionality.
"""

import os
import pytest
from unittest.mock import patch
from claudecode.claude_client_factory import create_claude_client
from claudecode.env_validation import (
    validate_environment_variables, get_provider_type
)
from claudecode.claude_client_base import ClaudeClientBase


class TestEnvironmentValidation:
    """Test environment variable validation."""

    def test_anthropic_api_key_validation(self):
        """Test validation with Anthropic API key."""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
        }, clear=True):
            validate_environment_variables()  # Should not raise

    def test_claude_oauth_token_validation(self):
        """Test validation with Claude OAuth token."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_OAUTH_TOKEN': 'test-token',
        }, clear=True):
            validate_environment_variables()  # Should not raise

    def test_bedrock_validation(self):
        """Test validation for Bedrock provider."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_BEDROCK': '1',
            'AWS_REGION': 'us-east-1',
            'AWS_ACCESS_KEY_ID': 'test-key',
            'AWS_SECRET_ACCESS_KEY': 'test-secret'
        }, clear=True):
            validate_environment_variables()  # Should not raise

    def test_vertex_validation(self):
        """Test validation for Vertex AI provider."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_VERTEX': '1',
            'ANTHROPIC_VERTEX_PROJECT_ID': 'test-project',
            'CLOUD_ML_REGION': 'us-central1'
        }, clear=True):
            validate_environment_variables()  # Should not raise

    def test_missing_anthropic_credentials(self):
        """Test that missing Anthropic credentials raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError,
                match="Either ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN"
            ):
                validate_environment_variables()

    def test_both_providers_enabled_error(self):
        """Test that enabling both Bedrock and Vertex raises error."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_BEDROCK': '1',
            'CLAUDE_CODE_USE_VERTEX': '1'
        }, clear=True):
            with pytest.raises(
                ValueError, match="Cannot use both Bedrock and Vertex AI"
            ):
                validate_environment_variables()

    def test_missing_bedrock_credentials(self):
        """Test that missing Bedrock credentials raises ValueError."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_BEDROCK': '1'
        }, clear=True):
            with pytest.raises(
                ValueError,
                match="AWS_REGION is required when using AWS Bedrock"
            ):
                validate_environment_variables()

    def test_missing_vertex_credentials(self):
        """Test that missing Vertex credentials raises ValueError."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_VERTEX': '1'
        }, clear=True):
            with pytest.raises(
                ValueError, match="ANTHROPIC_VERTEX_PROJECT_ID is required"
            ):
                validate_environment_variables()


class TestProviderType:
    """Test provider type detection."""

    def test_bedrock_provider_type(self):
        """Test Bedrock provider detection."""
        with patch.dict(
            os.environ, {'CLAUDE_CODE_USE_BEDROCK': '1'}, clear=True
        ):
            assert get_provider_type() == "bedrock"

    def test_vertex_provider_type(self):
        """Test Vertex AI provider detection."""
        with patch.dict(
            os.environ, {'CLAUDE_CODE_USE_VERTEX': '1'}, clear=True
        ):
            assert get_provider_type() == "vertex"

    def test_anthropic_provider_type(self):
        """Test default Anthropic provider detection."""
        with patch.dict(os.environ, {}, clear=True):
            assert get_provider_type() == "anthropic"


class TestClientFactory:
    """Test Claude client factory."""

    @patch('claudecode.env_validation.validate_environment_variables')
    @patch('claudecode.env_validation.get_provider_type')
    def test_create_anthropic_client(self, mock_get_provider, mock_validate):
        """Test creating Anthropic API client."""
        mock_get_provider.return_value = "anthropic"

        with patch(
            'claudecode.claude_api_client.ClaudeAPIClient'
        ) as mock_client:
            create_claude_client()
            mock_client.assert_called_once()

    @patch('claudecode.env_validation.validate_environment_variables')
    @patch('claudecode.env_validation.get_provider_type')
    def test_create_bedrock_client(self, mock_get_provider, mock_validate):
        """Test creating Bedrock client."""
        mock_get_provider.return_value = "bedrock"

        with patch(
            'claudecode.claude_bedrock_client.ClaudeBedrockClient'
        ) as mock_client:
            create_claude_client()
            mock_client.assert_called_once()

    @patch('claudecode.env_validation.validate_environment_variables')
    @patch('claudecode.env_validation.get_provider_type')
    def test_create_vertex_client(self, mock_get_provider, mock_validate):
        """Test creating Vertex AI client."""
        mock_get_provider.return_value = "vertex"

        with patch(
            'claudecode.claude_vertex_client.ClaudeVertexClient'
        ) as mock_client:
            create_claude_client()
            mock_client.assert_called_once()

    @patch('claudecode.env_validation.validate_environment_variables')
    @patch('claudecode.env_validation.get_provider_type')
    def test_unsupported_provider_error(
        self, mock_get_provider, mock_validate
    ):
        """Test error for unsupported provider."""
        mock_get_provider.return_value = "unsupported"

        with pytest.raises(ValueError, match="Unsupported provider type"):
            create_claude_client()


class TestBaseClientInterface:
    """Test the base client interface implementation."""

    def test_analyze_single_finding_success(self):
        """Test successful single finding analysis."""
        # Create a mock client that inherits from ClaudeClientBase
        class MockClient(ClaudeClientBase):
            def validate_api_access(self):
                return True, ""

            def call_with_retry(
                self, prompt, system_prompt=None, max_tokens=16384
            ):
                return (
                    True,
                    '{"keep_finding": true, "confidence_score": 8}',
                    ""
                )

        client = MockClient()
        finding = {"rule": "test-rule", "file": "test.py", "line": 1}

        success, result, error = client.analyze_single_finding(finding)
        assert success is True
        assert "keep_finding" in result
        assert error == ""

    def test_analyze_single_finding_api_failure(self):
        """Test single finding analysis with API failure."""
        class MockClient(ClaudeClientBase):
            def validate_api_access(self):
                return True, ""

            def call_with_retry(
                self, prompt, system_prompt=None, max_tokens=16384
            ):
                return False, "", "API call failed"

        client = MockClient()
        finding = {"rule": "test-rule", "file": "test.py", "line": 1}

        success, result, error = client.analyze_single_finding(finding)
        assert success is False
        assert result == {}
        assert "API call failed" in error


if __name__ == "__main__":
    pytest.main([__file__])
