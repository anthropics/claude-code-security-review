"""
Constants and configuration values for the Copilot CLI based GitLab MR security review.
"""

import os

# Model selection. The documented Copilot CLI default is claude-sonnet-5.5;
# it can be overridden with the COPILOT_MODEL environment variable (the same
# variable the Copilot CLI itself reads) or the --model flag.
DEFAULT_COPILOT_MODEL = os.environ.get('COPILOT_MODEL') or 'claude-sonnet-5.5'

# Copilot CLI executable name / path
COPILOT_BIN = os.environ.get('COPILOT_BIN') or 'copilot'

# Environment variables the Copilot CLI accepts for authentication (highest precedence first)
COPILOT_TOKEN_ENV_VARS = ('COPILOT_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')

# Secrets that must NOT be visible to the agent subprocess (defence in depth against
# prompt injection from MR content). The Copilot token itself must stay available.
SENSITIVE_ENV_VARS = (
    'GITLAB_TOKEN',
    'GITLAB_PRIVATE_TOKEN',
    'CI_JOB_TOKEN',
    'CI_REGISTRY_PASSWORD',
    'CI_DEPLOY_PASSWORD',
    'CI_REPOSITORY_URL',
)

# Working directory (relative to the repository) where prompt / result files are exchanged
WORK_DIR_NAME = '.copilot-review'

# Markers embedded in MR notes so reruns can detect earlier reviews
SUMMARY_MARKER = 'copilot-security-review:summary'
FINDING_MARKER = 'copilot-security-review:finding'

# Retry configuration
DEFAULT_MAX_RETRIES = 3

# Exit Codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_CONFIGURATION_ERROR = 2

# Subprocess Configuration
SUBPROCESS_TIMEOUT = 1200  # 20 minutes per Copilot CLI execution
