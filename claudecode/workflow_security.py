"""Deterministic checks for GitHub Actions workflow security."""

import re
from typing import Any, Dict, List, Optional


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_USES_RE = re.compile(r"^\+\s*(?:-\s*)?uses:\s*[\"']?([^\"'\s#]+)")
_FULL_SHA_RE = re.compile(r"^[a-fA-F0-9]{40}$")


def find_unpinned_github_actions(diff_text: str) -> List[Dict[str, Any]]:
    """Find newly added workflow actions that are not pinned to a full SHA.

    The check only inspects added lines in GitHub Actions workflow files. Local
    actions and Docker actions are ignored because they do not use repository
    refs.
    """

    findings: List[Dict[str, Any]] = []
    current_file: Optional[str] = None
    current_line: Optional[int] = None

    for raw_line in diff_text.splitlines():
        header_match = _DIFF_HEADER_RE.match(raw_line)
        if header_match:
            current_file = header_match.group(2)
            current_line = None
            continue

        hunk_match = _HUNK_HEADER_RE.match(raw_line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if current_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            if _is_workflow_file(current_file):
                finding = _finding_for_added_uses_line(
                    raw_line, current_file, current_line
                )
                if finding:
                    findings.append(finding)
            current_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            current_line += 1

    return findings


def _is_workflow_file(path: Optional[str]) -> bool:
    if not path:
        return False
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith(".github/workflows/") and normalized.endswith(
        (".yml", ".yaml")
    )


def _finding_for_added_uses_line(
    line: str, file_path: str, line_number: int
) -> Optional[Dict[str, Any]]:
    match = _USES_RE.match(line)
    if not match:
        return None

    action_ref = match.group(1).rstrip(",")
    if action_ref.startswith(("./", "docker://")):
        return None

    if "@" not in action_ref:
        return None

    action_name, ref = action_ref.rsplit("@", 1)
    if _FULL_SHA_RE.fullmatch(ref):
        return None

    return {
        "file": file_path,
        "line": line_number,
        "severity": "MEDIUM",
        "category": "unpinned_github_action",
        "description": (
            f"GitHub Actions workflow uses {action_name}@{ref}, which is a "
            "mutable ref instead of a full commit SHA."
        ),
        "exploit_scenario": (
            "If the referenced action tag or branch is moved or the action "
            "repository is compromised, this workflow can execute unexpected "
            "code in CI with the workflow's permissions and secrets."
        ),
        "recommendation": (
            f"Pin {action_name} to a full 40-character commit SHA and update it "
            "through a reviewed dependency update process."
        ),
        "confidence": 0.9,
    }
