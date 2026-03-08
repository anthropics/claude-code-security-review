#!/usr/bin/env python3
"""
Unit tests for GitHubActionClient.
"""

import pytest
import os
import subprocess
from unittest.mock import Mock, patch, MagicMock

from claudecode.github_action_audit import GitHubActionClient, DiffTooLargeError


class TestGitHubActionClient:
    """Test GitHubActionClient functionality."""
    
    def test_init_requires_token(self):
        """Test that client initialization requires GITHUB_TOKEN."""
        # Remove token if it exists
        original_token = os.environ.pop('GITHUB_TOKEN', None)
        
        try:
            with pytest.raises(ValueError, match="GITHUB_TOKEN environment variable required"):
                GitHubActionClient()
        finally:
            # Restore token
            if original_token:
                os.environ['GITHUB_TOKEN'] = original_token
    
    def test_init_with_token(self):
        """Test successful initialization with token."""
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            assert client.github_token == 'test-token'
            assert client.headers['Authorization'] == 'Bearer test-token'
            assert 'Accept' in client.headers
            assert 'X-GitHub-Api-Version' in client.headers
    
    @patch('requests.get')
    def test_get_pr_data_success(self, mock_get):
        """Test successful PR data retrieval."""
        # Mock responses
        pr_response = Mock()
        pr_response.json.return_value = {
            'number': 123,
            'title': 'Test PR',
            'body': 'PR description',
            'user': {'login': 'testuser'},
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2024-01-01T01:00:00Z',
            'state': 'open',
            'head': {
                'ref': 'feature-branch',
                'sha': 'abc123',
                'repo': {
                    'full_name': 'owner/repo'
                }
            },
            'base': {
                'ref': 'main',
                'sha': 'def456'
            },
            'additions': 50,
            'deletions': 10,
            'changed_files': 3
        }
        
        files_response = Mock()
        files_response.json.return_value = [
            {
                'filename': 'src/main.py',
                'status': 'modified',
                'additions': 30,
                'deletions': 5,
                'changes': 35,
                'patch': '@@ -1,5 +1,10 @@\n+import os\n def main():'
            },
            {
                'filename': 'tests/test_main.py',
                'status': 'added',
                'additions': 20,
                'deletions': 5,
                'changes': 25,
                'patch': '@@ -0,0 +1,20 @@\n+def test_main():'
            }
        ]
        
        mock_get.side_effect = [pr_response, files_response]
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            result = client.get_pr_data('owner/repo', 123)
        
        # Verify API calls
        assert mock_get.call_count == 2
        mock_get.assert_any_call(
            'https://api.github.com/repos/owner/repo/pulls/123',
            headers=client.headers
        )
        mock_get.assert_any_call(
            'https://api.github.com/repos/owner/repo/pulls/123/files?per_page=100',
            headers=client.headers
        )
        
        # Verify result structure
        assert result['number'] == 123
        assert result['title'] == 'Test PR'
        assert result['user'] == 'testuser'
        assert len(result['files']) == 2
        assert result['files'][0]['filename'] == 'src/main.py'
        assert result['files'][1]['status'] == 'added'
    
    @patch('requests.get')
    def test_get_pr_data_null_head_repo(self, mock_get):
        """Test PR data retrieval when head repo is null (deleted fork)."""
        pr_response = Mock()
        pr_response.json.return_value = {
            'number': 123,
            'title': 'Test PR',
            # Don't include body key to test the get() default
            'user': {'login': 'testuser'},
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2024-01-01T01:00:00Z',
            'state': 'open',
            'head': {
                'ref': 'feature-branch',
                'sha': 'abc123',
                'repo': None  # Deleted fork
            },
            'base': {
                'ref': 'main',
                'sha': 'def456'
            },
            'additions': 50,
            'deletions': 10,
            'changed_files': 3
        }
        
        files_response = Mock()
        files_response.json.return_value = []
        
        mock_get.side_effect = [pr_response, files_response]
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            result = client.get_pr_data('owner/repo', 123)
        
        # Should use original repo name when head repo is None
        assert result['head']['repo']['full_name'] == 'owner/repo'
        # The implementation passes None through, test should match that
        assert result['body'] == ''
    
    @patch('requests.get')
    def test_get_pr_data_api_error(self, mock_get):
        """Test PR data retrieval with API error."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            with pytest.raises(Exception, match="API Error"):
                client.get_pr_data('owner/repo', 123)
    
    @patch('requests.get')
    def test_get_pr_diff_success(self, mock_get):
        """Test successful PR diff retrieval."""
        diff_content = """diff --git a/src/main.py b/src/main.py
index abc123..def456 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,10 @@
+import os
 def main():
     print("Hello")
