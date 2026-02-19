"""
Google Vertex AI client for Claude API calls.

Provides Claude API functionality through Google Vertex AI service.
"""

import os
import time
from typing import Tuple, Optional

from claudecode.claude_client_base import ClaudeClientBase
from claudecode.constants import (
    DEFAULT_CLAUDE_MODEL, DEFAULT_TIMEOUT_SECONDS, DEFAULT_MAX_RETRIES,
    RATE_LIMIT_BACKOFF_MAX, PROMPT_TOKEN_LIMIT,
)
from claudecode.logger import get_logger

logger = get_logger(__name__)


class ClaudeVertexClient(ClaudeClientBase):
    """Client for calling Claude API through Google Vertex AI."""
    
    # Model mapping for Vertex AI
    VERTEX_MODEL_MAPPING = {
        'claude-3-5-haiku-20241022': 'claude-3-5-haiku@20241022',
        'claude-3-5-sonnet-20241022': 'claude-3-5-sonnet-v2@20241022',
        'claude-3-opus-20240229': 'claude-3-opus@20240229',
        'claude-opus-4-1-20250805': 'claude-3-opus@20240229',  # Use Claude 3 Opus as fallback
    }
    
    def __init__(self, 
                 model: Optional[str] = None,
                 timeout_seconds: Optional[int] = None,
                 max_retries: Optional[int] = None):
        """Initialize Google Vertex AI Claude client.
        
        Args:
            model: Claude model to use
            timeout_seconds: Request timeout in seconds
            max_retries: Maximum retry attempts for API calls
        """
        super().__init__(model, timeout_seconds, max_retries)
        
        self.model = model or DEFAULT_CLAUDE_MODEL
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.max_retries = max_retries or DEFAULT_MAX_RETRIES
        
        # Get required Vertex AI configuration
        self.project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
        self.region = os.environ.get("CLOUD_ML_REGION")
        
        if not all([self.project_id, self.region]):
            raise ValueError(
                "Google Vertex AI configuration is required. Please set "
                "ANTHROPIC_VERTEX_PROJECT_ID and CLOUD_ML_REGION environment variables."
            )
        
        # Map model to Vertex AI model ID
        self.vertex_model_id = self.VERTEX_MODEL_MAPPING.get(
            self.model, 
            'claude-3-5-sonnet-v2@20241022'  # Default fallback
        )
        
        # Initialize Vertex AI client
        try:
            from anthropic import AnthropicVertex
            
            self.client = AnthropicVertex(
                region=self.region,
                project_id=self.project_id,
            )
            logger.info(f"Google Vertex AI client initialized successfully with model {self.vertex_model_id}")
        except ImportError:
            raise ImportError(
                "anthropic[vertex] is required for Google Vertex AI support. "
                "Install it with: pip install 'anthropic[vertex]'"
            )
        except Exception as e:
            raise ValueError(f"Failed to initialize Google Vertex AI client: {str(e)}")
    
    def validate_api_access(self) -> Tuple[bool, str]:
        """Validate that Vertex AI API access is working.
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Simple test call to verify Vertex AI access
            response = self.client.messages.create(
                model=self.vertex_model_id,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}],
                timeout=10
            )
            
            # Check if response is valid
            if response.content:
                logger.info("Google Vertex AI API access validated successfully")
                return True, ""
            else:
                return False, "Invalid response format from Vertex AI"
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Google Vertex AI API validation failed: {error_msg}")
            return False, f"API validation failed: {error_msg}"
    
    def call_with_retry(self, 
                       prompt: str,
                       system_prompt: Optional[str] = None,
                       max_tokens: int = PROMPT_TOKEN_LIMIT) -> Tuple[bool, str, str]:
        """Make Vertex AI API call with retry logic.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            
        Returns:
            Tuple of (success, response_text, error_message)
        """
        retries = 0
        last_error = None
        
        while retries <= self.max_retries:
            try:
                logger.info(f"Vertex AI API call attempt {retries + 1}/{self.max_retries + 1}")
                
                # Prepare messages
                messages = [{"role": "user", "content": prompt}]
                
                # Build API call parameters
                api_params = {
                    "model": self.vertex_model_id,
                    "max_tokens": max_tokens,
                    "messages": messages,
                    "timeout": self.timeout_seconds
                }
                
                if system_prompt:
                    api_params["system"] = system_prompt
                
                # Make API call
                start_time = time.time()
                response = self.client.messages.create(**api_params)
                duration = time.time() - start_time
                
                # Extract text from response
                response_text = ""
                for content_block in response.content:
                    if hasattr(content_block, 'text'):
                        response_text += content_block.text
                
                logger.info(f"Vertex AI API call successful in {duration:.1f}s")
                return True, response_text, ""
                
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"Vertex AI API call failed: {error_msg}")
                
                # Check if it's a quota/rate limit error
                if any(keyword in error_msg.lower() for keyword in ["quota", "rate limit", "429"]):
                    logger.warning("Rate limiting detected, increasing backoff")
                    backoff_time = min(RATE_LIMIT_BACKOFF_MAX, 5 * (retries + 1))  # Progressive backoff
                    time.sleep(backoff_time)
                elif "timeout" in error_msg.lower():
                    logger.warning("Timeout detected, retrying")
                    time.sleep(2)
                else:
                    # For other errors, shorter backoff
                    time.sleep(1)
                
                retries += 1
        
        # All retries exhausted
        return False, "", f"Vertex AI API call failed after {self.max_retries + 1} attempts: {last_error}"


def get_claude_vertex_client(model: str = DEFAULT_CLAUDE_MODEL,
                            timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ClaudeVertexClient:
    """Convenience function to get Claude Vertex AI client.
    
    Args:
        model: Claude model identifier
        timeout_seconds: API call timeout
        
    Returns:
        Initialized ClaudeVertexClient instance
    """
    return ClaudeVertexClient(
        model=model,
        timeout_seconds=timeout_seconds
    )
