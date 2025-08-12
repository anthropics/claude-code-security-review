#!/usr/bin/env python3
"""
Pytest tests for Windows filesystem cleanup functionality.

This module validates the Windows-specific cleanup utilities that fix
recursion errors in temporary directory cleanup operations.
"""

import os
import sys
import tempfile
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from .platform_utils import get_platform_adapter, is_windows, safe_rmtree, create_safe_tempdir
from .safe_temp import safe_temp_directory, SafeTemporaryDirectory
from .windows_cleanup import safe_windows_rmtree, create_safe_tempdir as windows_create_safe_tempdir


class TestPlatformDetection:
    """Test platform detection functionality."""
    
    def test_platform_adapter_creation(self):
        """Test that platform adapter can be created."""
        adapter = get_platform_adapter()
        assert adapter is not None
        assert hasattr(adapter, 'is_windows')
        assert hasattr(adapter, 'safe_rmtree')
        assert hasattr(adapter, 'create_safe_tempdir')
    
    def test_is_windows_function(self):
        """Test the is_windows helper function."""
        result = is_windows()
        assert isinstance(result, bool)
        # Should match platform detection
        adapter = get_platform_adapter()
        assert result == adapter.is_windows()
    
    def test_windows_detection_consistency(self):
        """Test that all Windows detection methods are consistent."""
        adapter = get_platform_adapter()
        is_win_func = is_windows()
        is_win_platform = sys.platform.startswith('win')
        
        assert adapter.is_windows() == is_win_func
        assert adapter.is_windows() == is_win_platform


class TestSafeTempDirectoryOperations:
    """Test safe temporary directory creation and cleanup."""
    
    def test_create_safe_tempdir(self):
        """Test safe temporary directory creation."""
        temp_dir = create_safe_tempdir("test_claude_")
        try:
            assert os.path.exists(temp_dir)
            assert os.path.isdir(temp_dir)
            assert "test_claude_" in os.path.basename(temp_dir)
        finally:
            # Clean up
            if os.path.exists(temp_dir):
                safe_rmtree(temp_dir, ignore_errors=True)
    
    def test_create_safe_tempdir_with_content(self):
        """Test temporary directory with nested content."""
        temp_dir = create_safe_tempdir("content_test_")
        try:
            # Create nested structure
            test_subdir = os.path.join(temp_dir, "subdir")
            os.makedirs(test_subdir, exist_ok=True)
            
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, "w") as f:
                f.write("Test content")
            
            nested_file = os.path.join(test_subdir, "nested.txt")
            with open(nested_file, "w") as f:
                f.write("Nested content")
            
            # Verify structure
            assert os.path.exists(test_file)
            assert os.path.exists(nested_file)
            assert os.path.isdir(test_subdir)
            
        finally:
            # Clean up
            if os.path.exists(temp_dir):
                safe_rmtree(temp_dir, ignore_errors=True)
    
    def test_safe_rmtree_success(self):
        """Test successful directory removal."""
        temp_dir = create_safe_tempdir("rmtree_test_")
        
        # Create content
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("Test content")
        
        # Verify exists before removal
        assert os.path.exists(temp_dir)
        assert os.path.exists(test_file)
        
        # Remove
        start_time = time.time()
        success = safe_rmtree(temp_dir, ignore_errors=False)
        cleanup_time = time.time() - start_time
        
        # Verify removal
        assert success is True
        assert not os.path.exists(temp_dir)
        assert cleanup_time < 5.0  # Should be fast, not stuck in recursion
    
    def test_safe_rmtree_nonexistent(self):
        """Test cleanup of non-existent directory."""
        fake_dir = os.path.join(tempfile.gettempdir(), "non_existent_dir_12345")
        
        # Should handle gracefully
        result = safe_rmtree(fake_dir, ignore_errors=True)
        assert result is True  # Non-existent directories return True
        
        # Should also work with ignore_errors=False
        result = safe_rmtree(fake_dir, ignore_errors=False)
        assert result is True