+    # New feature
+    process_data()
"""
        
        mock_response = Mock()
        mock_response.text = diff_content
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            result = client.get_pr_diff('owner/repo', 123)
        
        # Verify API call
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == 'https://api.github.com/repos/owner/repo/pulls/123'
        assert call_args[1]['headers']['Accept'] == 'application/vnd.github.diff'
        
        # Verify result
        assert 'import os' in result
        assert 'process_data()' in result
    
    @patch('requests.get')
    def test_get_pr_diff_filters_generated_files(self, mock_get):
        """Test that generated files are filtered from diff."""
        diff_with_generated = """diff --git a/src/main.py b/src/main.py
index abc123..def456 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,10 @@
+import os
 def main():
     print("Hello")
diff --git a/generated/code.py b/generated/code.py
index 111..222 100644
--- a/generated/code.py
+++ b/generated/code.py
@@ -1,3 +1,5 @@
# @generated by protoc
+# More generated code
+print("generated")
diff --git a/src/feature.py b/src/feature.py
index 333..444 100644
--- a/src/feature.py
+++ b/src/feature.py
@@ -1,3 +1,5 @@
+# Real code
 def feature():
     pass
"""
        
        mock_response = Mock()
        mock_response.text = diff_with_generated
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            result = client.get_pr_diff('owner/repo', 123)
        
        # Verify generated file is filtered out
        assert 'src/main.py' in result
        assert 'src/feature.py' in result
        assert 'generated/code.py' not in result
        assert '@generated' not in result
        assert 'More generated code' not in result
    
    def test_filter_generated_files_edge_cases(self):
        """Test edge cases in generated file filtering."""
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            
            # Empty diff
            assert client._filter_generated_files('') == ''
            
            # No diff markers - if no diff format, everything is filtered
            text = "Just some random text\nwith @generated in it"
            # Since there's no 'diff --git' marker, the split results in one section
            # that contains @generated, so it gets filtered out
            assert client._filter_generated_files(text) == ''
            
            # Multiple generated markers
            diff = """diff --git a/a.py b/a.py
