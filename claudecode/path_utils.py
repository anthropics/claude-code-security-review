"""Path helpers for caller-provided instruction files."""

from pathlib import Path


def resolve_instruction_path(file_path: str, repo_path: str = "") -> Path:
    """Resolve relative instruction paths from the caller's repository root."""
    path = Path(file_path)
    if not file_path or path.is_absolute() or not repo_path:
        return path
    return Path(repo_path) / path
