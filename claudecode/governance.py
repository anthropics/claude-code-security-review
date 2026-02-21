# Governance policy integration for security reviews.
#
# Loads organizational governance policies from .github/governance-policy.yaml
# and applies custom rules, severity overrides, and agent governance checks.

import re
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from claudecode.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GovernancePolicy:
    # Parsed governance policy configuration.

    name: str = ""
    severity_overrides: List[Dict[str, str]] = field(default_factory=list)
    custom_rules: List[Dict[str, Any]] = field(default_factory=list)
    agent_governance: Dict[str, bool] = field(default_factory=dict)


def load_governance_policy(policy_path: Path) -> Optional[GovernancePolicy]:
    # Load governance policy from a YAML file.
    # Returns GovernancePolicy if file exists and is valid, None otherwise.

    if not policy_path.exists():
        return None

    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(
            f"[Warning] Failed to parse governance policy YAML: {e}", file=sys.stderr
        )
        return None
    except Exception as e:
        print(f"[Warning] Failed to read governance policy file: {e}", file=sys.stderr)
        return None

    if not isinstance(raw, dict):
        print("[Warning] Governance policy file is not a YAML mapping", file=sys.stderr)
        return None

    gov = raw.get("governance", raw)
    if not isinstance(gov, dict):
        print(
            "[Warning] Governance policy 'governance' key is not a mapping",
            file=sys.stderr,
        )
        return None

    policy = GovernancePolicy(
        name=gov.get("name", ""),
        severity_overrides=gov.get("severity_overrides", []) or [],
        custom_rules=gov.get("custom_rules", []) or [],
        agent_governance=gov.get("agent_governance", {}) or {},
    )

    # Validate severity_overrides entries
    valid_overrides = []
    for override in policy.severity_overrides:
        if not isinstance(override, dict) or "pattern" not in override:
            continue
        if "severity" not in override:
            continue
        valid_overrides.append(override)
    policy.severity_overrides = valid_overrides

    # Validate custom_rules entries
    valid_rules = []
    for rule in policy.custom_rules:
        if not isinstance(rule, dict) or "pattern" not in rule:
            continue
        if "severity" not in rule:
            continue
        valid_rules.append(rule)
    policy.custom_rules = valid_rules

    logger.info(
        f"Loaded governance policy '{policy.name}' with "
        f"{len(policy.severity_overrides)} severity overrides and "
        f"{len(policy.custom_rules)} custom rules"
    )

    return policy


def apply_severity_overrides(
    findings: List[Dict[str, Any]], policy: GovernancePolicy
) -> List[Dict[str, Any]]:
    # Apply governance severity overrides to findings.
    # For each finding, check if any severity override rule matches.
    # If so, update the finding's severity and mark it as governance-overridden.

    if not policy.severity_overrides:
        return findings

    result = []
    for finding in findings:
        updated = finding.copy()
        description = finding.get("description", "") or ""
        file_path = finding.get("file", "") or ""
        combined = f"{description} {file_path}"

        for override in policy.severity_overrides:
            pattern = override.get("pattern", "")
            context = override.get("context", "")
            new_severity = override.get("severity", "").upper()

            try:
                if not re.search(pattern, combined, re.IGNORECASE):
                    continue
            except re.error:
                continue

            # If context is specified, check that it also matches
            if context and not re.search(context, combined, re.IGNORECASE):
                continue

            # Apply override
            original = updated.get("severity", "MEDIUM")
            updated["original_severity"] = original
            updated["severity"] = new_severity
            updated["governance_override"] = True
            break  # First matching rule wins

        result.append(updated)

    return result


