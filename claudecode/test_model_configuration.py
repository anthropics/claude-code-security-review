#!/usr/bin/env python3
"""
Tests for model configuration propagation.

Verifies that:
1. validate_api_access() uses self.model (not a hardcoded model string)
2. model parameter flows from FindingsFilter through to ClaudeAPIClient
3. GitHub Actions ::warning:: annotation is emitted when API validation fails
"""

import io
import os
import sys
from unittest.mock import Mock, patch, MagicMock

import pytest

from claudecode.constants import DEFAULT_CLAUDE_MODEL


class TestValidateApiAccessUsesConfiguredModel:
    """Test that validate_api_access() uses self.model instead of a hardcoded value."""

    @patch("claudecode.claude_api_client.Anthropic")
    def test_validate_uses_self_model(self, mock_anthropic_cls):
        """validate_api_access should pass self.model to messages.create, not a hardcoded string."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from claudecode.claude_api_client import ClaudeAPIClient

        custom_model = "claude-sonnet-4-20250514"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = ClaudeAPIClient(model=custom_model, api_key="test-key")
            client.validate_api_access()

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == custom_model

    @patch("claudecode.claude_api_client.Anthropic")
    def test_validate_never_uses_deprecated_haiku(self, mock_anthropic_cls):
        """Regression: validate_api_access must never send the hardcoded deprecated model."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from claudecode.claude_api_client import ClaudeAPIClient

        deprecated = "claude-3-5-haiku-20241022"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = ClaudeAPIClient(model=DEFAULT_CLAUDE_MODEL, api_key="test-key")
            client.validate_api_access()

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] != deprecated

    @patch("claudecode.claude_api_client.Anthropic")
    def test_validate_uses_default_model_when_none_specified(self, mock_anthropic_cls):
        """When model is not specified, validate_api_access should use DEFAULT_CLAUDE_MODEL."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from claudecode.claude_api_client import ClaudeAPIClient

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = ClaudeAPIClient(api_key="test-key")
            client.validate_api_access()

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == DEFAULT_CLAUDE_MODEL


class TestModelFlowsThroughFindingsFilter:
    """Test that model propagates from initialize_findings_filter to ClaudeAPIClient."""

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_model_reaches_claude_api_client(self, mock_client_cls):
        """Model passed to FindingsFilter should reach ClaudeAPIClient.__init__."""
        mock_client_cls.return_value.validate_api_access.return_value = (True, "")

        from claudecode.findings_filter import FindingsFilter

        test_model = "claude-opus-4-5"
        FindingsFilter(
            use_hard_exclusions=True,
            use_claude_filtering=True,
            api_key="test-key",
            model=test_model,
        )

        call_kwargs = mock_client_cls.call_args[1]
        assert call_kwargs["model"] == test_model

    @patch("claudecode.github_action_audit.FindingsFilter")
    def test_initialize_findings_filter_passes_model(self, mock_filter_cls):
        """initialize_findings_filter must pass model= to FindingsFilter."""
        mock_filter_cls.return_value = MagicMock()

        from claudecode.github_action_audit import initialize_findings_filter

        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "test-key",
            "ENABLE_CLAUDE_FILTERING": "true",
        }):
            initialize_findings_filter()

        call_kwargs = mock_filter_cls.call_args[1]
        assert "model" in call_kwargs
        assert call_kwargs["model"] == DEFAULT_CLAUDE_MODEL


class TestWarningAnnotationOnValidationFailure:
    """Test that a GitHub Actions ::warning:: annotation is emitted when API validation fails."""

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_warning_annotation_emitted(self, mock_client_cls):
        """When validate_api_access fails, a ::warning:: annotation should be printed."""
        mock_client_cls.return_value.validate_api_access.return_value = (
            False, "model_not_found: the model is deprecated"
        )

        from claudecode.findings_filter import FindingsFilter

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            FindingsFilter(
                use_hard_exclusions=True,
                use_claude_filtering=True,
                api_key="test-key",
                model=DEFAULT_CLAUDE_MODEL,
            )

        output = captured.getvalue()
        assert "::warning::" in output

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_filtering_disabled_on_validation_failure(self, mock_client_cls):
        """When validation fails, use_claude_filtering must be False."""
        mock_client_cls.return_value.validate_api_access.return_value = (False, "bad key")

        from claudecode.findings_filter import FindingsFilter

        with patch("sys.stdout", io.StringIO()):
            f = FindingsFilter(
                use_hard_exclusions=True,
                use_claude_filtering=True,
                api_key="test-key",
                model=DEFAULT_CLAUDE_MODEL,
            )

        assert not f.use_claude_filtering
        assert f.claude_client is None
