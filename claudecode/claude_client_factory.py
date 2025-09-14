"""
Claude client factory for selecting the appropriate provider.

Provides a unified interface to create Claude clients based on environment configuration.
"""

from typing import Optional

from claudecode.claude_client_base import ClaudeClientBase
from claudecode.constants import DEFAULT_CLAUDE_MODEL, DEFAULT_TIMEOUT_SECONDS
from claudecode.env_validation import validate_environment_variables, get_provider_type
from claudecode.logger import get_logger

logger = get_logger(__name__)


def create_claude_client(model: Optional[str] = None,
                        api_key: Optional[str] = None,
                        timeout_seconds: Optional[int] = None,
                        max_retries: Optional[int] = None) -> ClaudeClientBase:
    """
    Create a Claude client based on environment configuration.
    
    This factory function automatically selects the appropriate provider
    (Anthropic API, AWS Bedrock, or Google Vertex AI) based on environment variables.
    
    Args:
        model: Claude model to use (defaults to DEFAULT_CLAUDE_MODEL)
        api_key: Anthropic API key (only used for direct Anthropic API)
        timeout_seconds: Request timeout in seconds (defaults to DEFAULT_TIMEOUT_SECONDS)
        max_retries: Maximum retry attempts for API calls
        
    Returns:
        Initialized Claude client instance
        
    Raises:
        ValueError: If environment validation fails or provider is unsupported
        ImportError: If required dependencies for the selected provider are missing
    """
    # Validate environment variables first
    validate_environment_variables()
    
    # Determine provider type
    provider_type = get_provider_type()
    
    # Set defaults
    model = model or DEFAULT_CLAUDE_MODEL
    timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    
    logger.info(f"Creating Claude client for provider: {provider_type}")
    
    if provider_type == "bedrock":
        from claudecode.claude_bedrock_client import ClaudeBedrockClient
        return ClaudeBedrockClient(
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries
        )
    elif provider_type == "vertex":
        from claudecode.claude_vertex_client import ClaudeVertexClient
        return ClaudeVertexClient(
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries
        )
    elif provider_type == "anthropic":
        from claudecode.claude_api_client import ClaudeAPIClient
        return ClaudeAPIClient(
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries
        )
    else:
        raise ValueError(f"Unsupported provider type: {provider_type}")


def get_claude_client(model: str = DEFAULT_CLAUDE_MODEL,
                     api_key: Optional[str] = None,
                     timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ClaudeClientBase:
    """
    Convenience function to get Claude client with default parameters.
    
    This is a simplified interface that maintains backward compatibility
    with existing code while supporting the new multi-provider architecture.
    
    Args:
        model: Claude model identifier
        api_key: Optional API key (only used for direct Anthropic API)
        timeout_seconds: API call timeout
        
    Returns:
        Initialized Claude client instance
    """
    return create_claude_client(
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds
    )
