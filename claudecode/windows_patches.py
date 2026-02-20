#!/usr/bin/env python3
"""
Windows compatibility patches for tempfile operations.

Monkey-patching to fix Windows filesystem issues,
specifically recursion problems with shutil.rmtree in temporary directories.
"""

import os
import tempfile
import platform
from typing import Optional, Any
from contextlib import contextmanager

from .logger import get_logger
from .safe_temp import SafeTemporaryDirectory

logger = get_logger(__name__)


class WindowsPatches:
    """
    Manager for Windows-specific monkey patches.
    
    Handles  patching to fix Windows filesystem issues
    without modifying existing code.
    """
    
    def __init__(self):
        """Initialize the patch manager."""
        self._is_windows = platform.system().lower() == "windows"
        self._original_temp_directory: Optional[Any] = None
        self._patches_applied = False
        
    def apply_patches(self) -> bool:
        """
        Apply Windows-specific patches to fix filesystem issues.
        
        Returns:
            True if patches were applied, False if not needed or already applied
        """
        if not self._is_windows:
            logger.debug("Not on Windows, skipping patches")
            return False
            
        if self._patches_applied:
            logger.debug("Patches already applied")
            return False
        
        try:
            # Patch tempfile.TemporaryDirectory with our safe version
            self._original_temp_directory = tempfile.TemporaryDirectory
            tempfile.TemporaryDirectory = SafeTemporaryDirectory
            
            self._patches_applied = True
            logger.info("Applied Windows compatibility patches for tempfile operations")
            return True
            
        except Exception as e:
            logger.error(f"Failed to apply Windows patches: {e}")
            return False
    
    def remove_patches(self) -> bool:
        """
        Remove Windows patches and restore original behavior.
        
        Returns:
            True if patches were removed, False if not applied
        """
        if not self._patches_applied:
            return False
        
        try:
            # Restore original tempfile.TemporaryDirectory
            if self._original_temp_directory is not None:
                tempfile.TemporaryDirectory = self._original_temp_directory
                self._original_temp_directory = None
            
            self._patches_applied = False
            logger.info("Removed Windows compatibility patches")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove Windows patches: {e}")
            return False
    
    def is_patched(self) -> bool:
        """Check if patches are currently applied."""
        return self._patches_applied
    
    @contextmanager
    def patch_context(self):
        """Context manager for temporary patch application."""
        applied = self.apply_patches()
        try:
            yield self
        finally:
            if applied:
                self.remove_patches()


# Global patch manager instance
_patch_manager = WindowsPatches()


def apply_windows_patches() -> bool:
    """Apply Windows compatibility patches globally."""
    return _patch_manager.apply_patches()


def remove_windows_patches() -> bool:
    """Remove Windows compatibility patches."""
    return _patch_manager.remove_patches()


def is_windows_patched() -> bool:
    """Check if Windows patches are currently active."""
    return _patch_manager.is_patched()


@contextmanager
def windows_patch_context():
    """Context manager for temporary Windows patch application."""
    with _patch_manager.patch_context():
        yield


def auto_patch_if_needed() -> bool:
    """Automatically apply Windows patches if running on Windows."""
    if platform.system().lower() == "windows":
        if not _patch_manager.is_patched():
            return _patch_manager.apply_patches()
        return True
    return False


# Auto-apply patches when module is imported on Windows
# This ensures maximum compatibility without code changes
if platform.system().lower() == "windows":
    try:
        auto_patch_if_needed()
        logger.debug("Windows patches auto-applied on module import")
    except Exception as e:
        logger.warning(f"Failed to auto-apply Windows patches: {e}")
