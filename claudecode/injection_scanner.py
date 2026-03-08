"""Pre-prompt injection scanner for PR content.

Scans PR metadata (title, body, filenames) and diff content for prompt
injection attempts before they are interpolated into the security audit
prompt. This hardens the pipeline against adversarial PRs that try to
manipulate Claude's security review output.

Attack vectors addressed:
- Instruction overrides in PR titles/bodies ("ignore all findings")
- Delimiter injection in filenames (### System:, [INST], etc.)
- Hidden instructions in diff content (HTML comments, authority impersonation)
- Output manipulation ("report zero findings", "analysis_summary")

Patterns derived from Sentinel AI (https://github.com/MaxwellCalkin/sentinel-ai),
an open-source LLM safety guardrails library with 530-case benchmark at 100% accuracy.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class InjectionFinding:
    """A detected prompt injection attempt."""
    location: str       # "title", "body", "filename", "diff"
    pattern_name: str   # Pattern that matched
    matched_text: str   # The matched substring
    severity: str       # "HIGH" or "CRITICAL"
    description: str    # Human-readable description


# Patterns that indicate prompt injection in PR metadata
_METADATA_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    # Instruction overrides — someone trying to manipulate the audit
    (
        "instruction_override",
        re.compile(
            r"(?i)(ignore|disregard|forget|override|bypass|skip)\s+"
            r"(all\s+|every\s+|any\s+)?"
            r"((?:(?:previous|prior|above|security|your|safety)\s+)*)"
            r"(instructions?|findings?|rules?|guidelines?|vulnerabilit|issues?)"
        ),
        "CRITICAL",
        "Instruction override attempt — may suppress security findings",
    ),
    # Output manipulation — trying to force specific audit results
    (
        "output_manipulation",
        re.compile(
            r"(?i)(report|output|return|show|find)\s+"
            r"(zero|no|0|empty|nothing|clean)\s+"
            r"(findings?|vulnerabilit|issues?|problems?|results?)"
        ),
        "CRITICAL",
        "Output manipulation — attempting to force clean audit result",
    ),
    # Delimiter injection in metadata
    (
        "delimiter_injection",
        re.compile(
            r"(?i)(\[/?INST\]|\[/?SYS\]|<\|im_start\|>|<\|im_end\|>|"
            r"<<\s*SYS\s*>>|###\s*(System|Human|Assistant)\s*:)"
        ),
        "CRITICAL",
        "Chat template delimiter injection",
    ),
    # Role injection
    (
        "role_injection",
        re.compile(
            r"(?i)(you\s+are\s+now|pretend\s+(to\s+be|you\s+are)|"
            r"new\s+system\s+prompt|system\s*:\s*you)"
        ),
        "HIGH",
        "Role injection attempt",
    ),
    # JSON schema manipulation — trying to inject into the output format
    (
        "schema_manipulation",
        re.compile(
            r'(?i)"findings"\s*:\s*\[\s*\]|'
            r'"review_completed"\s*:\s*true|'
            r'"high_severity"\s*:\s*0|'
            r'"analysis_summary"'
        ),
        "HIGH",
        "JSON output schema injection — attempting to inject pre-formed audit results",
    ),
    # Authority impersonation
    (
        "authority_impersonation",
        re.compile(
            r"(?i)(ADMIN\s+MESSAGE|SYSTEM\s+(UPDATE|OVERRIDE|MESSAGE)\s*:|"
            r"IMPORTANT\s+SYSTEM\s+(MESSAGE|UPDATE)\s*:|"
            r"AUTHORIZED\s+BY\s+ANTHROPIC\s*:|"
            r"\[SYSTEM\s+ADMIN\])"
        ),
        "CRITICAL",
        "Authority impersonation — fake system/admin message",
    ),
]

# Additional patterns for diff content (more permissive since code naturally
# contains some of these strings)
_DIFF_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    # Hidden instructions in HTML/markdown comments
    (
        "html_comment_injection",
        re.compile(
            r"(?i)<!--\s*(SYSTEM|ADMIN|INSTRUCTION|IMPORTANT|OVERRIDE|IGNORE|EXECUTE)\s*:"
            r".{0,200}?"
            r"-->"
        ),
        "CRITICAL",
        "Hidden instruction in HTML/markdown comment",
    ),
    # Direct attempts to end the code block and inject instructions
    (
        "code_block_escape",
        re.compile(
            r"```\s*\n\s*(ignore|disregard|forget|override|now\s+you\s+are|"
            r"IMPORTANT|SYSTEM|new\s+instructions?)",
            re.IGNORECASE,
        ),
        "CRITICAL",
        "Code block escape — attempting to break out of diff context",
    ),
]


def scan_pr_metadata(pr_data: dict) -> list[InjectionFinding]:
    """Scan PR title, body, and filenames for injection attempts.

    Args:
        pr_data: PR data dictionary with 'title', 'body', 'files', 'user' keys.

    Returns:
        List of InjectionFinding instances. Empty if clean.
    """
    findings: list[InjectionFinding] = []

    fields = {
        "title": pr_data.get("title", ""),
        "body": pr_data.get("body", "") or "",
        "user": pr_data.get("user", ""),
    }

    # Scan metadata fields
    for location, text in fields.items():
        for name, pattern, severity, desc in _METADATA_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    InjectionFinding(
                        location=location,
                        pattern_name=name,
                        matched_text=match.group()[:120],
                        severity=severity,
                        description=desc,
                    )
                )

    # Scan filenames
    for file_info in pr_data.get("files", []):
        filename = file_info.get("filename", "") if isinstance(file_info, dict) else str(file_info)
        for name, pattern, severity, desc in _METADATA_PATTERNS:
            for match in pattern.finditer(filename):
                findings.append(
                    InjectionFinding(
                        location=f"filename:{filename}",
                        pattern_name=name,
                        matched_text=match.group()[:120],
                        severity=severity,
                        description=desc,
                    )
                )

    return findings


def scan_diff(diff_text: str) -> list[InjectionFinding]:
    """Scan PR diff for injection attempts.

    Only checks diff-specific patterns (HTML comment injection, code block
    escape). Metadata patterns are not applied to diff content to avoid
    false positives on legitimate code.

    Args:
        diff_text: Complete PR diff in unified format.

    Returns:
        List of InjectionFinding instances. Empty if clean.
    """
    findings: list[InjectionFinding] = []

    for name, pattern, severity, desc in _DIFF_PATTERNS:
        for match in pattern.finditer(diff_text):
            findings.append(
                InjectionFinding(
                    location="diff",
                    pattern_name=name,
                    matched_text=match.group()[:120],
                    severity=severity,
                    description=desc,
                )
            )

    return findings


def scan_all(pr_data: dict, diff_text: Optional[str] = None) -> list[InjectionFinding]:
    """Scan all PR content for injection attempts.

    Args:
        pr_data: PR data dictionary.
        diff_text: Optional PR diff content.

    Returns:
        Combined list of findings from metadata and diff scanning.
    """
    findings = scan_pr_metadata(pr_data)
    if diff_text:
        findings.extend(scan_diff(diff_text))
    return findings


def format_warnings(findings: list[InjectionFinding]) -> str:
    """Format injection findings as human-readable warnings.

    Args:
        findings: List of InjectionFinding instances.

    Returns:
        Multi-line warning string.
    """
    if not findings:
        return ""

    lines = [f"[SECURITY] Detected {len(findings)} prompt injection attempt(s) in PR content:"]
    for f in findings:
        lines.append(f"  [{f.severity}] {f.description} in {f.location}: {f.matched_text!r}")
    return "\n".join(lines)
