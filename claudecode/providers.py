"""Provider registry for Anthropic-compatible API providers.

This module records the configuration for Anthropic-compatible providers that
the security review action can route requests through. Each provider entry
holds the regional Anthropic-compatible endpoints and the per-model facts
(context window, pricing, supported input modalities and thinking modes) needed
to drive the review client.

The registry is intentionally data-driven so callers resolve endpoints and
model facts by name instead of hardcoding them at call sites.
"""

from typing import Any, Dict, List, Optional


# MiniMax exposes an Anthropic-compatible Messages API. The two regional
# endpoints below cover the global (``global_en``) and China (``cn_zh``)
# deployments. Per-model facts describe the context window, pricing (USD per
# million tokens), supported input modalities and available thinking modes.
MINIMAX_PROVIDER: Dict[str, Any] = {
    "name": "minimax",
    "reason_codes": {
        "provider_add": "provider-add",
        "model_add": "model-add",
        "parameter_refresh": "parameter-refresh",
        "input_capability": "input-capability",
    },
    "model_id": "MiniMax-M3",
    "model_ids": ["MiniMax-M3", "MiniMax-M2.7"],
    "anthropic_base_url": "https://api.minimax.io/anthropic",
    "openai_base_url": "https://api.minimax.io/v1",
    "context_window": 1000000,
    "pricing_usd_per_million_tokens": {
        "input": 0.6,
        "output": 2.4,
        "cache_read": 0.12,
        "cache_write": None,
    },
    "thinking": ["adaptive", "disabled"],
    "models": [
        {
            "model_id": "MiniMax-M3",
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
        {
            "model_id": "MiniMax-M2.7",
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
    ],
    "regions": [
        {
            "region": "global_en",
            "openai_base_url": "https://api.minimax.io/v1",
            "anthropic_base_url": "https://api.minimax.io/anthropic",
            "docs_root": "https://platform.minimax.io/docs",
        },
        {
            "region": "cn_zh",
            "openai_base_url": "https://api.minimaxi.com/v1",
            "anthropic_base_url": "https://api.minimaxi.com/anthropic",
            "docs_root": "https://platform.minimaxi.com/docs",
        },
    ],
    "default_region": "global_en",
}

# Registry of Anthropic-compatible providers indexed by lowercase provider name.
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "minimax": MINIMAX_PROVIDER,
}


def get_provider(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the provider configuration for ``name`` or ``None``."""
    if not name:
        return None
    return PROVIDERS.get(name.lower())


def list_providers() -> List[str]:
    """Return the names of all registered providers."""
    return sorted(PROVIDERS.keys())


def get_provider_model(name: Optional[str], model_id: str) -> Optional[Dict[str, Any]]:
    """Return the model facts for ``model_id`` within provider ``name``."""
    provider = get_provider(name)
    if not provider:
        return None
    for model in provider.get("models", []):
        if model.get("model_id") == model_id:
            return model
    return None


def get_provider_models(name: Optional[str]) -> List[Dict[str, Any]]:
    """Return all model entries registered for provider ``name``."""
    provider = get_provider(name)
    if not provider:
        return []
    return list(provider.get("models", []))


def get_regional_endpoints(name: Optional[str]) -> List[Dict[str, Any]]:
    """Return the regional endpoint configuration for provider ``name``."""
    provider = get_provider(name)
    if not provider:
        return []
    return list(provider.get("regions", []))


def get_anthropic_base_url(name: Optional[str], region: Optional[str] = None) -> Optional[str]:
    """Resolve the Anthropic-compatible base URL for a provider and region."""
    provider = get_provider(name)
    if not provider:
        return None
    region_name = region or provider.get("default_region")
    for entry in provider.get("regions", []):
        if entry.get("region") == region_name:
            return entry.get("anthropic_base_url")
    return None


def get_openai_base_url(name: Optional[str], region: Optional[str] = None) -> Optional[str]:
    """Resolve the OpenAI-compatible base URL for a provider and region."""
    provider = get_provider(name)
    if not provider:
        return None
    region_name = region or provider.get("default_region")
    for entry in provider.get("regions", []):
        if entry.get("region") == region_name:
            return entry.get("openai_base_url")
    return None
