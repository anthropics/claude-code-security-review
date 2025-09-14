"""Claude API client for direct Anthropic API calls."""

import os
import time
from typing import Dict, Any, Tuple, Optional

from anthropic import Anthropic

from claudecode.claude_client_base import ClaudeClientBase
from claudecode.constants import (
    DEFAULT_CLAUDE_MODEL, DEFAULT_TIMEOUT_SECONDS, DEFAULT_MAX_RETRIES,
    RATE_LIMIT_BACKOFF_MAX, PROMPT_TOKEN_LIMIT,
)
from claudecode.logger import get_logger

logger = get_logger(__name__)


class ClaudeAPIClient(ClaudeClientBase):
    """Client for calling Claude API directly for security analysis tasks."""
    
    def __init__(self, 
                 model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 timeout_seconds: Optional[int] = None,
                 max_retries: Optional[int] = None):
        """Initialize Claude API client.
        
        Args:
            model: Claude model to use
            api_key: Anthropic API key (if None, reads from ANTHROPIC_API_KEY env var)
            timeout_seconds: Request timeout in seconds
            max_retries: Maximum retry attempts for API calls
        """
        super().__init__(model, timeout_seconds, max_retries)
        
        self.model = model or DEFAULT_CLAUDE_MODEL
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.max_retries = max_retries or DEFAULT_MAX_RETRIES
        
        # Get API key from environment or parameter
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "No Anthropic API key found. Please set ANTHROPIC_API_KEY environment variable "
                "or provide api_key parameter."
            )
        
        # Initialize Anthropic client
        self.client = Anthropic(api_key=self.api_key)
        logger.info("Claude API client initialized successfully")
    
    def validate_api_access(self) -> Tuple[bool, str]:
        """Validate that API access is working.
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Simple test call to verify API access
            self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}],
                timeout=10
            )
            logger.info("Claude API access validated successfully")
            return True, ""
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Claude API validation failed: {error_msg}")
            return False, f"API validation failed: {error_msg}"
    
    def call_with_retry(self, 
                       prompt: str,
                       system_prompt: Optional[str] = None,
                       max_tokens: int = PROMPT_TOKEN_LIMIT) -> Tuple[bool, str, str]:
        """Make Claude API call with retry logic.
        
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
                logger.info(f"Claude API call attempt {retries + 1}/{self.max_retries + 1}")
                
                # Prepare messages
                messages = [{"role": "user", "content": prompt}]
                
                # Build API call parameters
                api_params = {
                    "model": self.model,
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
                
                logger.info(f"Claude API call successful in {duration:.1f}s")
                return True, response_text, ""
                
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"Claude API call failed: {error_msg}")
                
                # Check if it's a rate limit error
                if "rate limit" in error_msg.lower() or "429" in error_msg:
                    logger.warning("Rate limit detected, increasing backoff")
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
        return False, "", f"API call failed after {self.max_retries + 1} attempts: {last_error}"
    


def get_claude_api_client(model: str = DEFAULT_CLAUDE_MODEL,
                         api_key: Optional[str] = None,
                         timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ClaudeAPIClient:
    """Convenience function to get Claude API client.
    
    Args:
        model: Claude model identifier
        api_key: Optional API key (reads from environment if not provided)
        timeout_seconds: API call timeout
        
    Returns:
        Initialized ClaudeAPIClient instance
    """
    return ClaudeAPIClient(
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds
    )