class TestSafeTempDirectoryContextManager:
    """Test the safe temporary directory context manager."""
    
    def test_context_manager_basic(self):
        """Test basic context manager functionality."""
        temp_dir_path = None
        
        with safe_temp_directory("context_test_") as temp_dir:
            temp_dir_path = temp_dir
            assert os.path.exists(temp_dir)
            assert os.path.isdir(temp_dir)
            assert "context_test_" in os.path.basename(temp_dir)
        
        # Should be cleaned up after context exit
        assert not os.path.exists(temp_dir_path)
    
    def test_context_manager_with_content(self):
        """Test context manager with file creation."""
        temp_dir_path = None
        test_file_path = None
        
        with safe_temp_directory("content_ctx_") as temp_dir:
            temp_dir_path = temp_dir
            
            # Create content
            test_file_path = os.path.join(temp_dir, "context_test.txt")
            with open(test_file_path, "w") as f:
                f.write("Context manager test")
            
            # Verify during context
            assert os.path.exists(test_file_path)
            
        # Should be cleaned up after context exit
        assert not os.path.exists(temp_dir_path)
        assert not os.path.exists(test_file_path)
    
    def test_context_manager_exception_handling(self):
        """Test context manager cleanup on exception."""
        temp_dir_path = None
        
        try:
            with safe_temp_directory("exception_test_") as temp_dir:
                temp_dir_path = temp_dir
                assert os.path.exists(temp_dir)
                
                # Create some content
                test_file = os.path.join(temp_dir, "test.txt")
                with open(test_file, "w") as f:
                    f.write("Test content")
                
                # Raise exception
                raise ValueError("Test exception")
                
        except ValueError:
            pass  # Expected
        
        # Should still be cleaned up despite exception
        if temp_dir_path:
            assert not os.path.exists(temp_dir_path)


class TestSafeTemporaryDirectoryClass:
    """Test the SafeTemporaryDirectory class."""
    
    def test_safe_temporary_directory_class(self):
        """Test SafeTemporaryDirectory class basic functionality."""
        with SafeTemporaryDirectory() as temp_dir:
            assert os.path.exists(temp_dir)
            assert os.path.isdir(temp_dir)
            
            # Create test content
            test_file = os.path.join(temp_dir, "class_test.txt")
            with open(test_file, "w") as f:
                f.write("Class test content")
            
            assert os.path.exists(test_file)
        
        # Should be cleaned up
        assert not os.path.exists(temp_dir)
        assert not os.path.exists(test_file)
    
    def test_safe_temporary_directory_with_prefix(self):
        """Test SafeTemporaryDirectory with custom prefix."""
        with SafeTemporaryDirectory(prefix="custom_prefix_") as temp_dir:
            assert "custom_prefix_" in os.path.basename(temp_dir)
            assert os.path.exists(temp_dir)
        
        assert not os.path.exists(temp_dir)
    
    def test_safe_temporary_directory_reuse_protection(self):
        """Test that SafeTemporaryDirectory prevents concurrent reuse."""
        safe_temp = SafeTemporaryDirectory()
        
        # Test that we can't enter context twice concurrently
        safe_temp.__enter__()
        try:
            # This should raise an error since we're already in context
            with pytest.raises(RuntimeError, match="Temporary directory already created"):
                safe_temp.__enter__()
        finally:
            # Clean up properly
            safe_temp.__exit__(None, None, None)
        
        # After cleanup, should be able to reuse
        with safe_temp as temp_dir:
            assert os.path.exists(temp_dir)


class TestWindowsSpecificFunctionality:
    """Test Windows-specific cleanup functionality."""
    
    def test_windows_rmtree_function(self):
        """Test the Windows-specific rmtree function."""
        if not is_windows():
            pytest.skip("Windows-specific test")
        
        temp_dir = windows_create_safe_tempdir("win_test_")
        try:
            # Create content
            test_file = os.path.join(temp_dir, "windows_test.txt")
            with open(test_file, "w") as f:
                f.write("Windows test content")
            
            assert os.path.exists(temp_dir)
            assert os.path.exists(test_file)
            
            # Use Windows-specific cleanup
            success = safe_windows_rmtree(temp_dir, ignore_errors=False)
            assert success is True
            assert not os.path.exists(temp_dir)
            
        except Exception:
            # Fallback cleanup if test fails
            if os.path.exists(temp_dir):
                safe_rmtree(temp_dir, ignore_errors=True)
            raise
    
    def test_cross_platform_compatibility(self):
        """Test that Windows functions work on all platforms."""
        # This should work on both Windows and non-Windows
        temp_dir = windows_create_safe_tempdir("cross_platform_")
        try:
            # Create content
            test_file = os.path.join(temp_dir, "cross_platform.txt")
            with open(test_file, "w") as f:
                f.write("Cross-platform test")
            
            assert os.path.exists(temp_dir)
            
            # Should work regardless of platform
            success = safe_windows_rmtree(temp_dir, ignore_errors=True)
            assert success is True
            assert not os.path.exists(temp_dir)
            
        except Exception:
            # Fallback cleanup
            if os.path.exists(temp_dir):
                safe_rmtree(temp_dir, ignore_errors=True)
            raise


