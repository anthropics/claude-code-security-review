#!/usr/bin/env python3
"""
Unit tests for ClaudeAPIClient Anthropic-compatible provider support.

These tests cover routing the Claude API client through an Anthropic-compatible
provider endpoint (for example the MiniMax Anthropic-compatible endpoint) via an
optional base_url. The endpoint URLs and model identifiers exercised here are
taken from the target provider configuration rather than hardcoded in product
code.
"""

from unittest.mock import patch

import pytest

from claudecode.claude_api_client import ClaudeAPIClient, get_claude_api_client
from claudecode.constants import DEFAULT_CLAUDE_MODEL


# Target provider configuration (Anthropic-compatible regional endpoints and
# model identifiers). These values come from the provider configuration and are
# used here only to verify the client forwards them correctly.
MINIMAX_GLOBAL_BASE_URL = "https://api.minimax.io/anthropic"
MINIMAX_CHINA_BASE_URL = "https://api.minimaxi.com/anthropic"
MINIMAX_MODEL_IDS = ["MiniMax-M3", "MiniMax-M2.7"]


class TestClaudeAPIClientBaseUrl:
    """Test Anthropic-compatible base URL support."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_init_forwards_base_url_parameter(self, mock_anthropic):
        """A base_url parameter is forwarded to the Anthropic client."""
        ClaudeAPIClient(
            api_key="test-key",
            base_url=MINIMAX_GLOBAL_BASE_URL,
        )

        _, kwargs = mock_anthropic.call_args
        assert kwargs["api_key"] == "test-key"
        assert kwargs["base_url"] == MINIMAX_GLOBAL_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_init_uses_default_base_url_when_no_param(self, mock_anthropic):
        """When no base_url is given the module default (ANTHROPIC_BASE_URL) is used."""
        with patch(
            'claudecode.claude_api_client.DEFAULT_ANTHROPIC_BASE_URL',
            MINIMAX_CHINA_BASE_URL,
        ):
            client = ClaudeAPIClient(api_key="test-key")

        assert client.base_url == MINIMAX_CHINA_BASE_URL
        _, kwargs = mock_anthropic.call_args
        assert kwargs["base_url"] == MINIMAX_CHINA_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_init_omits_base_url_when_unset(self, mock_anthropic):
        """When no base_url is configured the Anthropic default endpoint is used."""
        with patch(
            'claudecode.claude_api_client.DEFAULT_ANTHROPIC_BASE_URL',
            None,
        ):
            client = ClaudeAPIClient(api_key="test-key")

        assert client.base_url is None
        _, kwargs = mock_anthropic.call_args
        assert "base_url" not in kwargs

    @patch('claudecode.claude_api_client.Anthropic')
    @pytest.mark.parametrize("model_id", MINIMAX_MODEL_IDS)
    def test_init_supports_provider_model_ids(self, mock_anthropic, model_id):
        """Model identifiers from the target provider config are accepted."""
        client = ClaudeAPIClient(
            api_key="test-key",
            base_url=MINIMAX_GLOBAL_BASE_URL,
            model=model_id,
        )

        assert client.model == model_id
        assert client.base_url == MINIMAX_GLOBAL_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    @pytest.mark.parametrize("base_url", [MINIMAX_GLOBAL_BASE_URL, MINIMAX_CHINA_BASE_URL])
    def test_init_supports_regional_endpoints(self, mock_anthropic, base_url):
        """Both regional Anthropic-compatible endpoints are forwarded."""
        client = ClaudeAPIClient(api_key="test-key", base_url=base_url)

        assert client.base_url == base_url
        _, kwargs = mock_anthropic.call_args
        assert kwargs["base_url"] == base_url

    @patch('claudecode.claude_api_client.Anthropic')
    def test_parameter_base_url_overrides_default(self, mock_anthropic):
        """An explicit base_url parameter takes precedence over the default."""
        with patch(
            'claudecode.claude_api_client.DEFAULT_ANTHROPIC_BASE_URL',
            MINIMAX_CHINA_BASE_URL,
        ):
            client = ClaudeAPIClient(
                api_key="test-key",
                base_url=MINIMAX_GLOBAL_BASE_URL,
            )

        assert client.base_url == MINIMAX_GLOBAL_BASE_URL
        _, kwargs = mock_anthropic.call_args
        assert kwargs["base_url"] == MINIMAX_GLOBAL_BASE_URL


class TestGetClaudeAPIClient:
    """Test the convenience factory forwards base_url."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_get_claude_api_client_forwards_base_url(self, mock_anthropic):
        """The factory forwards an Anthropic-compatible base URL."""
        client = get_claude_api_client(
            api_key="test-key",
            base_url=MINIMAX_GLOBAL_BASE_URL,
            model=MINIMAX_MODEL_IDS[0],
        )

        assert client.base_url == MINIMAX_GLOBAL_BASE_URL
        assert client.model == MINIMAX_MODEL_IDS[0]
        _, kwargs = mock_anthropic.call_args
        assert kwargs["base_url"] == MINIMAX_GLOBAL_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_get_claude_api_client_defaults_model(self, mock_anthropic):
        """The factory still defaults the model when none is provided."""
        with patch(
            'claudecode.claude_api_client.DEFAULT_ANTHROPIC_BASE_URL',
            None,
        ):
            client = get_claude_api_client(api_key="test-key")

        assert client.model == DEFAULT_CLAUDE_MODEL
        _, kwargs = mock_anthropic.call_args
        assert "base_url" not in kwargs


