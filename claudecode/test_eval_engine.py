"""Tests for eval_engine module."""

import os
from unittest.mock import Mock, patch
import pytest
import json

from claudecode.evals.eval_engine import (
    EvaluationEngine, EvalResult, EvalCase, run_single_evaluation
)


class TestEvalResult:
    """Test the EvalResult dataclass."""
    
    def test_eval_result_creation(self):
        """Test creating an EvalResult instance."""
        result = EvalResult(
            repo_name="test/repo",
            pr_number=123,
            description="Test PR",
            success=True,
            runtime_seconds=10.5,
            findings_count=2,
            detected_vulnerabilities=True
        )
        
        assert result.repo_name == "test/repo"
        assert result.pr_number == 123
        assert result.description == "Test PR"
        assert result.success is True
        assert result.runtime_seconds == 10.5
        assert result.findings_count == 2
        assert result.detected_vulnerabilities is True
        assert result.error_message == ""
        assert result.findings_summary is None
    
    def test_eval_result_with_error(self):
        """Test creating an EvalResult with error."""
        result = EvalResult(
            repo_name="test/repo",
            pr_number=456,
            description="Failed PR",
            success=False,
            runtime_seconds=5.0,
            findings_count=0,
            detected_vulnerabilities=False,
            error_message="Failed to clone repository"
        )
        
        assert result.success is False
        assert result.error_message == "Failed to clone repository"
        assert result.findings_count == 0
    
    def test_eval_result_with_findings(self):
        """Test creating an EvalResult with findings."""
        findings = [
            {"file": "test.py", "line": 10, "severity": "HIGH"}
        ]
        result = EvalResult(
            repo_name="test/repo",
            pr_number=789,
            description="PR with findings",
            success=True,
            runtime_seconds=15.0,
            findings_count=1,
            detected_vulnerabilities=True,
            findings_summary=findings,
            full_findings=findings
        )
        
        assert result.findings_count == 1
        assert result.detected_vulnerabilities is True
        assert result.findings_summary is not None
        assert len(result.findings_summary) == 1
    
    def test_eval_result_to_dict(self):
        """Test converting EvalResult to dictionary."""
        result = EvalResult(
            repo_name="test/repo",
            pr_number=123,
            description="Test",
            success=True,
            runtime_seconds=10.0,
            findings_count=0,
            detected_vulnerabilities=False
        )
        
        result_dict = result.to_dict()
        assert result_dict['repo_name'] == "test/repo"
        assert result_dict['pr_number'] == 123
        assert result_dict['success'] is True


class TestEvalCase:
    """Test the EvalCase dataclass."""
    
    def test_eval_case_creation(self):
        """Test creating an EvalCase instance."""
        case = EvalCase(
            repo_name="test/repo",
            pr_number=123,
            description="Test case"
        )
        
        assert case.repo_name == "test/repo"
        assert case.pr_number == 123
        assert case.description == "Test case"


