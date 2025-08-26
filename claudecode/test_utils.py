#!/usr/bin/env python3
"""
Comprehensive test utilities for the Claude Code Security Review system.

This module provides industry-standard testing utilities, fixtures, and helpers
for testing the Claude Code Security Review system across different platforms
and configurations.
"""

import os
import sys
import platform
import tempfile
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Callable
from unittest.mock import Mock, MagicMock, patch
from contextlib import contextmanager
import json
import time

from .logger import get_logger
from .platform_utils import PlatformAdapter, get_platform_adapter

logger = get_logger(__name__)


class EnvironmentManager:
    """
    Manages test environment setup and teardown.
    
    This class provides a comprehensive test environment that can simulate
    different operating systems, Claude CLI installations, and API configurations.
    """
    
    def __init__(self, platform_override: Optional[str] = None):
        """
        Initialize test environment.
        
        Args:
            platform_override: Override detected platform ('windows', 'linux', 'darwin')
        """
        self.platform_override = platform_override
        self.original_env = dict(os.environ)
        self.temp_dirs: List[str] = []
        self.patches: List[Any] = []
        
    def __enter__(self):
        """Enter test environment context."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit test environment context and cleanup."""
        self.cleanup()
    
    def cleanup(self):
        """Clean up test environment."""
        # Restore original environment
        os.environ.clear()
        os.environ.update(self.original_env)
        
        # Clean up temporary directories
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to clean up temp dir {temp_dir}: {e}")
        
        # Stop all patches
        for p in self.patches:
            try:
                p.stop()
            except Exception as e:
                logger.warning(f"Failed to stop patch: {e}")
        
        self.temp_dirs.clear()
        self.patches.clear()
    
    def set_environment_variables(self, env_vars: Dict[str, str]):
        """Set environment variables for the test."""
        for key, value in env_vars.items():
            os.environ[key] = value
    
    def create_temp_directory(self, prefix: str = "claude_test_") -> str:
        """Create a temporary directory that will be cleaned up."""
        temp_dir = tempfile.mkdtemp(prefix=prefix)
        self.temp_dirs.append(temp_dir)
        return temp_dir
    
    def mock_platform(self, platform_name: str) -> Any:
        """Mock the platform.system() function."""
        patcher = patch('platform.system', return_value=platform_name.title())
        mock_platform = patcher.start()
        self.patches.append(patcher)
        return mock_platform


class ClaudeCliMocker:
    """
    Comprehensive Claude CLI mocking utilities.
    
    This class provides various ways to mock Claude CLI behavior for testing
    different scenarios including success, failure, timeouts, and API errors.
    """
    
    @staticmethod
    def mock_successful_validation(version: str = "1.0.71 (Claude Code)") -> Mock:
        """Mock successful Claude CLI validation."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = version
        mock_result.stderr = ""
        return mock_result
    
    @staticmethod
    def mock_failed_validation(error_code: int = 1, stderr: str = "Authentication failed") -> Mock:
        """Mock failed Claude CLI validation."""
        mock_result = Mock()
        mock_result.returncode = error_code
        mock_result.stdout = ""
        mock_result.stderr = stderr
        return mock_result
    
    @staticmethod
    def mock_file_not_found() -> Exception:
        """Mock FileNotFoundError for missing Claude CLI."""
        return FileNotFoundError("The system cannot find the file specified")
    
    @staticmethod
    def mock_timeout() -> Exception:
        """Mock subprocess timeout."""
        return subprocess.TimeoutExpired(['claude'], 10)
    
    @staticmethod
    def mock_successful_audit(findings: Optional[List[Dict[str, Any]]] = None) -> Mock:
        """Mock successful Claude CLI security audit."""
        if findings is None:
            findings = []
        
        result_data = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": json.dumps({
                "findings": findings,
                "analysis_summary": {
                    "files_reviewed": 1,
                    "high_severity": len([f for f in findings if f.get('severity') == 'HIGH']),
                    "medium_severity": len([f for f in findings if f.get('severity') == 'MEDIUM']),
                    "low_severity": len([f for f in findings if f.get('severity') == 'LOW']),
                    "review_completed": True
                }
            })
        }
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(result_data)
        mock_result.stderr = ""
        return mock_result
    
    @staticmethod
    def mock_api_error(error_type: str = "forbidden", message: str = "Request not allowed") -> Mock:
        """Mock Claude CLI API error."""
        result_data = {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": f'API Error: 403 {{"error":{{"type":"{error_type}","message":"{message}"}}}}'
        }
        
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = json.dumps(result_data)
        mock_result.stderr = ""
        return mock_result
    
    @staticmethod
    def mock_prompt_too_long() -> Mock:
        """Mock 'prompt too long' error."""
        result_data = {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "Prompt is too long"
        }
        
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(result_data)
        mock_result.stderr = ""
        return mock_result


class GitHubApiMocker:
    """
    GitHub API mocking utilities for testing PR analysis.
    """
    
    @staticmethod
    def mock_pr_data(pr_number: int = 123, repo_name: str = "test/repo") -> Dict[str, Any]:
        """Create mock PR data."""
        return {
            'number': pr_number,
            'title': 'Test PR',
            'body': 'This is a test pull request',
            'user': {'login': 'testuser'},
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2024-01-01T12:00:00Z',
            'state': 'open',
            'head': {
                'ref': 'feature/test',
                'sha': 'abc123',
                'repo': {'full_name': repo_name}
            },
            'base': {
                'ref': 'main',
                'sha': 'main123'
            },
            'additions': 10,
            'deletions': 5,
            'changed_files': 2
        }
    
    @staticmethod
    def mock_pr_files() -> List[Dict[str, Any]]:
        """Create mock PR files data."""
        return [
            {
                'filename': 'src/test.py',
                'status': 'modified',
                'additions': 5,
                'deletions': 2,
                'changes': 7,
                'patch': '@@ -1,3 +1,6 @@\n+import os\n print("hello")\n+secret = "hardcoded"\n'
            }
        ]
    
    @staticmethod
    def mock_pr_diff() -> str:
        """Create mock PR diff."""
        return """diff --git a/src/test.py b/src/test.py
