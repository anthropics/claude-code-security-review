"""
Constants and configuration values for ClaudeCode.
"""

import os

# API Configuration
DEFAULT_CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL') or 'claude-opus-4-1-20250805'
# Optional Anthropic-compatible base URL. When set, the Claude API client and
# Claude Code runner route requests through an alternate provider endpoint
# (for example the MiniMax Anthropic-compatible endpoint) instead of the
# default Anthropic API. Leave unset to use the default Anthropic endpoint.
DEFAULT_ANTHROPIC_BASE_URL = os.environ.get('ANTHROPIC_BASE_URL') or None
DEFAULT_TIMEOUT_SECONDS = 180  # 3 minutes
DEFAULT_MAX_RETRIES = 3
RATE_LIMIT_BACKOFF_MAX = 30  # Maximum backoff time for rate limits

# Token Limits
PROMPT_TOKEN_LIMIT = 16384  # 16k tokens max for claude-opus-4

# Exit Codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2

# Subprocess Configuration
SUBPROCESS_TIMEOUT = 1200  # 20 minutes for Claude Code execution

