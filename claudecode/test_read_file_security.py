#!/usr/bin/env python3
"""
Tests for path-traversal protection in ClaudeAPIClient._read_file().

Covers:
  - normal relative paths (should succeed)
  - ".." traversal attempts (should be blocked)
  - absolute paths (should be blocked)
  - symlinks that escape the repo root (should be blocked)
  - empty / whitespace-only paths (should be blocked)
  - encoding fallback (latin-1 for binary-ish files)
"""

import os
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """Return a ClaudeAPIClient whose API key check is satisfied."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy-key")
    from claudecode.claude_api_client import ClaudeAPIClient
    return ClaudeAPIClient(api_key="sk-test-dummy-key")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo_tree(tmp_path):
    """Create a minimal fake repository tree and set REPO_PATH."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # a normal source file
    normal_file = src_dir / "main.py"
    normal_file.write_text("print('hello')\n", encoding="utf-8")

    # a file with non-UTF-8 content (latin-1)
    latin_file = src_dir / "legacy.txt"
    latin_file.write_bytes(b"caf\xe9\n")

    # a file right at the root
    root_file = tmp_path / "README.md"
    root_file.write_text("# Readme\n", encoding="utf-8")

    # a symlink that points OUTSIDE the repo
    outside_dir = tmp_path.parent / "outside_secret"
    outside_dir.mkdir(exist_ok=True)
    secret_file = outside_dir / "secret.txt"
    secret_file.write_text("TOP SECRET\n", encoding="utf-8")

    escape_link = tmp_path / "escape_link.txt"
    escape_link.symlink_to(secret_file)

    old_repo = os.environ.get("REPO_PATH")
    os.environ["REPO_PATH"] = str(tmp_path)
    yield tmp_path
    # teardown
    if old_repo is None:
        os.environ.pop("REPO_PATH", None)
    else:
        os.environ["REPO_PATH"] = old_repo


# ---------------------------------------------------------------------------
# Tests — happy paths
# ---------------------------------------------------------------------------

class TestReadFileHappyPaths:
    """Legitimate file reads that should succeed."""

    def test_read_relative_path(self, repo_tree):
        client = _make_client()
        ok, content, err = client._read_file("src/main.py")
        assert ok is True
        assert "hello" in content
        assert err == ""

    def test_read_file_at_root(self, repo_tree):
        client = _make_client()
        ok, content, err = client._read_file("README.md")
        assert ok is True
        assert "Readme" in content

    def test_read_latin1_fallback(self, repo_tree):
        client = _make_client()
        ok, content, err = client._read_file("src/legacy.txt")
        assert ok is True
        assert "caf" in content


# ---------------------------------------------------------------------------
# Tests — path traversal attacks
# ---------------------------------------------------------------------------

class TestReadFilePathTraversal:
    """Malicious paths that must be rejected."""

    def test_dotdot_traversal_blocked(self, repo_tree):
        client = _make_client()
        ok, content, err = client._read_file("../../../etc/passwd")
        assert ok is False
        assert content == ""
        assert "outside the repository root" in err

    def test_dotdot_with_subdir_prefix(self, repo_tree):
        """src/../../etc/passwd should still be blocked."""
        client = _make_client()
        ok, content, err = client._read_file("src/../../etc/passwd")
        assert ok is False
        assert "outside the repository root" in err or "not found" in err.lower()

    def test_absolute_path_blocked(self, repo_tree):
        client = _make_client()
        ok, _, err = client._read_file("/etc/passwd")
        assert ok is False
        assert "Absolute paths are not allowed" in err

    def test_symlink_escape_blocked(self, repo_tree):
        """A symlink inside the repo pointing outside must be caught."""
        client = _make_client()
        ok, content, err = client._read_file("escape_link.txt")
        assert ok is False
        assert content == ""
        assert "outside the repository root" in err


# ---------------------------------------------------------------------------
# Tests — edge cases
# ---------------------------------------------------------------------------

class TestReadFileEdgeCases:
    """Edge cases and malformed input."""

    def test_empty_string(self, repo_tree):
        client = _make_client()
        ok, _, err = client._read_file("")
        assert ok is False
        assert "Empty file path" in err

    def test_whitespace_only(self, repo_tree):
        client = _make_client()
        ok, _, err = client._read_file("   ")
        assert ok is False
        assert "Empty file path" in err

    def test_nonexistent_file(self, repo_tree):
        client = _make_client()
        ok, _, err = client._read_file("does_not_exist.py")
        assert ok is False
        assert "not found" in err.lower()

    def test_directory_not_file(self, repo_tree):
        client = _make_client()
        ok, _, err = client._read_file("src")
        assert ok is False
        assert "not a file" in err.lower()

    def test_dotdot_reaching_root_exactly(self, repo_tree):
        """src/.. resolves to the repo root itself — directory, not a file."""
        client = _make_client()
        ok, _, err = client._read_file("src/..")
        assert ok is False


# ---------------------------------------------------------------------------
# Tests — without REPO_PATH (falls back to cwd)
# ---------------------------------------------------------------------------

class TestReadFileWithoutRepoPath:
    """When REPO_PATH is unset, cwd is used as root."""

    def test_falls_back_to_cwd(self, tmp_path):
        test_file = tmp_path / "hello.txt"
        test_file.write_text("world\n")

        old_repo = os.environ.pop("REPO_PATH", None)
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            client = _make_client()
            ok, content, _ = client._read_file("hello.txt")
            assert ok is True
            assert "world" in content
        finally:
            os.chdir(old_cwd)
            if old_repo is not None:
                os.environ["REPO_PATH"] = old_repo

    def test_traversal_blocked_without_repo_path(self, tmp_path):
        old_repo = os.environ.pop("REPO_PATH", None)
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            client = _make_client()
            ok, _, err = client._read_file("../../../etc/passwd")
            assert ok is False
            assert "outside the repository root" in err
        finally:
            os.chdir(old_cwd)
            if old_repo is not None:
                os.environ["REPO_PATH"] = old_repo