@generated by tool
content
diff --git a/b.py b/b.py
normal content
diff --git a/c.py b/c.py
# This file is @generated
more content
"""
            result = client._filter_generated_files(diff)
            assert 'a.py' not in result
            assert 'b.py' in result
            assert 'c.py' not in result


class TestGitHubAPIIntegration:
    """Test GitHub API integration scenarios."""
    
    @patch('requests.get')
    def test_rate_limit_handling(self, mock_get):
        """Test that rate limit headers are respected."""
        mock_response = Mock()
        mock_response.headers = {
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': '1234567890'
        }
        mock_response.status_code = 403
        mock_response.json.return_value = {
            'message': 'API rate limit exceeded'
        }
        mock_response.raise_for_status.side_effect = Exception("Rate limit exceeded")
        mock_get.return_value = mock_response
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            with pytest.raises(Exception, match="Rate limit exceeded"):
                client.get_pr_data('owner/repo', 123)
    
    @patch('requests.get')
    def test_pagination_not_needed_for_pr_files(self, mock_get):
        """Test that PR files endpoint returns all files without pagination."""
        # GitHub API returns up to 3000 files per PR without pagination
        large_file_list = [
            {
                'filename': f'file{i}.py',
                'status': 'added',
                'additions': 10,
                'deletions': 0,
                'changes': 10,
                'patch': f'@@ -0,0 +1,10 @@\n+# File {i}'
            }
            for i in range(100)  # 100 files
        ]
        
        pr_response = Mock()
        pr_response.json.return_value = {
            'number': 123,
            'title': 'Large PR',
            'body': 'Many files',
            'user': {'login': 'testuser'},
            'created_at': '2024-01-01T00:00:00Z',
            'updated_at': '2024-01-01T01:00:00Z',
            'state': 'open',
            'head': {'ref': 'feature', 'sha': 'abc123', 'repo': {'full_name': 'owner/repo'}},
            'base': {'ref': 'main', 'sha': 'def456'},
            'additions': 1000,
            'deletions': 0,
            'changed_files': 100
        }
        
        files_response = Mock()
        files_response.json.return_value = large_file_list
        
        mock_get.side_effect = [pr_response, files_response]
        
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            result = client.get_pr_data('owner/repo', 123)
        
        assert len(result['files']) == 100
        assert result['files'][0]['filename'] == 'file0.py'
        assert result['files'][99]['filename'] == 'file99.py'


class TestDiffTooLarge:
    """Test handling of large PR diffs that exceed GitHub's 20,000-line API limit."""

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_falls_back_to_local_git_diff(self, mock_get, mock_subprocess):
        """Test that a 406 response triggers local git diff fallback."""
        # Mock GitHub API returning 406
        mock_response = Mock()
        mock_response.status_code = 406
        mock_response.text = "Sorry, the diff exceeded the maximum number of lines (20000)"
        mock_get.return_value = mock_response

        # Mock successful local git diff
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="diff --git a/src/main.py b/src/main.py\n+import os\n",
            stderr=""
        )

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            result = client.get_pr_diff('owner/repo', 123, base_ref='main')

        # Should have attempted local git diff
        assert mock_subprocess.called
        assert 'import os' in result

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_tries_base_ref_first(self, mock_get, mock_subprocess):
        """Test that fallback tries origin/base_ref...HEAD before HEAD~1."""
        mock_response = Mock()
        mock_response.status_code = 406
        mock_get.return_value = mock_response

        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n+new code\n",
            stderr=""
        )

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            client.get_pr_diff('owner/repo', 123, base_ref='main')

        # First call should be git diff origin/main...HEAD
        first_call_args = mock_subprocess.call_args_list[0]
        assert first_call_args[0][0] == ['git', 'diff', 'origin/main...HEAD']

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_falls_back_to_head_parent(self, mock_get, mock_subprocess):
        """Test that if origin/base...HEAD fails, falls back to HEAD~1."""
        mock_response = Mock()
        mock_response.status_code = 406
        mock_get.return_value = mock_response

        # First call (origin/main...HEAD) fails, second (HEAD~1) succeeds
        mock_subprocess.side_effect = [
            Mock(returncode=128, stdout="", stderr="fatal: bad revision"),
            Mock(returncode=0, stdout="diff --git a/file.py b/file.py\n+code\n", stderr="")
        ]

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            result = client.get_pr_diff('owner/repo', 123, base_ref='main')

        assert mock_subprocess.call_count == 2
        second_call_args = mock_subprocess.call_args_list[1]
        assert second_call_args[0][0] == ['git', 'diff', 'HEAD~1']
        assert '+code' in result

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_no_base_ref_uses_head_parent(self, mock_get, mock_subprocess):
        """Test fallback without base_ref only tries HEAD~1."""
        mock_response = Mock()
        mock_response.status_code = 406
        mock_get.return_value = mock_response

        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n+code\n",
            stderr=""
        )

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            client.get_pr_diff('owner/repo', 123, base_ref=None)

        # Should only try HEAD~1 (no base_ref provided)
        assert mock_subprocess.call_count == 1
        call_args = mock_subprocess.call_args_list[0]
        assert call_args[0][0] == ['git', 'diff', 'HEAD~1']

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_all_fallbacks_fail_raises_error(self, mock_get, mock_subprocess):
        """Test that DiffTooLargeError is raised when all fallbacks fail."""
        mock_response = Mock()
        mock_response.status_code = 406
        mock_get.return_value = mock_response

        # Both local git diff attempts fail
        mock_subprocess.return_value = Mock(
            returncode=128,
            stdout="",
            stderr="fatal: bad revision 'origin/main...HEAD'"
        )

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            with pytest.raises(DiffTooLargeError, match="PR diff exceeds GitHub API limit"):
                client.get_pr_diff('owner/repo', 123, base_ref='main')

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_git_diff_timeout_raises_error(self, mock_get, mock_subprocess):
        """Test that git diff timeout is handled gracefully."""
        mock_response = Mock()
        mock_response.status_code = 406
        mock_get.return_value = mock_response

        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd='git diff', timeout=120)

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            with pytest.raises(DiffTooLargeError, match="timed out"):
                client.get_pr_diff('owner/repo', 123, base_ref=None)

    @patch('requests.get')
    def test_get_pr_diff_non_406_error_still_raises(self, mock_get):
        """Test that non-406 HTTP errors still raise normally."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = Exception("Internal Server Error")
        mock_get.return_value = mock_response

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            with pytest.raises(Exception, match="Internal Server Error"):
                client.get_pr_diff('owner/repo', 123)

    @patch('subprocess.run')
    @patch('requests.get')
    def test_get_pr_diff_406_local_diff_filters_generated_files(self, mock_get, mock_subprocess):
        """Test that local git diff output is filtered for generated files."""
        mock_response = Mock()
        mock_response.status_code = 406
        mock_get.return_value = mock_response

        diff_with_generated = """diff --git a/src/main.py b/src/main.py
+real code
diff --git a/generated/api.py b/generated/api.py
# @generated by protoc
+generated code
"""
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=diff_with_generated,
            stderr=""
        )

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'REPO_PATH': '/tmp/repo'}):
            client = GitHubActionClient()
            result = client.get_pr_diff('owner/repo', 123, base_ref='main')

        # Generated file should be filtered out
        assert 'src/main.py' in result
        assert 'generated/api.py' not in result
