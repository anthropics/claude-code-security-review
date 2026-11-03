"""
copilot_review - GitLab merge request security review powered by the GitHub Copilot CLI.

Derived from anthropics/claude-code-security-review (MIT License), migrated from GitHub Actions +
Claude Code to GitLab CI + GitHub Copilot CLI.
"""

__version__ = "2.0.0"

from copilot_review.gitlab_client import GitLabClient
from copilot_review.copilot_runner import CopilotRunner
from copilot_review.gitlab_mr_audit import main

__all__ = [
    "GitLabClient",
    "CopilotRunner",
    "main",
]