class TestClaudeAPIClientProviderRegistry:
    """Test resolving endpoints and model facts through the provider registry."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_provider_resolves_default_region_base_url(self, mock_anthropic):
        """A provider name resolves the default region Anthropic-compatible URL."""
        client = ClaudeAPIClient(
            api_key="test-key",
            provider="minimax",
            model="MiniMax-M3",
        )

        assert client.provider == "minimax"
        assert client.base_url == MINIMAX_GLOBAL_BASE_URL
        _, kwargs = mock_anthropic.call_args
        assert kwargs["base_url"] == MINIMAX_GLOBAL_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_provider_resolves_default_model(self, mock_anthropic):
        """A provider name uses its default model when no model is supplied."""
        client = ClaudeAPIClient(
            api_key="test-key",
            provider="minimax",
        )

        assert client.model == "MiniMax-M3"

    @pytest.mark.parametrize(
        "kwargs,error",
        [
            ({"provider": "unknown"}, "Unknown Anthropic-compatible provider"),
            (
                {"provider": "minimax", "region": "unknown"},
                "Unknown region unknown for provider minimax",
            ),
            (
                {"provider": "minimax", "model": "unknown"},
                "Model unknown is not registered for provider minimax",
            ),
        ],
    )
    def test_provider_rejects_unknown_configuration(self, kwargs, error):
        """Unknown provider configuration fails instead of using Anthropic defaults."""
        with pytest.raises(ValueError, match=error):
            ClaudeAPIClient(api_key="test-key", **kwargs)

    @patch('claudecode.claude_api_client.Anthropic')
    def test_provider_resolves_regional_base_url(self, mock_anthropic):
        """A region selects the matching Anthropic-compatible endpoint."""
        client = ClaudeAPIClient(
            api_key="test-key",
            provider="minimax",
            region="cn_zh",
            model="MiniMax-M2.7",
        )

        assert client.region == "cn_zh"
        assert client.base_url == MINIMAX_CHINA_BASE_URL
        _, kwargs = mock_anthropic.call_args
        assert kwargs["base_url"] == MINIMAX_CHINA_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_explicit_base_url_overrides_provider(self, mock_anthropic):
        """An explicit base_url takes precedence over the provider registry."""
        client = ClaudeAPIClient(
            api_key="test-key",
            base_url=MINIMAX_GLOBAL_BASE_URL,
            provider="minimax",
            region="cn_zh",
        )

        assert client.base_url == MINIMAX_GLOBAL_BASE_URL

    @patch('claudecode.claude_api_client.Anthropic')
    def test_get_claude_api_client_forwards_provider(self, mock_anthropic):
        """The factory forwards provider and region to the client."""
        client = get_claude_api_client(
            api_key="test-key",
            provider="minimax",
            region="cn_zh",
            model="MiniMax-M3",
        )

        assert client.provider == "minimax"
        assert client.region == "cn_zh"
        assert client.base_url == MINIMAX_CHINA_BASE_URL
        assert client.model == "MiniMax-M3"