class TestEvaluationEngine:
    """Test the EvaluationEngine class."""
    
    def test_engine_initialization(self):
        """Test engine initialization with API key."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            engine = EvaluationEngine()
            
            assert engine.work_dir == os.path.expanduser("~/code/audit")
            assert engine.claude_api_key == 'test-key'
    
    def test_engine_initialization_no_api_key(self):
        """Test engine initialization without API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                EvaluationEngine()
    
    def test_get_eval_branch_name(self):
        """Test branch name generation."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            engine = EvaluationEngine()
            
            case = EvalCase("owner/repo", 123)
            branch_name = engine._get_eval_branch_name(case)
            
            assert branch_name.startswith("eval-pr-owner-repo-123-")
            assert len(branch_name) > len("eval-pr-owner-repo-123-")
    
    @patch('os.path.exists')
    @patch('subprocess.run')
    def test_clean_worktrees(self, mock_run, mock_exists):
        """Test worktree cleanup."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            # Mock git auth token call in __init__
            mock_run.side_effect = [
                Mock(returncode=1, stdout=""),  # gh auth token (fails, no token)
                Mock(returncode=0),  # prune
                Mock(returncode=0, stdout=""),  # list (empty)
                Mock(returncode=0, stdout=""),  # branch --list (empty)
            ]
            
            engine = EvaluationEngine()
            
            mock_exists.return_value = True  # repo_path exists
            
            engine._clean_worktrees("/repo/path", "eval-pr-test-123")
            
            # Should call run four times: gh auth token (in __init__), prune, list, branch --list
            assert mock_run.call_count == 4
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_setup_repository_clone(self, mock_exists, mock_run):
        """Test repository setup with cloning."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            mock_exists.return_value = False  # Repository doesn't exist
            mock_run.side_effect = [
                Mock(returncode=1, stdout=""),  # gh auth token (fails, no token)
                Mock(returncode=0),  # git clone
                Mock(returncode=0),  # git fetch
                Mock(returncode=0),  # git worktree add
            ]
            
            engine = EvaluationEngine()
            
            case = EvalCase("owner/repo", 123)
            success, worktree_path, error = engine._setup_repository(case)
            
            assert success is True
            assert worktree_path != ""
            assert error == ""
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_setup_repository_clone_does_not_leak_token_in_argv(self, mock_exists, mock_run):
        """Regression test: when ``github_token`` is set, the token must
        NOT appear in the argv of any ``subprocess.run`` call. argv is
        visible to every other user on the host via ``ps``, so embedding
        the token there is a credential exposure. The fix uses
        ``GIT_ASKPASS`` + an env var so the token only lives in this
        process's environment and a mode-0700 helper file."""
        mock_exists.return_value = False  # Repository doesn't exist
        secret_token = 'ghp_secret_token_must_not_appear_in_argv_AAAAAAAAAAAAAAAAAAAA'
        mock_run.side_effect = [
            Mock(returncode=0, stdout=secret_token + '\n'),  # gh auth token
            Mock(returncode=0),  # git clone
            Mock(returncode=0),  # git fetch
            Mock(returncode=0),  # git worktree add
        ]
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}, clear=False):
            os.environ.pop('GITHUB_TOKEN', None)
            engine = EvaluationEngine()
            assert engine.github_token == secret_token

            case = EvalCase("owner/repo", 123)
            success, _, _ = engine._setup_repository(case)
            assert success is True

        # Walk every recorded subprocess.run call and confirm the token
        # never appears in any positional or keyword argv.
        for call in mock_run.call_args_list:
            argv = call.args[0] if call.args else call.kwargs.get('args', [])
            for arg in argv:
                assert secret_token not in str(arg), (
                    f"github token leaked into subprocess argv: {arg!r}"
                )

        # The clone URL should use the ``x-access-token`` placeholder
        # username rather than embedding the token. argv[1] is the git
        # subcommand; the URL is the second-to-last positional arg.
        clone_call = mock_run.call_args_list[1]
        clone_argv = clone_call.args[0]
        assert any('x-access-token@github.com' in str(a) for a in clone_argv), (
            f"expected x-access-token placeholder in clone argv, got {clone_argv!r}"
        )
        # GIT_ASKPASS must be set in the env passed to the clone subprocess.
        clone_env = clone_call.kwargs.get('env') or {}
        assert clone_env.get('GIT_ASKPASS'), (
            "GIT_ASKPASS must be set on the clone subprocess env"
        )
        assert clone_env.get('GIT_AUTH_TOKEN') == secret_token

    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_setup_repository_existing(self, mock_exists, mock_run):
        """Test repository setup with existing repository."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            # First call checks base_repo_path, second checks repo_path inside _clean_worktrees
            mock_exists.side_effect = [True, True]
            mock_run.side_effect = [
                Mock(returncode=1, stdout=""),  # gh auth token (fails, no token)
                Mock(returncode=0),  # worktree prune
                Mock(returncode=0, stdout=""),  # worktree list
                Mock(returncode=0, stdout=""),  # git branch --list
                Mock(returncode=0),  # git fetch
                Mock(returncode=0),  # git worktree add
            ]
            
            engine = EvaluationEngine()
            
            case = EvalCase("owner/repo", 123)
            success, worktree_path, error = engine._setup_repository(case)
            
            assert success is True
            assert error == ""
    
    @patch('subprocess.run')
    def test_run_sast_audit_success(self, mock_run):
        """Test successful SAST audit run."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            # Mock gh auth token call first, then the audit
            mock_run.side_effect = [
                Mock(returncode=1, stdout=""),  # gh auth token (fails, no token)
                Mock(returncode=0, stdout=json.dumps({
                    "findings": [
                        {"file": "test.py", "line": 10, "severity": "HIGH"}
                    ]
                }), stderr="")  # SAST audit
            ]
            
            engine = EvaluationEngine()
            
            case = EvalCase("owner/repo", 123)
            success, output, parsed, error = engine._run_sast_audit(case, "/repo/path")
            
            assert success is True
            assert parsed is not None
            assert len(parsed["findings"]) == 1
            assert error is None
    
    @patch('subprocess.run')
    def test_run_sast_audit_failure(self, mock_run):
        """Test failed SAST audit run."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            mock_run.side_effect = [
                Mock(returncode=1, stdout=""),  # gh auth token (fails, no token)
                Mock(returncode=1, stdout="", stderr="Error running audit")  # SAST audit fails
            ]
            
            engine = EvaluationEngine()
            
            case = EvalCase("owner/repo", 123)
            success, output, parsed, error = engine._run_sast_audit(case, "/repo/path")
            
            assert success is False
            assert error is not None
            assert "Exit code 1" in error
    
    @patch.object(EvaluationEngine, '_setup_repository')
    @patch.object(EvaluationEngine, '_run_sast_audit')
    @patch.object(EvaluationEngine, '_cleanup_worktree')
    def test_run_evaluation_success(self, mock_cleanup, mock_audit, mock_setup):
        """Test successful evaluation run."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            engine = EvaluationEngine()
            
            mock_setup.return_value = (True, "/worktree/path", "")
            mock_audit.return_value = (
                True,
                '{"findings": [{"file": "test.py", "line": 10}]}',
                {"findings": [{"file": "test.py", "line": 10}]},
                None
            )
            
            case = EvalCase("owner/repo", 123, "Test PR")
            result = engine.run_evaluation(case)
            
            assert result.success is True
            assert result.findings_count == 1
            assert result.detected_vulnerabilities is True
            assert result.findings_summary is not None
            assert len(result.findings_summary) == 1
            
            mock_cleanup.assert_called_once()
    
    @patch.object(EvaluationEngine, '_setup_repository')
    def test_run_evaluation_setup_failure(self, mock_setup):
        """Test evaluation with repository setup failure."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            engine = EvaluationEngine()
            
            mock_setup.return_value = (False, "", "Clone failed")
            
            case = EvalCase("owner/repo", 123, "Test PR")
            result = engine.run_evaluation(case)
            
            assert result.success is False
            assert result.findings_count == 0
            assert "Repository setup failed" in result.error_message


class TestHelperFunctions:
    """Test helper functions."""
    
    @patch.object(EvaluationEngine, 'run_evaluation')
    def test_run_single_evaluation(self, mock_run):
        """Test run_single_evaluation helper."""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            mock_result = Mock(spec=EvalResult)
            mock_run.return_value = mock_result
            
            case = EvalCase("owner/repo", 123)
            result = run_single_evaluation(case, verbose=True)
            
            assert result == mock_result
            mock_run.assert_called_once_with(case)