class TestPerformanceAndReliability:
    """Test performance and reliability of cleanup operations."""
    
    def test_cleanup_performance(self):
        """Test that cleanup operations complete in reasonable time."""
        temp_dir = create_safe_tempdir("perf_test_")
        try:
            # Create multiple nested directories and files
            for i in range(10):
                subdir = os.path.join(temp_dir, f"subdir_{i}")
                os.makedirs(subdir, exist_ok=True)
                
                for j in range(5):
                    test_file = os.path.join(subdir, f"file_{j}.txt")
                    with open(test_file, "w") as f:
                        f.write(f"Content for file {i}-{j}")
            
            # Measure cleanup time
            start_time = time.time()
            success = safe_rmtree(temp_dir, ignore_errors=False)
            cleanup_time = time.time() - start_time
            
            assert success is True
            assert not os.path.exists(temp_dir)
            assert cleanup_time < 10.0  # Should complete within 10 seconds
            
        except Exception:
            # Cleanup on failure
            if os.path.exists(temp_dir):
                safe_rmtree(temp_dir, ignore_errors=True)
            raise
    
    def test_error_recovery(self):
        """Test error recovery and graceful handling."""
        # Test with ignore_errors=True
        fake_dir = "/definitely/does/not/exist/12345"
        result = safe_rmtree(fake_dir, ignore_errors=True)
        assert result is True  # Should succeed gracefully
        
        # Test context manager error recovery
        temp_dir_path = None
        try:
            with safe_temp_directory("error_recovery_") as temp_dir:
                temp_dir_path = temp_dir
                # Create content that might be hard to clean up
                test_file = os.path.join(temp_dir, "test.txt")
                with open(test_file, "w") as f:
                    f.write("Test content")
                
                # Even if something goes wrong, cleanup should still work
                pass
        except Exception:
            pass
        
        # Should be cleaned up regardless
        if temp_dir_path:
            assert not os.path.exists(temp_dir_path)


# Integration test that can be run standalone
def test_windows_cleanup_integration():
    """Integration test for complete Windows cleanup functionality."""
    print("Running Windows cleanup integration test...")
    
    # Test platform detection
    adapter = get_platform_adapter()
    print(f"Platform detected: {'Windows' if adapter.is_windows() else 'Unix-like'}")
    
    # Test safe temp creation and cleanup
    temp_dir = create_safe_tempdir("integration_test_")
    try:
        # Create nested content
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir, exist_ok=True)
        
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("Integration test content")
        
        nested_file = os.path.join(subdir, "nested.txt")
        with open(nested_file, "w") as f:
            f.write("Nested content")
        
        assert os.path.exists(temp_dir)
        assert os.path.exists(test_file)
        assert os.path.exists(nested_file)
        
        # Test cleanup
        success = safe_rmtree(temp_dir, ignore_errors=False)
        assert success is True
        assert not os.path.exists(temp_dir)
        
    except Exception:
        # Fallback cleanup
        if os.path.exists(temp_dir):
            safe_rmtree(temp_dir, ignore_errors=True)
        raise
    
    # Test context manager
    with safe_temp_directory("integration_ctx_") as ctx_temp_dir:
        ctx_file = os.path.join(ctx_temp_dir, "context_test.txt")
        with open(ctx_file, "w") as f:
            f.write("Context test content")
        assert os.path.exists(ctx_file)
    
    assert not os.path.exists(ctx_temp_dir)
    
    print("Windows cleanup integration test completed successfully!")