index 1234567..abcdefg 100644
--- a/src/test.py
+++ b/src/test.py
@@ -1,3 +1,6 @@
+import os
 print("hello")
+secret = "hardcoded_secret_key"
"""


class WindowsTestingUtils:
    """
    Windows-specific testing utilities.
    """
    
    @staticmethod
    def mock_windows_environment() -> Dict[str, str]:
        """Create Windows-like environment variables."""
        return {
            'OS': 'Windows_NT',
            'USERPROFILE': r'C:\Users\TestUser',
            'APPDATA': r'C:\Users\TestUser\AppData\Roaming',
            'ProgramFiles': r'C:\Program Files',
            'ProgramFiles(x86)': r'C:\Program Files (x86)',
            'SystemRoot': r'C:\Windows',
            'PATH': r'C:\Windows\System32;C:\Program Files\nodejs;C:\Users\TestUser\AppData\Roaming\npm'
        }
    
    @staticmethod
    def create_mock_claude_installation(temp_dir: str, install_type: str = "npm") -> str:
        """
        Create a mock Claude CLI installation in a temporary directory.
        
        Args:
            temp_dir: Temporary directory to create installation in
            install_type: Type of installation ('npm', 'manual', 'chocolatey')
            
        Returns:
            Path to the mock Claude executable
        """
        if install_type == "npm":
            npm_dir = os.path.join(temp_dir, "npm")
            os.makedirs(npm_dir, exist_ok=True)
            
            # Create mock claude.CMD file
            claude_cmd = os.path.join(npm_dir, "claude.CMD")
            with open(claude_cmd, 'w') as f:
                f.write('@echo off\necho 1.0.71 (Claude Code)\n')
            
            # Create mock claude.ps1 file
            claude_ps1 = os.path.join(npm_dir, "claude.ps1")
            with open(claude_ps1, 'w') as f:
                f.write('Write-Host "1.0.71 (Claude Code)"\n')
            
            return claude_cmd
        
        elif install_type == "manual":
            manual_dir = os.path.join(temp_dir, "claude")
            os.makedirs(manual_dir, exist_ok=True)
            
            claude_exe = os.path.join(manual_dir, "claude.exe")
            # Create a dummy executable file (just for path testing)
            with open(claude_exe, 'wb') as f:
                f.write(b'MZ')  # Minimal PE header signature
            
            return claude_exe
        
        else:
            raise ValueError(f"Unsupported install_type: {install_type}")


class FixtureManager:
    """
    Manages test fixtures and data.
    """
    
    @staticmethod
    def create_sample_security_findings() -> List[Dict[str, Any]]:
        """Create sample security findings for testing."""
        return [
            {
                'file': 'src/auth.py',
                'line': 42,
                'severity': 'HIGH',
                'category': 'hardcoded_secrets',
                'description': 'Hardcoded API key found in source code',
                'recommendation': 'Use environment variables for sensitive data',
                'confidence': 0.95
            },
            {
                'file': 'src/db.py',
                'line': 15,
                'severity': 'HIGH',
                'category': 'sql_injection',
                'description': 'SQL injection vulnerability in query construction',
                'recommendation': 'Use parameterized queries',
                'confidence': 0.90
            },
            {
                'file': 'src/utils.py',
                'line': 8,
                'severity': 'MEDIUM',
                'category': 'weak_crypto',
                'description': 'Use of weak hashing algorithm MD5',
                'recommendation': 'Use SHA-256 or stronger algorithms',
                'confidence': 0.80
            }
        ]
    
    @staticmethod
    def create_sample_configuration() -> Dict[str, Any]:
        """Create sample configuration for testing."""
        return {
            'github_repository': 'test/repo',
            'pr_number': 123,
            'github_token': 'ghp_test_token_123',
            'anthropic_api_key': 'sk-ant-test-key-123',
            'exclude_directories': ['node_modules', '.git', 'dist'],
            'enable_claude_filtering': False,
            'claudecode_timeout': 20
        }


@contextmanager
def mock_subprocess_run(side_effect: Union[Mock, List[Mock], Callable, Exception]):
    """
    Context manager for mocking subprocess.run with comprehensive behavior.
    
    Args:
        side_effect: Mock return value, list of values, callable, or exception
    """
    with patch('subprocess.run', side_effect=side_effect) as mock_run:
        # Also patch the platform_utils version
        with patch('claudecode.platform_utils.subprocess.run', side_effect=side_effect):
            yield mock_run


@contextmanager
def temporary_environment(**env_vars):
    """
    Context manager for temporarily setting environment variables.
    
    Args:
        **env_vars: Environment variables to set
    """
    original_env = dict(os.environ)
    try:
        os.environ.update(env_vars)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original_env)


def assert_claude_command_called_correctly(mock_run: Mock, expected_args: List[str]):
    """
    Assert that subprocess.run was called with the correct Claude command.
    
    This function handles platform-specific variations in command construction.
    
    Args:
        mock_run: Mocked subprocess.run function
        expected_args: Expected command arguments
    """
    assert mock_run.called, "subprocess.run was not called"
    
    call_args = mock_run.call_args[0][0]  # First positional argument (command)
    
    # On Windows, the command might be wrapped with cmd.exe or powershell.exe
    if platform.system() == "Windows":
        # Check if the original claude command appears in the call
        if len(expected_args) > 0 and expected_args[0] == "claude":
            # Look for claude-related arguments in the call
            claude_found = any("claude" in str(arg) for arg in call_args)
            assert claude_found, f"Claude command not found in call: {call_args}"
            
            # Check that additional arguments are preserved
            if len(expected_args) > 1:
                expected_additional_args = expected_args[1:]
                for arg in expected_additional_args:
                    assert arg in call_args, f"Expected argument '{arg}' not found in call: {call_args}"
        else:
            assert call_args == expected_args, f"Expected {expected_args}, got {call_args}"
    else:
        # On Unix-like systems, expect exact match
        assert call_args == expected_args, f"Expected {expected_args}, got {call_args}"


def create_test_repository(temp_dir: str, files: Dict[str, str]) -> str:
    """
    Create a test repository with specified files.
    
    Args:
        temp_dir: Base temporary directory
        files: Dictionary of filename -> content
        
    Returns:
        Path to created repository
    """
    repo_dir = os.path.join(temp_dir, "test_repo")
    os.makedirs(repo_dir, exist_ok=True)
    
    for filename, content in files.items():
        file_path = os.path.join(repo_dir, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    return repo_dir


def measure_test_performance(test_func: Callable) -> Dict[str, Any]:
    """
    Measure test performance metrics.
    
    Args:
        test_func: Test function to measure
        
    Returns:
        Dictionary with timing and performance metrics
    """
    start_time = time.time()
    start_cpu = time.process_time()
    
    try:
        result = test_func()
        success = True
        error = None
    except Exception as e:
        result = None
        success = False
        error = str(e)
    
    end_time = time.time()
    end_cpu = time.process_time()
    
    return {
        'wall_time': end_time - start_time,
        'cpu_time': end_cpu - start_cpu,
        'success': success,
        'error': error,
        'result': result
    }


class ReportingUtils:
    """
    Test result reporting and analysis utilities.
    """
    
    def __init__(self):
        """Initialize test reporter."""
        self.results: List[Dict[str, Any]] = []
    
    def record_test_result(self, test_name: str, success: bool, 
                          duration: float, error: Optional[str] = None):
        """Record a test result."""
        self.results.append({
            'test_name': test_name,
            'success': success,
            'duration': duration,
            'error': error,
            'timestamp': time.time()
        })
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive test report."""
        total_tests = len(self.results)
        passed_tests = len([r for r in self.results if r['success']])
        failed_tests = total_tests - passed_tests
        
        total_duration = sum(r['duration'] for r in self.results)
        avg_duration = total_duration / total_tests if total_tests > 0 else 0
        
        failures = [r for r in self.results if not r['success']]
        
        return {
            'summary': {
                'total_tests': total_tests,
                'passed': passed_tests,
                'failed': failed_tests,
                'pass_rate': passed_tests / total_tests if total_tests > 0 else 0,
                'total_duration': total_duration,
                'average_duration': avg_duration
            },
            'failures': failures,
            'all_results': self.results
        }
    
    def print_summary(self):
        """Print test summary to console."""
        report = self.generate_report()
        summary = report['summary']
        
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Pass Rate: {summary['pass_rate']:.1%}")
        print(f"Total Duration: {summary['total_duration']:.2f}s")
        print(f"Average Duration: {summary['average_duration']:.2f}s")
        
        if summary['failed'] > 0:
            print(f"\nFAILURES:")
            for failure in report['failures']:
                print(f"  - {failure['test_name']}: {failure['error']}")
        
        print("="*60)
