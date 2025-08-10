#!/usr/bin/env python3
"""
Safe temporary directory management with platform-aware cleanup.

Drop-in replacement for tempfile.TemporaryDirectory with Windows compatibility.
"""

import os
import tempfile
from contextlib import contextmanager
from typing import Generator, Optional

from .platform_utils import get_platform_adapter
from .logger import get_logger

logger = get_logger(__name__)


@contextmanager
def safe_temp_directory(prefix: str = "claude_temp_", 
                       auto_cleanup: bool = True) -> Generator[str, None, None]:
    """
    Context manager for safe temporary directory with platform-aware cleanup.
    
    Drop-in replacement for tempfile.TemporaryDirectory that handles Windows
    filesystem issues like locked files and recursion errors.
    
    Args:
        prefix: Prefix for temporary directory name
        auto_cleanup: If True, automatically cleanup on exit
        
    Yields:
        Path to the temporary directory
    """
    platform_adapter = get_platform_adapter()
    temp_dir = None
    
    try:
        # Create temporary directory using platform adapter
        temp_dir = platform_adapter.create_safe_tempdir(prefix=prefix)
        logger.debug(f"Created safe temporary directory: {temp_dir}")
        yield temp_dir
        
    except Exception as e:
        logger.error(f"Error in safe temporary directory context: {e}")
        raise
        
    finally:
        # Cleanup if requested and directory was created
        if auto_cleanup and temp_dir and os.path.exists(temp_dir):
            try:
                success = platform_adapter.safe_rmtree(temp_dir, ignore_errors=True)
                if success:
                    logger.debug(f"Successfully cleaned up temporary directory: {temp_dir}")
                else:
                    logger.warning(f"Failed to clean up temporary directory: {temp_dir}")
            except Exception as cleanup_error:
                logger.error(f"Error during temporary directory cleanup: {cleanup_error}")


class SafeTemporaryDirectory:
    """
    Drop-in replacement for tempfile.TemporaryDirectory with Windows-safe cleanup.
    
    Compatible interface with tempfile.TemporaryDirectory but uses platform-aware
    cleanup to prevent Windows filesystem issues.
    """
    
    def __init__(self, suffix=None, prefix=None, dir=None, ignore_cleanup_errors=True):
        """
        Initialize temporary directory manager.
        
        Args:
            suffix: Directory name suffix
            prefix: Directory name prefix  
            dir: Parent directory (None = system temp)
            ignore_cleanup_errors: Whether to suppress cleanup errors
        """
        # Build prefix similar to tempfile.TemporaryDirectory
        if prefix is None:
            prefix = "tmp"
        if suffix is not None:
            prefix = prefix + suffix
            
        self.prefix = prefix
        self.dir = dir
        self.ignore_cleanup_errors = ignore_cleanup_errors
        self.name: Optional[str] = None
        self.platform_adapter = get_platform_adapter()
    
    def __enter__(self) -> str:
        """Context manager entry - create the directory."""
        if self.name is not None:
            raise RuntimeError("Temporary directory already created")
        
        # Use platform adapter for safe creation
        self.name = self.platform_adapter.create_safe_tempdir(prefix=self.prefix)
        logger.debug(f"Created safe temporary directory: {self.name}")
        return self.name
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - clean up the directory."""
        self.cleanup()
    
    def cleanup(self) -> None:
        """
        Clean up the temporary directory.
        
        This method can be called multiple times safely.
        """
        if self.name is None:
            return  # Already cleaned up or never created
        
        try:
            success = self.platform_adapter.safe_rmtree(self.name, ignore_errors=self.ignore_cleanup_errors)
            if success:
                logger.debug(f"Successfully cleaned up temporary directory: {self.name}")
            elif not self.ignore_cleanup_errors:
                raise OSError(f"Failed to clean up temporary directory: {self.name}")
            else:
                logger.warning(f"Failed to clean up temporary directory: {self.name}")
                
        except Exception as e:
            if not self.ignore_cleanup_errors:
                raise
            logger.error(f"Error during temporary directory cleanup: {e}")
        finally:
            self.name = None
    
    def __del__(self):
        """Destructor cleanup."""
        if self.name is not None:
            self.cleanup()


class SafeTempDir:
    """
    Class-based interface for safe temporary directory management.
    
    This provides an object-oriented interface for cases where
    context managers are not suitable.
    """
    
    def __init__(self, prefix: str = "claude_temp_"):
        """
        Initialize safe temporary directory manager.
        
        Args:
            prefix: Prefix for temporary directory name
        """
        self.prefix = prefix
        self.temp_dir: Optional[str] = None
        self.platform_adapter = get_platform_adapter()
    
    def create(self) -> str:
        """
        Create the temporary directory.
        
        Returns:
            Path to the created temporary directory
        """
        if self.temp_dir is not None:
            raise RuntimeError("Temporary directory already created")
        
        self.temp_dir = self.platform_adapter.create_safe_tempdir(self.prefix)
        logger.debug(f"Created safe temporary directory: {self.temp_dir}")
        return self.temp_dir
    
    def cleanup(self) -> bool:
        """
        Clean up the temporary directory.
        
        Returns:
            True if cleanup succeeded, False otherwise
        """
        if self.temp_dir is None:
            return True  # Nothing to clean up
        
        try:
            success = self.platform_adapter.safe_rmtree(self.temp_dir, ignore_errors=True)
            if success:
                logger.debug(f"Successfully cleaned up temporary directory: {self.temp_dir}")
            else:
                logger.warning(f"Failed to clean up temporary directory: {self.temp_dir}")
            
            self.temp_dir = None
            return success
            
        except Exception as e:
            logger.error(f"Error during temporary directory cleanup: {e}")
            return False
    
    def __enter__(self) -> str:
        """Context manager entry."""
        return self.create()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit with cleanup."""
        self.cleanup()
    
    def __del__(self):
        """Destructor cleanup."""
        if self.temp_dir is not None:
            self.cleanup()


# Convenience functions for backward compatibility
def create_temp_directory(prefix: str = "claude_temp_") -> str:
    """
    Create a temporary directory with platform-specific handling.
    
    Args:
        prefix: Prefix for temporary directory name
        
    Returns:
        Path to the created temporary directory
        
    Note:
        Caller is responsible for cleanup using safe_cleanup_directory()
    """
    platform_adapter = get_platform_adapter()
    return platform_adapter.create_safe_tempdir(prefix=prefix)


def safe_cleanup_directory(path: str, ignore_errors: bool = True) -> bool:
    """
    Safely clean up a directory with platform-specific handling.
    
    Args:
        path: Directory path to remove
        ignore_errors: If True, suppress errors and return False on failure
        
    Returns:
        True if cleanup succeeded, False otherwise
    """
    platform_adapter = get_platform_adapter()
    return platform_adapter.safe_rmtree(path, ignore_errors=ignore_errors)
