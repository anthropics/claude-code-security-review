#!/usr/bin/env python3
"""
Main entry point for the Copilot CLI based GitLab MR security review.
Usage: python -m copilot_review.audit
"""

from copilot_review.gitlab_mr_audit import main

if __name__ == "__main__":
    main()
