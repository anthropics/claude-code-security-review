"""
AWS Bedrock client for Claude API calls.

Provides Claude API functionality through AWS Bedrock service.
"""

import json
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


class ClaudeBedrockClient(ClaudeClientBase):
    """Client for calling Claude API through AWS Bedrock."""
    
    # Model mapping for Bedrock
    BEDROCK_MODEL_MAPPING = {
        'claude-3-5-haiku-20241022': 'anthropic.claude-3-5-haiku-20241022-v1:0',
        'claude-3-5-sonnet-20241022': 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        'claude-3-opus-20240229': 'anthropic.claude-3-opus-20240229-v1:0',
        'claude-opus-4-1-20250805': 'anthropic.claude-3-opus-20240229-v1:0',  # Use Claude 3 Opus as fallback
    }
    
    def __init__(self, 
                 model: Optional[str] = None,
                 timeout_seconds: Optional[int] = None,
                 max_retries: Optional[int] = None):
        """Initialize AWS Bedrock Claude client.
        
        Args:
            model: Claude model to use
            timeout_seconds: Request timeout in seconds
            max_retries: Maximum retry attempts for API calls
        """
        super().__init__(model, timeout_seconds, max_retries)
        
        self.model = model or DEFAULT_CLAUDE_MODEL
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.max_retries = max_retries or DEFAULT_MAX_RETRIES
        
        # Get required AWS configuration
        self.aws_region = os.environ.get("AWS_REGION")
        self.aws_access_key_id = os.environ.get("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        
        if not all([self.aws_region, self.aws_access_key_id, self.aws_secret_access_key]):
            raise ValueError(
                "AWS credentials are required. Please set AWS_REGION, "
                "AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY environment variables."
            )
        
        # Map model to Bedrock model ID
        self.bedrock_model_id = self.BEDROCK_MODEL_MAPPING.get(
            self.model, 
            'anthropic.claude-3-5-sonnet-20241022-v2:0'  # Default fallback
        )
        
        # Initialize Bedrock client
        try:
            import boto3
            self.bedrock_client = boto3.client(
                'bedrock-runtime',
                region_name=self.aws_region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key
            )
            logger.info(f"AWS Bedrock client initialized successfully with model {self.bedrock_model_id}")
        except ImportError:
            raise ImportError(
                "boto3 is required for AWS Bedrock support. "
                "Install it with: pip install boto3"
            )
        except Exception as e:
            raise ValueError(f"Failed to initialize AWS Bedrock client: {str(e)}")
    
    def validate_api_access(self) -> Tuple[bool, str]:
        """Validate that Bedrock API access is working.
        
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Simple test call to verify Bedrock access
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Hello"}],
            })
            
            response = self.bedrock_client.invoke_model(
                body=body,
                modelId=self.bedrock_model_id,
                accept='application/json',
                contentType='application/json'
            )
            
            # Parse response to ensure it's valid
            response_body = json.loads(response.get('body').read())
            if response_body.get('content'):
                logger.info("AWS Bedrock API access validated successfully")
                return True, ""
            else:
                return False, "Invalid response format from Bedrock"
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"AWS Bedrock API validation failed: {error_msg}")
            return False, f"API validation failed: {error_msg}"
    
    def call_with_retry(self, 
                       prompt: str,
                       system_prompt: Optional[str] = None,
                       max_tokens: int = PROMPT_TOKEN_LIMIT) -> Tuple[bool, str, str]:
        """Make Bedrock API call with retry logic.
        
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
                logger.info(f"Bedrock API call attempt {retries + 1}/{self.max_retries + 1}")
                
                # Prepare messages
                messages = [{"role": "user", "content": prompt}]
                
                # Build API call body
                body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                
                if system_prompt:
                    body["system"] = system_prompt
                
                # Make API call
                start_time = time.time()
                response = self.bedrock_client.invoke_model(
                    body=json.dumps(body),
                    modelId=self.bedrock_model_id,
                    accept='application/json',
                    contentType='application/json'
                )
                duration = time.time() - start_time
                
                # Parse response
                response_body = json.loads(response.get('body').read())
                
                # Extract text from response
                response_text = ""
                if 'content' in response_body:
                    for content_block in response_body['content']:
                        if content_block.get('type') == 'text':
                            response_text += content_block.get('text', '')
                
                logger.info(f"Bedrock API call successful in {duration:.1f}s")
                return True, response_text, ""
                
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                logger.error(f"Bedrock API call failed: {error_msg}")
                
                # Check if it's a throttling error
                if "throttled" in error_msg.lower() or "throttling" in error_msg.lower():
                    logger.warning("Throttling detected, increasing backoff")
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
        return False, "", f"Bedrock API call failed after {self.max_retries + 1} attempts: {last_error}"


def get_claude_bedrock_client(model: str = DEFAULT_CLAUDE_MODEL,
                             timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> ClaudeBedrockClient:
    """Convenience function to get Claude Bedrock client.
    
    Args:
        model: Claude model identifier
        timeout_seconds: API call timeout
        
    Returns:
        Initialized ClaudeBedrockClient instance
    """
    return ClaudeBedrockClient(
        model=model,
        timeout_seconds=timeout_seconds
    )
