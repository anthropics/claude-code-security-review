#!/usr/bin/env python3
"""
Tests for model configuration propagation.

Verifies that:
1. validate_api_access() uses self.model (not a hardcoded model string)
2. model parameter flows from FindingsFilter through to ClaudeAPIClient
3. GitHub Actions ::warning:: annotation is emitted when API validation fails
"""

import os
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

        # Extract the model kwarg from the messages.create call
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs is not None, "messages.create was not called"
        used_model = call_kwargs.kwargs.get("model") or call_kwargs[1].get("model")
        assert used_model == custom_model, (
            f"Expected model '{custom_model}' but got '{used_model}'. "
            "validate_api_access() may still be using a hardcoded model."
        )

    @patch("claudecode.claude_api_client.Anthropic")
    def test_validate_uses_default_model_when_none_provided(self, mock_anthropic_cls):
        """When no model is specified, validate_api_access should use DEFAULT_CLAUDE_MODEL."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from claudecode.claude_api_client import ClaudeAPIClient

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = ClaudeAPIClient(api_key="test-key")

        client.validate_api_access()

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs is not None
        used_model = call_kwargs.kwargs.get("model") or call_kwargs[1].get("model")
        assert used_model == DEFAULT_CLAUDE_MODEL, (
            f"Expected default model '{DEFAULT_CLAUDE_MODEL}' but got '{used_model}'."
        )

    @patch("claudecode.claude_api_client.Anthropic")
    def test_validate_does_not_use_hardcoded_haiku(self, mock_anthropic_cls):
        """Regression: validate_api_access must never use the old hardcoded haiku model."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        from claudecode.claude_api_client import ClaudeAPIClient

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = ClaudeAPIClient(api_key="test-key")

        client.validate_api_access()

        call_kwargs = mock_client.messages.create.call_args
        used_model = call_kwargs.kwargs.get("model") or call_kwargs[1].get("model")
        assert used_model != "claude-3-5-haiku-20241022", (
            "validate_api_access() is still using the deprecated hardcoded "
            "'claude-3-5-haiku-20241022' model."
        )


class TestModelFlowsThroughFindingsFilter:
    """Test that model parameter propagates from FindingsFilter to ClaudeAPIClient."""

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_model_passed_to_claude_client(self, mock_client_cls):
        """FindingsFilter should pass its model parameter to ClaudeAPIClient."""
        mock_instance = MagicMock()
        mock_instance.validate_api_access.return_value = (True, "")
        mock_client_cls.return_value = mock_instance

        from claudecode.findings_filter import FindingsFilter

        custom_model = "claude-sonnet-4-20250514"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            FindingsFilter(
                use_claude_filtering=True,
                api_key="test-key",
                model=custom_model,
            )

        mock_client_cls.assert_called_once_with(
            model=custom_model,
            api_key="test-key",
        )

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_default_model_used_when_not_specified(self, mock_client_cls):
        """FindingsFilter should use DEFAULT_CLAUDE_MODEL when model is not specified."""
        mock_instance = MagicMock()
        mock_instance.validate_api_access.return_value = (True, "")
        mock_client_cls.return_value = mock_instance

        from claudecode.findings_filter import FindingsFilter

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            FindingsFilter(
                use_claude_filtering=True,
                api_key="test-key",
            )

        mock_client_cls.assert_called_once_with(
            model=DEFAULT_CLAUDE_MODEL,
            api_key="test-key",
        )


class TestInitializeFindingsFilterPassesModel:
    """Test that initialize_findings_filter passes model to FindingsFilter."""

    @patch("claudecode.github_action_audit.FindingsFilter")
    def test_model_passed_when_claude_filtering_enabled(self, mock_filter_cls):
        """initialize_findings_filter should pass DEFAULT_CLAUDE_MODEL to FindingsFilter."""
        mock_filter_cls.return_value = MagicMock()

        from claudecode.github_action_audit import initialize_findings_filter

        with patch.dict(os.environ, {
            "ENABLE_CLAUDE_FILTERING": "true",
            "ANTHROPIC_API_KEY": "test-key",
        }):
            initialize_findings_filter()

        call_kwargs = mock_filter_cls.call_args.kwargs
        assert "model" in call_kwargs, (
            "initialize_findings_filter() does not pass 'model' to FindingsFilter"
        )
        assert call_kwargs["model"] == DEFAULT_CLAUDE_MODEL


class TestWarningOnValidationFailure:
    """Test that a GitHub Actions ::warning:: annotation is emitted on API validation failure."""

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_warning_annotation_printed_on_validation_failure(self, mock_client_cls, capsys):
        """When API validation fails, a ::warning:: annotation should be printed to stdout."""
        mock_instance = MagicMock()
        mock_instance.validate_api_access.return_value = (False, "model not found")
        mock_client_cls.return_value = mock_instance

        from claudecode.findings_filter import FindingsFilter

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            f = FindingsFilter(
                use_claude_filtering=True,
                api_key="test-key",
            )

        captured = capsys.readouterr()
        assert "::warning::" in captured.out, (
            "Expected GitHub Actions ::warning:: annotation in stdout"
        )
        assert "filtering is disabled" in captured.out.lower()

        # Also verify filtering was disabled
        assert f.use_claude_filtering is False
        assert f.claude_client is None

    @patch("claudecode.findings_filter.ClaudeAPIClient")
    def test_no_warning_when_validation_succeeds(self, mock_client_cls, capsys):
        """When API validation succeeds, no ::warning:: annotation should be printed."""
        mock_instance = MagicMock()
        mock_instance.validate_api_access.return_value = (True, "")
        mock_client_cls.return_value = mock_instance

        from claudecode.findings_filter import FindingsFilter

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            f = FindingsFilter(
                use_claude_filtering=True,
                api_key="test-key",
            )

        captured = capsys.readouterr()
        assert "::warning::" not in captured.out

        # Filtering should still be enabled
        assert f.use_claude_filtering is True
