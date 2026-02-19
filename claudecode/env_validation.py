"""
Environment validation utilities for Claude Code.

Validates the environment variables required for running Claude Code
based on the selected provider (Anthropic API, AWS Bedrock, or Vertex AI).
"""

import os
from typing import List


def validate_environment_variables() -> None:
    """
    Validates environment variables for Claude Code.
    
    Based on the selected provider (Anthropic API, AWS Bedrock, or Vertex AI).
    
    Raises:
        ValueError: If required environment variables are missing or invalid
    """
    use_bedrock = os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1"
    use_vertex = os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1"
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    claude_code_oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")

    errors: List[str] = []

    if use_bedrock and use_vertex:
        errors.append(
            "Cannot use both Bedrock and Vertex AI simultaneously. "
            "Please set only one provider."
        )

    if not use_bedrock and not use_vertex:
        if not anthropic_api_key and not claude_code_oauth_token:
            errors.append(
                "Either ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN is "
                "required when using direct Anthropic API."
            )
    elif use_bedrock:
        required_bedrock_vars = {
            "AWS_REGION": os.environ.get("AWS_REGION"),
            "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        }

        for key, value in required_bedrock_vars.items():
            if not value:
                errors.append(f"{key} is required when using AWS Bedrock.")
                
    elif use_vertex:
        required_vertex_vars = {
            "ANTHROPIC_VERTEX_PROJECT_ID": os.environ.get(
                "ANTHROPIC_VERTEX_PROJECT_ID"
            ),
            "CLOUD_ML_REGION": os.environ.get("CLOUD_ML_REGION"),
        }

        for key, value in required_vertex_vars.items():
            if not value:
                errors.append(
                f"{key} is required when using Google Vertex AI."
            )

    if errors:
        error_message = (
            "Environment variable validation failed:\n"
            + "\n".join(f"  - {error}" for error in errors)
        )
        raise ValueError(error_message)


def get_provider_type() -> str:
    """
    Determine which provider to use based on environment variables.

    Returns:
        Provider type: 'bedrock', 'vertex', or 'anthropic'
    """
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK") == "1":
        return "bedrock"
    elif os.environ.get("CLAUDE_CODE_USE_VERTEX") == "1":
        return "vertex"
    else:
        return "anthropic"
