"""Logging configuration for the Copilot CLI GitLab MR security review."""

import logging
import sys
import os


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger that outputs to stderr.
    
    Args:
        name: The name of the logger (usually __name__)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        
        # Get project and MR IID from environment for prefix
        repo_name = os.environ.get('CI_PROJECT_PATH', '')
        pr_number = os.environ.get('CI_MERGE_REQUEST_IID') or os.environ.get('MR_IID', '')
        
        # Build prefix
        if repo_name and pr_number:
            prefix = f"[{repo_name}!{pr_number}]"
        elif repo_name:
            prefix = f"[{repo_name}]"
        elif pr_number:
            prefix = f"[MR!{pr_number}]"
        else:
            prefix = ""
        
        # Include prefix in format if available
        if prefix:
            format_str = f'{prefix} [%(name)s] %(message)s'
        else:
            format_str = '[%(name)s] %(message)s'
        
        formatter = logging.Formatter(format_str)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger