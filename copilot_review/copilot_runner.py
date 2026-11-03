"""Runner that executes prompts through the GitHub Copilot CLI (``copilot``) in non-interactive mode.

Design notes
------------
* Long prompts (the MR diff can be large) are written to a file inside the repository and the CLI is
  given a short ``-p`` instruction that points to it. Passing a large diff as a single command-line
  argument would hit the operating system's argument size limit. ``stdin`` and ``arg`` modes are
  available through ``COPILOT_PROMPT_MODE``.
* The agent is asked to write its JSON result to a file inside the work directory. If that file is not
  produced, the JSON is recovered from the CLI's stdout instead, so the tool does not depend on a
  stable stdout format.
* Tool permissions are kept minimal (read, a few read-only git/grep commands, write only inside the
  work directory, no URL access) and secrets such as the GitLab token are removed from the
  environment of the agent process.
"""

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from copilot_review.constants import (
    COPILOT_BIN,
    COPILOT_TOKEN_ENV_VARS,
    DEFAULT_COPILOT_MODEL,
    DEFAULT_MAX_RETRIES,
    SENSITIVE_ENV_VARS,
    SUBPROCESS_TIMEOUT,
    WORK_DIR_NAME,
)
from copilot_review.logger import get_logger

logger = get_logger(__name__)

PROMPT_MODES = ('file', 'stdin', 'arg')
# Linux limits a single argv string to 128 KiB; stay well below it.
MAX_ARG_PROMPT_BYTES = 100_000

# Read-only commands the agent may run without approval. Verify the pattern syntax against the
# installed Copilot CLI version (see README) and override with COPILOT_ALLOW_TOOLS if needed.
DEFAULT_ALLOW_TOOLS = [
    'read',
    f'write({WORK_DIR_NAME}/*)',
    'shell(git diff:*)',
    'shell(git log:*)',
    'shell(git show:*)',
    'shell(git ls-files:*)',
    'shell(grep:*)',
    'shell(ls:*)',
]

# Deny rules take precedence over allow rules (per the Copilot CLI documentation).
DEFAULT_DENY_TOOLS = [
    'url',
    'shell(curl:*)',
    'shell(wget:*)',
    'shell(git push:*)',
    'shell(git remote:*)',
    'shell(git config:*)',
]

_TOO_LONG_HINTS = (
    'prompt is too long',
    'context length',
    'context window',
    'maximum context',
    'token limit',
    'too many tokens',
)


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(',') if item.strip()]


def find_json_with_key(text: str, key: str) -> Optional[Dict[str, Any]]:
    """Return the first JSON object in ``text`` that contains ``key`` (or None)."""
    if not text:
        return None

    try:
        whole = json.loads(text)
        if isinstance(whole, dict) and key in whole:
            return whole
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    idx = text.find('{')
    while idx != -1:
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            idx = text.find('{', idx + 1)
            continue
        if isinstance(obj, dict) and key in obj:
            return obj
        idx = text.find('{', end)
    return None


class CopilotRunner:
    """Runs prompts through ``copilot -p`` and returns the parsed JSON result."""

    def __init__(self,
                 timeout_minutes: Optional[int] = None,
                 model: Optional[str] = None,
                 prompt_mode: Optional[str] = None,
                 max_retries: Optional[int] = None):
        if timeout_minutes is not None:
            self.timeout_seconds = int(timeout_minutes) * 60
        else:
            self.timeout_seconds = SUBPROCESS_TIMEOUT

        self.model = model or os.environ.get('COPILOT_MODEL') or DEFAULT_COPILOT_MODEL
        self.binary = os.environ.get('COPILOT_BIN') or COPILOT_BIN
        self.max_retries = max_retries or DEFAULT_MAX_RETRIES

        mode = (prompt_mode or os.environ.get('COPILOT_PROMPT_MODE') or 'file').lower()
        if mode not in PROMPT_MODES:
            raise ValueError(f"Invalid COPILOT_PROMPT_MODE '{mode}'. Use one of: {', '.join(PROMPT_MODES)}")
        self.prompt_mode = mode

    # ------------------------------------------------------------------ configuration helpers
    @staticmethod
    def result_path_for(repo_dir: Path, purpose: str) -> Path:
        """Path of the result file the agent is asked to write for a given purpose."""
        return Path(repo_dir) / WORK_DIR_NAME / f'result-{purpose}.json'

    def allow_tools(self) -> List[str]:
        override = os.environ.get('COPILOT_ALLOW_TOOLS')
        return _split_csv(override) if override else list(DEFAULT_ALLOW_TOOLS)

    def deny_tools(self) -> List[str]:
        override = os.environ.get('COPILOT_DENY_TOOLS')
        return _split_csv(override) if override is not None and override != '' else list(DEFAULT_DENY_TOOLS)

    def build_env(self) -> Dict[str, str]:
        """Environment for the agent process: current env minus secrets the agent does not need."""
        return {k: v for k, v in os.environ.items() if k not in SENSITIVE_ENV_VARS}

    def build_command(self, work_dir: Path, instruction: Optional[str]) -> List[str]:
        """Build the ``copilot`` command line.

        Args:
            work_dir: Directory shared with the agent for prompt/result files
            instruction: Text passed with ``-p`` (None when the prompt is sent on stdin)
        """
        cmd = [
            self.binary,
            '-s',
            '--no-color',
            '--no-ask-user',
            '--no-auto-update',
            f'--model={self.model}',
            f'--add-dir={work_dir}',
            f"--allow-tool={', '.join(self.allow_tools())}",
        ]
        deny = self.deny_tools()
        if deny:
            cmd.append(f"--deny-tool={', '.join(deny)}")

        extra = os.environ.get('COPILOT_EXTRA_ARGS', '')
        if extra:
            cmd.extend(shlex.split(extra))

        if instruction is not None:
            cmd.extend(['-p', instruction])
        return cmd

    # ------------------------------------------------------------------ availability
    def validate_available(self) -> Tuple[bool, str]:
        """Check that the Copilot CLI is installed and a token is configured."""
        try:
            result = subprocess.run(
                [self.binary, '--version'],
                capture_output=True,
                text=True,
                timeout=30,
                env=self.build_env(),
            )
        except subprocess.TimeoutExpired:
            return False, "Copilot CLI command timed out"
        except FileNotFoundError:
            return False, "Copilot CLI is not installed or not in PATH (npm install -g @github/copilot)"
        except Exception as e:
            return False, f"Failed to check Copilot CLI: {str(e)}"

        if result.returncode != 0:
            error_msg = f"Copilot CLI returned exit code {result.returncode}"
            if result.stderr:
                error_msg += f". Stderr: {result.stderr}"
            if result.stdout:
                error_msg += f". Stdout: {result.stdout}"
            return False, error_msg

        if not any(os.environ.get(name) for name in COPILOT_TOKEN_ENV_VARS):
            return False, ("No Copilot token found. Set COPILOT_GITHUB_TOKEN (fine-grained token with the "
                           "'Copilot Requests' permission; classic ghp_ tokens are not supported).")
        return True, ""

    # ------------------------------------------------------------------ execution
    def run(self,
            repo_dir: Path,
            prompt: str,
            purpose: str = 'audit',
            required_key: str = 'findings') -> Tuple[bool, str, Dict[str, Any]]:
        """Run a prompt and return ``(success, error_message, parsed_json)``.

        Args:
            repo_dir: Repository checkout the agent works in
            prompt: Full prompt text
            purpose: Short label used for the prompt/result file names (``audit``, ``filter``)
            required_key: Top-level key the result JSON must contain
        """
        repo_dir = Path(repo_dir)
        if not repo_dir.exists():
            return False, f"Repository directory does not exist: {repo_dir}", {}

        prompt_size = len(prompt.encode('utf-8'))
        if prompt_size > 1024 * 1024:
            logger.warning(f"Large prompt size: {prompt_size / 1024 / 1024:.2f}MB")

        work_dir = repo_dir / WORK_DIR_NAME
        work_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = work_dir / f'prompt-{purpose}.md'
        result_path = self.result_path_for(repo_dir, purpose)

        mode = self.prompt_mode
        if mode == 'arg' and prompt_size > MAX_ARG_PROMPT_BYTES:
            logger.warning("Prompt too large for a command-line argument; using file mode instead")
            mode = 'file'

        try:
            stdin_input: Optional[str] = None
            if mode == 'file':
                prompt_path.write_text(prompt, encoding='utf-8')
                instruction = (
                    f"Read the file {prompt_path} and carry out the task described in it exactly. "
                    f"Your final reply must contain only the JSON result described in that file."
                )
            elif mode == 'arg':
                instruction = prompt
            else:  # stdin
                instruction = None
                stdin_input = prompt

            cmd = self.build_command(work_dir, instruction)
            env = self.build_env()

            for attempt in range(self.max_retries):
                last_attempt = attempt == self.max_retries - 1
                if result_path.exists():
                    result_path.unlink()

                try:
                    result = subprocess.run(
                        cmd,
                        input=stdin_input,
                        cwd=repo_dir,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout_seconds,
                        env=env,
                    )
                except subprocess.TimeoutExpired:
                    return False, f"Copilot CLI execution timed out after {self.timeout_seconds // 60} minutes", {}

                stdout = result.stdout or ''
                stderr = result.stderr or ''
                combined = f"{stdout}\n{stderr}"

                if result.returncode != 0:
                    if self._looks_like_prompt_too_long(combined):
                        return False, "PROMPT_TOO_LONG", {}
                    if last_attempt:
                        details = f"Copilot CLI execution failed with return code {result.returncode}\n"
                        details += f"Stderr: {stderr[:2000]}\n"
                        details += f"Stdout: {stdout[:500]}..."
                        return False, details, {}
                    time.sleep(5 * attempt)
                    continue

                parsed = self._load_result(result_path, stdout, required_key)
                if parsed is not None:
                    return True, "", parsed

                if self._looks_like_prompt_too_long(combined):
                    return False, "PROMPT_TOO_LONG", {}
                if last_attempt:
                    return False, (f"Failed to parse Copilot CLI output (no JSON with '{required_key}' found). "
                                   f"Output preview: {stdout[:500]!r}"), {}
                logger.warning(f"No parsable '{required_key}' JSON on attempt {attempt + 1}; retrying")

            return False, "Unexpected error in retry logic", {}

        except Exception as e:
            return False, f"Copilot CLI execution error: {str(e)}", {}
        finally:
            self._cleanup(work_dir, [prompt_path, result_path])

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _load_result(result_path: Path, stdout: str, required_key: str) -> Optional[Dict[str, Any]]:
        """Prefer the result file written by the agent, fall back to stdout."""
        if result_path.exists():
            try:
                text = result_path.read_text(encoding='utf-8')
            except OSError as e:
                logger.warning(f"Could not read result file {result_path}: {e}")
            else:
                found = find_json_with_key(text, required_key)
                if found is not None:
                    return found
        return find_json_with_key(stdout, required_key)

    @staticmethod
    def _looks_like_prompt_too_long(text: str) -> bool:
        # Heuristic: the exact Copilot CLI error text is not documented.
        lowered = text.lower()
        return any(hint in lowered for hint in _TOO_LONG_HINTS)

    @staticmethod
    def _cleanup(work_dir: Path, files: List[Path]) -> None:
        if os.environ.get('COPILOT_KEEP_WORKDIR', '').lower() == 'true':
            return
        for path in files:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                logger.warning(f"Could not remove {path}: {e}")
        try:
            work_dir.rmdir()  # only removes the directory when empty
        except OSError:
            pass
