"""
ClaudeCode - AI-Powered PR Security Audit Tool

A standalone security audit tool that uses Claude Code for comprehensive
security analysis of GitHub pull requests.
"""

__version__ = "1.0.0"
__author__ = "Anthropic Security Team"

# Import main components for easier access
from claudecode.github_action_audit import (
    GitHubActionClient,
    SimpleClaudeRunner,
    main
)

# Auto-apply Windows compatibility patches if needed
try:
    from claudecode.windows_patches import auto_patch_if_needed
    auto_patch_if_needed()
except ImportError:
    # Windows patches not available, continue normally
    pass

__all__ = [
    "GitHubActionClient",
    "SimpleClaudeRunner",
    "main"
]