def apply_custom_rules(
    diff_text: str, policy: GovernancePolicy
) -> List[Dict[str, Any]]:
    # Run custom governance rules against the PR diff.
    # Splits the diff into per-file sections, checks path globs,
    # and runs regex patterns against added lines.

    if not policy.custom_rules or not diff_text:
        return []

    # Split diff into per-file sections
    file_sections = re.split(r"(?=^diff --git)", diff_text, flags=re.MULTILINE)

    findings = []

    for section in file_sections:
        if not section.strip():
            continue

        # Extract filename from diff header
        match = re.match(r"^diff --git a/(.*?) b/", section)
        if not match:
            continue
        filename = match.group(1)

        # Extract added lines with their line numbers
        added_lines = _extract_added_lines(section)

        for rule in policy.custom_rules:
            # Check path filter
            paths = rule.get("paths", [])
            if paths and not _matches_any_path(filename, paths):
                continue

            pattern = rule.get("pattern", "")
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue

            # Check added lines for pattern matches
            for line_num, line_content in added_lines:
                if compiled.search(line_content):
                    findings.append(
                        {
                            "file": filename,
                            "line": line_num,
                            "severity": rule.get("severity", "MEDIUM").upper(),
                            "category": "governance_policy",
                            "description": rule.get(
                                "message", f"Governance rule '{rule.get('name', 'unnamed')}' violated"
                            ),
                            "recommendation": rule.get(
                                "message", "Review this code against organizational governance policy"
                            ),
                            "confidence": 1.0,
                            "governance_rule": rule.get("name", "unnamed"),
                        }
                    )
                    break  # One finding per rule per file

    return findings


def _extract_added_lines(diff_section: str) -> List[tuple]:
    # Extract added lines with approximate line numbers from a diff section.
    # Returns list of (line_number, line_content) tuples for added lines.

    added = []
    current_line = 0

    for line in diff_section.split("\n"):
        # Parse hunk header for line numbers
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if line.startswith("+") and not line.startswith("+++"):
            added.append((current_line, line[1:]))  # Strip leading +
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass  # Deleted lines don't increment the new file line counter
        elif not line.startswith("\\"):
            current_line += 1

    return added


def _matches_any_path(filename: str, patterns: List[str]) -> bool:
    # Check if a filename matches any of the given glob patterns.

    for pattern in patterns:
        if fnmatch(filename, pattern):
            return True
        # Also check with ** expansion for directory wildcards
        if "**" in pattern:
            # Convert ** glob to work with fnmatch
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix = parts[0]
                suffix = parts[1].lstrip("/")
                if filename.startswith(prefix) and (
                    not suffix or fnmatch(filename[len(prefix) :], f"*{suffix}")
                ):
                    return True
    return False


def format_governance_prompt_section(policy: GovernancePolicy) -> str:
    # Format governance policy into a prompt section for the security audit.

    sections = []
    sections.append("ORGANIZATIONAL GOVERNANCE POLICY:")
    if policy.name:
        sections.append(f"Policy: {policy.name}")
    sections.append("")

    if policy.severity_overrides:
        sections.append("**Severity Overrides (apply these when scoring findings):**")
        for override in policy.severity_overrides:
            pattern = override.get("pattern", "")
            context = override.get("context", "")
            severity = override.get("severity", "").upper()
            ctx_str = f" (in context: {context})" if context else ""
            sections.append(f"- Pattern `{pattern}`{ctx_str} -> severity: {severity}")
        sections.append("")

    if policy.custom_rules:
        sections.append(
            "**Custom Governance Rules (flag violations of these rules):**"
        )
        for rule in policy.custom_rules:
            name = rule.get("name", "unnamed")
            message = rule.get("message", "")
            paths = rule.get("paths", [])
            severity = rule.get("severity", "MEDIUM").upper()
            path_str = f" in {', '.join(paths)}" if paths else ""
            sections.append(f"- [{severity}] {name}{path_str}: {message}")
        sections.append("")

    if policy.agent_governance:
        sections.append("**Agent Governance Requirements:**")
        if policy.agent_governance.get("require_tool_allowlist"):
            sections.append(
                "- Flag any agent code that does not use a tool allowlist"
            )
        if policy.agent_governance.get("flag_unrestricted_agents"):
            sections.append(
                "- Flag agents with unrestricted tool/command access"
            )
        if policy.agent_governance.get("require_audit_trail"):
            sections.append(
                "- Flag agent operations that lack audit trail logging"
            )
        sections.append("")

    return "\n".join(sections)
