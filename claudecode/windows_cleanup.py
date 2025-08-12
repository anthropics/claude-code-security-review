#!/usr/bin/env python3
"""
Windows file system cleanup utilities with recursion protection.

Handles Windows-specific filesystem issues: long paths, locked files, 
permission problems, and recursive deletion with safeguards.
"""

import os
import sys
import time
import stat
import shutil
import tempfile
from typing import Optional, Callable, Any, List
from pathlib import Path
import logging

from .logger import get_logger

logger = get_logger(__name__)


class WindowsCleanupError(Exception):
    """Exception for Windows cleanup operation failures."""
    pass


class WindowsFileSystemCleaner:
    """
    Windows file system cleanup with multiple fallback strategies.
    
    Handles: long paths, locked files, permissions, recursive deletion safeguards.
    """
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 0.1, max_depth: int = 100):
        """
        Args:
            max_retries: Retry attempts for locked files
            retry_delay: Delay between retries (seconds)
            max_depth: Max directory depth (prevents infinite recursion)
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_depth = max_depth
        self._cleanup_stats = {
            'files_removed': 0,
            'dirs_removed': 0,
            'retries_used': 0,
            'errors_encountered': 0
        }
    
    def safe_rmtree(self, path: str, ignore_errors: bool = False) -> bool:
        """
        Safe directory removal with Windows-specific handling.
        
        Uses multiple fallback strategies for locked files, permissions, long paths.
        
        Args:
            path: Directory path to remove
            ignore_errors: If True, continue on errors instead of raising
            
        Returns:
            True if successfully removed, False otherwise
            
        Raises:
            WindowsCleanupError: If removal fails and ignore_errors is False
        """
        if not os.path.exists(path):
            return True
        
        logger.debug(f"Attempting to remove directory: {path}")
        
        try:
            # Strategy 1: Standard shutil.rmtree with custom error handler
            self._rmtree_with_retries(path)
            logger.debug(f"Successfully removed directory: {path}")
            return True
            
        except Exception as e:
            logger.warning(f"Standard rmtree failed for {path}: {e}")
            
            try:
                # Strategy 2: Force removal with attribute changes
                self._force_rmtree(path)
                logger.debug(f"Force removal successful for: {path}")
                return True
                
            except Exception as e2:
                logger.warning(f"Force removal failed for {path}: {e2}")
                
                try:
                    # Strategy 3: Manual recursive removal with depth protection
                    self._manual_rmtree(path, current_depth=0)
                    logger.debug(f"Manual removal successful for: {path}")
                    return True
                    
                except Exception as e3:
                    error_msg = f"All removal strategies failed for {path}: {e}, {e2}, {e3}"
                    logger.error(error_msg)
                    self._cleanup_stats['errors_encountered'] += 1
                    
                    if ignore_errors:
                        return False
                    else:
                        raise WindowsCleanupError(error_msg) from e3
    
    def _rmtree_with_retries(self, path: str) -> None:
        """Remove directory tree with retry logic for locked files."""
        def retry_on_error(func: Callable, path: str, exc_info: Any) -> None:
            """Error handler that retries operations for locked files."""
            exception = exc_info[1]
            
            # Common Windows errors that might be resolved by retrying
            retry_errors = (
                PermissionError,
                FileNotFoundError,
                OSError
            )
            
            if isinstance(exception, retry_errors):
                for attempt in range(self.max_retries):
                    try:
                        time.sleep(self.retry_delay)
                        
                        # Try to make file writable
                        if os.path.exists(path):
                            try:
                                os.chmod(path, stat.S_IWRITE)
                            except:
                                pass  # Ignore chmod errors
                        
                        # Retry the original operation
                        func(path)
                        self._cleanup_stats['retries_used'] += 1
                        logger.debug(f"Retry {attempt + 1} successful for: {path}")
                        return
                        
                    except Exception as retry_error:
                        if attempt == self.max_retries - 1:
                            logger.warning(f"Final retry failed for {path}: {retry_error}")
                            raise retry_error
                        continue
            else:
                # Non-retryable error, re-raise immediately
                raise exception
        
        shutil.rmtree(path, onerror=retry_on_error)
    
    def _force_rmtree(self, path: str) -> None:
        """Force removal by changing file attributes to writable first."""
        
        def force_remove_readonly(func: Callable, path: str, exc_info: Any) -> None:
            """Force remove read-only files by changing attributes."""
            try:
                # Make file/directory writable
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception as e:
                logger.debug(f"Force attribute change failed for {path}: {e}")
                raise
        
        # First pass: make everything writable
        for root, dirs, files in os.walk(path, topdown=False):
            # Process files
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.chmod(file_path, stat.S_IWRITE)
                    self._cleanup_stats['files_removed'] += 1
                except:
                    pass  # Continue on individual file errors
            
            # Process directories
            for dir in dirs:
                dir_path = os.path.join(root, dir)
                try:
                    os.chmod(dir_path, stat.S_IWRITE)
                    self._cleanup_stats['dirs_removed'] += 1
                except:
                    pass  # Continue on individual directory errors
        
        # Second pass: remove everything
        shutil.rmtree(path, onerror=force_remove_readonly)
    
    def _manual_rmtree(self, path: str, current_depth: int = 0) -> None:
        """Manual recursive removal with depth protection against infinite recursion."""
        if current_depth > self.max_depth:
            logger.warning(f"Maximum recursion depth {self.max_depth} exceeded at: {path}")
            raise WindowsCleanupError(f"Recursion depth limit exceeded: {path}")
        
        if not os.path.exists(path):
            return
        
        if os.path.isfile(path):
            # Handle file
            self._safe_remove_file(path)
            return
        
        # Handle directory
        try:
            entries = os.listdir(path)
        except (PermissionError, FileNotFoundError):
            # Directory might be locked or already removed
            return
        
        # Remove contents first
        for entry in entries:
            entry_path = os.path.join(path, entry)
            
            if os.path.isdir(entry_path):
                # Recursive directory removal with depth tracking
                self._manual_rmtree(entry_path, current_depth + 1)
                self._cleanup_stats['dirs_removed'] += 1
            else:
                # File removal
                self._safe_remove_file(entry_path)
                self._cleanup_stats['files_removed'] += 1
        
        # Remove empty directory
        self._safe_remove_dir(path)
    
    def _safe_remove_file(self, file_path: str) -> None:
        """Safely remove a file with retries."""
        for attempt in range(self.max_retries):
            try:
                # Make writable first
                os.chmod(file_path, stat.S_IWRITE)
                os.remove(file_path)
                return
                
            except (PermissionError, FileNotFoundError) as e:
                if attempt == self.max_retries - 1:
                    logger.warning(f"Failed to remove file {file_path}: {e}")
                    raise
                time.sleep(self.retry_delay)
    
    def _safe_remove_dir(self, dir_path: str) -> None:
        """Safely remove an empty directory with retries."""
        for attempt in range(self.max_retries):
            try:
                os.rmdir(dir_path)
                return
                
            except (PermissionError, OSError) as e:
                if attempt == self.max_retries - 1:
                    logger.warning(f"Failed to remove directory {dir_path}: {e}")
                    raise
                time.sleep(self.retry_delay)
    
    def get_cleanup_stats(self) -> dict:
        """Get cleanup operation statistics."""
        return dict(self._cleanup_stats)
    
    def reset_stats(self) -> None:
        """Reset cleanup statistics."""
        for key in self._cleanup_stats:
            self._cleanup_stats[key] = 0


def safe_windows_rmtree(path: str, ignore_errors: bool = True) -> bool:
    """
    Windows-safe directory removal with multiple fallback strategies.
    
    Args:
        path: Directory path to remove
        ignore_errors: If True, suppress errors and return False on failure
        
    Returns:
        True if removal succeeded, False if failed and ignore_errors=True
        
    Raises:
        WindowsCleanupError: If removal fails and ignore_errors=False
    """
    cleaner = WindowsFileSystemCleaner()
    return cleaner.safe_rmtree(path, ignore_errors=ignore_errors)


def create_safe_tempdir(prefix: str = "claude_temp_") -> str:
    """
    Create temporary directory with Windows-safe paths and cleanup.
    
    Args:
        prefix: Prefix for directory name (truncated on Windows)
        
    Returns:
        Path to the created temporary directory
    """
    # Use shorter paths on Windows to avoid long path issues
    if sys.platform.startswith('win'):
        # Try to use a shorter temp directory
        temp_base = os.environ.get('TEMP', tempfile.gettempdir())
        # Limit prefix length to avoid long paths
        if len(prefix) > 20:
            prefix = prefix[:20]
    
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    logger.debug(f"Created temporary directory: {temp_dir}")
    return temp_dir
