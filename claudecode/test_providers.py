#!/usr/bin/env python3
"""
Unit tests for the Anthropic-compatible provider registry.

These tests verify the provider registry exposes the regional Anthropic-compatible
endpoints and the per-model facts (context window, pricing, input modalities and
thinking modes) for the MiniMax provider.
"""

import pytest

from claudecode.providers import (
    PROVIDERS,
    get_anthropic_base_url,
    get_openai_base_url,
    get_provider,
    get_provider_model,
    get_provider_models,
    get_regional_endpoints,
    list_providers,
)


# Expected regional Anthropic-compatible endpoints.
MINIMAX_GLOBAL_BASE_URL = "https://api.minimax.io/anthropic"
MINIMAX_CHINA_BASE_URL = "https://api.minimaxi.com/anthropic"

# Expected model identifiers registered for the provider.
MINIMAX_MODEL_IDS = ["MiniMax-M3", "MiniMax-M2.7"]

# Expected per-model facts sourced from the provider configuration.
EXPECTED_MODELS = {
    "MiniMax-M3": {
        "context_window": 1000000,
        "pricing_usd_per_million_tokens": {
            "input": 0.6,
            "output": 2.4,
            "cache_read": 0.12,
            "cache_write": None,
        },
        "input_modalities": ["text", "image", "video"],
        "thinking": ["adaptive", "disabled"],
    },
    "MiniMax-M2.7": {
        "context_window": 204800,
        "pricing_usd_per_million_tokens": {
            "input": 0.3,
            "output": 1.2,
            "cache_read": 0.06,
            "cache_write": 0.375,
        },
        "input_modalities": ["text"],
        "thinking": ["always_on"],
    },
}


class TestProviderRegistry:
    """Test the provider registry data and accessors."""

    def test_minimax_is_registered(self):
        """The MiniMax provider is registered by name."""
        assert "minimax" in PROVIDERS
        assert "minimax" in list_providers()

    def test_get_provider_returns_config(self):
        """get_provider returns the registered configuration."""
        provider = get_provider("minimax")
        assert provider is not None
        assert provider["name"] == "minimax"

    def test_get_provider_is_case_insensitive(self):
        """Provider lookup is case insensitive."""
        assert get_provider("MiniMax") is not None
        assert get_provider("MINIMAX") is not None

    def test_get_provider_unknown_returns_none(self):
        """Unknown providers resolve to None."""
        assert get_provider("unknown") is None
        assert get_provider(None) is None


class TestProviderModels:
    """Test the per-model facts exposed by the registry."""

    def test_registered_model_ids(self):
        """Both model identifiers are registered."""
        models = get_provider_models("minimax")
        ids = [m["model_id"] for m in models]
        assert ids == MINIMAX_MODEL_IDS

    @pytest.mark.parametrize("model_id", MINIMAX_MODEL_IDS)
    def test_model_has_context_window(self, model_id):
        """Each model exposes a context window."""
        model = get_provider_model("minimax", model_id)
        assert model["context_window"] == EXPECTED_MODELS[model_id]["context_window"]

    @pytest.mark.parametrize("model_id", MINIMAX_MODEL_IDS)
    def test_model_has_pricing(self, model_id):
        """Each model exposes USD per million token pricing."""
        model = get_provider_model("minimax", model_id)
        assert model["pricing_usd_per_million_tokens"] == (
            EXPECTED_MODELS[model_id]["pricing_usd_per_million_tokens"]
        )

    @pytest.mark.parametrize("model_id", MINIMAX_MODEL_IDS)
    def test_model_has_input_modalities(self, model_id):
        """Each model exposes its supported input modalities."""
        model = get_provider_model("minimax", model_id)
        assert model["input_modalities"] == EXPECTED_MODELS[model_id]["input_modalities"]

    @pytest.mark.parametrize("model_id", MINIMAX_MODEL_IDS)
    def test_model_has_thinking_modes(self, model_id):
        """Each model exposes its available thinking modes."""
        model = get_provider_model("minimax", model_id)
        assert model["thinking"] == EXPECTED_MODELS[model_id]["thinking"]

    def test_get_provider_model_unknown(self):
        """Unknown model ids resolve to None."""
        assert get_provider_model("minimax", "does-not-exist") is None
        assert get_provider_model("unknown", "MiniMax-M3") is None


class TestProviderRegionalEndpoints:
    """Test the regional endpoint configuration."""

    def test_regional_endpoints_present(self):
        """Both global and China regions are configured."""
        regions = get_regional_endpoints("minimax")
        names = [r["region"] for r in regions]
        assert names == ["global_en", "cn_zh"]

    @pytest.mark.parametrize(
        "region,expected",
        [
            ("global_en", MINIMAX_GLOBAL_BASE_URL),
            ("cn_zh", MINIMAX_CHINA_BASE_URL),
        ],
    )
    def test_anthropic_base_url_per_region(self, region, expected):
        """The Anthropic-compatible base URL is resolved per region."""
        assert get_anthropic_base_url("minimax", region) == expected

    def test_default_region_is_global(self):
        """The default region resolves to the global endpoint."""
        assert get_anthropic_base_url("minimax") == MINIMAX_GLOBAL_BASE_URL

    @pytest.mark.parametrize(
        "region,expected",
        [
            ("global_en", "https://api.minimax.io/v1"),
            ("cn_zh", "https://api.minimaxi.com/v1"),
        ],
    )
    def test_openai_base_url_per_region(self, region, expected):
        """The OpenAI-compatible base URL is resolved per region."""
        assert get_openai_base_url("minimax", region) == expected

    def test_regional_docs_roots(self):
        """Each region exposes a docs root."""
        regions = {r["region"]: r for r in get_regional_endpoints("minimax")}
        assert regions["global_en"]["docs_root"] == "https://platform.minimax.io/docs"
        assert regions["cn_zh"]["docs_root"] == "https://platform.minimaxi.com/docs"

    def test_anthropic_base_url_unknown_provider(self):
        """Unknown providers resolve to no base URL."""
        assert get_anthropic_base_url("unknown") is None
