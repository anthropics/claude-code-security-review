"""Findings filter for reducing false positives in security audit results."""

import re
from typing import Dict, Any, List, Tuple, Optional, Pattern
import time
from dataclasses import dataclass, field

from copilot_review.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FilterStats:
    """Statistics about the filtering process."""
    total_findings: int = 0
    hard_excluded: int = 0
    llm_excluded: int = 0
    kept_findings: int = 0
    exclusion_breakdown: Dict[str, int] = field(default_factory=dict)
    confidence_scores: List[float] = field(default_factory=list)
    runtime_seconds: float = 0.0


class HardExclusionRules:
    """Hard exclusion rules for common false positives."""

    # Pre-compiled regex patterns for better performance
    _DOS_PATTERNS: List[Pattern] = [
        re.compile(r'\b(denial of service|dos attack|resource exhaustion)\b', re.IGNORECASE),
        re.compile(r'\b(exhaust|overwhelm|overload).*?(resource|memory|cpu)\b', re.IGNORECASE),
        re.compile(r'\b(infinite|unbounded).*?(loop|recursion)\b', re.IGNORECASE),
    ]


    _RATE_LIMITING_PATTERNS: List[Pattern] = [
        re.compile(r'\b(missing|lack of|no)\s+rate\s+limit', re.IGNORECASE),
        re.compile(r'\brate\s+limiting\s+(missing|required|not implemented)', re.IGNORECASE),
        re.compile(r'\b(implement|add)\s+rate\s+limit', re.IGNORECASE),
        re.compile(r'\bunlimited\s+(requests|calls|api)', re.IGNORECASE),
    ]

    _RESOURCE_PATTERNS: List[Pattern] = [
        re.compile(r'\b(resource|memory|file)\s+leak\s+potential', re.IGNORECASE),
        re.compile(r'\bunclosed\s+(resource|file|connection)', re.IGNORECASE),
        re.compile(r'\b(close|cleanup|release)\s+(resource|file|connection)', re.IGNORECASE),
        re.compile(r'\bpotential\s+memory\s+leak', re.IGNORECASE),
        re.compile(r'\b(database|thread|socket|connection)\s+leak', re.IGNORECASE),
    ]

    _OPEN_REDIRECT_PATTERNS: List[Pattern] = [
        re.compile(r'\b(open redirect|unvalidated redirect)\b', re.IGNORECASE),
        re.compile(r'\b(redirect.(attack|exploit|vulnerability))\b', re.IGNORECASE),
        re.compile(r'\b(malicious.redirect)\b', re.IGNORECASE),
    ]

    _MEMORY_SAFETY_PATTERNS: List[Pattern] = [
        re.compile(r'\b(buffer overflow|stack overflow|heap overflow)\b', re.IGNORECASE),
        re.compile(r'\b(oob)\s+(read|write|access)\b', re.IGNORECASE),
        re.compile(r'\b(out.?of.?bounds?)\b', re.IGNORECASE),
        re.compile(r'\b(memory safety|memory corruption)\b', re.IGNORECASE),
        re.compile(r'\b(use.?after.?free|double.?free|null.?pointer.?dereference)\b', re.IGNORECASE),
        re.compile(r'\b(segmentation fault|segfault|memory violation)\b', re.IGNORECASE),
        re.compile(r'\b(bounds check|boundary check|array bounds)\b', re.IGNORECASE),
        re.compile(r'\b(integer overflow|integer underflow|integer conversion)\b', re.IGNORECASE),
        re.compile(r'\barbitrary.?(memory read|pointer dereference|memory address|memory pointer)\b', re.IGNORECASE),
    ]

    # Memory safety findings are only meaningful in native code. The original rule knew only
    # .c/.cc/.cpp/.h, which would silently drop findings in .hpp/.cxx/.hh/.hxx files.
    _NATIVE_EXTENSIONS = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx'}

    # Safe Rust cannot have memory safety bugs, but `unsafe` blocks and FFI can.
    _RUST_UNSAFE_HINT: Pattern = re.compile(r'\b(unsafe|ffi|raw pointer|extern\s+"c")\b', re.IGNORECASE)

    _REGEX_INJECTION: List[Pattern] = [
        re.compile(r'\b(regex|regular expression)\s+injection\b', re.IGNORECASE),
        re.compile(r'\b(regex|regular expression)\s+denial of service\b', re.IGNORECASE),
        re.compile(r'\b(regex|regular expression)\s+flooding\b', re.IGNORECASE),
    ]

    _SSRF_PATTERNS: List[Pattern] = [
        re.compile(r'\b(ssrf|server\s+.?side\s+.?request\s+.?forgery)\b', re.IGNORECASE),
    ]

    @classmethod
    def get_exclusion_reason(cls, finding: Dict[str, Any]) -> Optional[str]:
        """Check if a finding should be excluded based on hard rules.

        Args:
            finding: Security finding to check

        Returns:
            Exclusion reason if finding should be excluded, None otherwise
        """
        # Check if finding is in a Markdown file
        file_path = finding.get('file', '')
        if file_path.lower().endswith('.md'):
            return "Finding in Markdown documentation file"

        description = finding.get('description', '')
        title = finding.get('title', '')

        # Handle None values
        if description is None:
            description = ''
        if title is None:
            title = ''

        combined_text = f"{title} {description}".lower()

        # Check DOS patterns
        for pattern in cls._DOS_PATTERNS:
            if pattern.search(combined_text):
                return "Generic DOS/resource exhaustion finding (low signal)"


        # Check rate limiting patterns
        for pattern in cls._RATE_LIMITING_PATTERNS:
            if pattern.search(combined_text):
                return "Generic rate limiting recommendation"

        # Check resource patterns - always exclude
        for pattern in cls._RESOURCE_PATTERNS:
            if pattern.search(combined_text):
                return "Resource management finding (not a security vulnerability)"

        # Check open redirect patterns
        for pattern in cls._OPEN_REDIRECT_PATTERNS:
            if pattern.search(combined_text):
                return "Open redirect vulnerability (not high impact)"

        # Check regex injection patterns
        for pattern in cls._REGEX_INJECTION:
            if pattern.search(combined_text):
                return "Regex injection finding (not applicable)"

        # Check memory safety patterns - exclude if NOT in native code
        file_ext = ''
        if '.' in file_path:
            file_ext = f".{file_path.lower().split('.')[-1]}"

        # If file doesn't have a C/C++ extension (including no extension), exclude memory safety findings,
        # except Rust findings that explicitly concern unsafe code or FFI.
        if file_ext not in cls._NATIVE_EXTENSIONS:
            rust_unsafe = file_ext == '.rs' and cls._RUST_UNSAFE_HINT.search(combined_text)
            if not rust_unsafe:
                for pattern in cls._MEMORY_SAFETY_PATTERNS:
                    if pattern.search(combined_text):
                        return "Memory safety finding in non-C/C++ code (not applicable)"

        # Check SSRF patterns - exclude if in HTML files only
        html_extensions = {'.html'}

        # If file has HTML extension, exclude SSRF findings
        if file_ext in html_extensions:
            for pattern in cls._SSRF_PATTERNS:
                if pattern.search(combined_text):
                    return "SSRF finding in HTML file (not applicable to client-side code)"

        return None


class FindingsFilter:
    """Main filter class for security findings."""

    def __init__(self,
                 use_hard_exclusions: bool = True,
                 use_llm_filtering: bool = True,
                 llm_client: Optional[Any] = None,
                 custom_filtering_instructions: Optional[str] = None):
        """Initialize findings filter.

        Args:
            use_hard_exclusions: Whether to apply hard exclusion rules
            use_llm_filtering: Whether to use the LLM (Copilot CLI) for filtering
            llm_client: Client with an ``analyze_findings`` method (see CopilotFilterClient)
            custom_filtering_instructions: Optional custom filtering instructions
        """
        self.use_hard_exclusions = use_hard_exclusions
        self.custom_filtering_instructions = custom_filtering_instructions
        self.llm_client = llm_client
        # LLM filtering needs a client; without one only the hard rules are applied
        self.use_llm_filtering = bool(use_llm_filtering and llm_client is not None)

    def filter_findings(self,
                       findings: List[Dict[str, Any]],
                       pr_context: Optional[Dict[str, Any]] = None) -> Tuple[bool, Dict[str, Any], FilterStats]:
        """Filter security findings to remove false positives.

        Args:
            findings: List of security findings from the audit
            pr_context: Optional MR context for better analysis

        Returns:
            Tuple of (success, filtered_results, stats)
        """
        start_time = time.time()

        if not findings:
            stats = FilterStats(total_findings=0, runtime_seconds=0.0)
            return True, {
                "filtered_findings": [],
                "excluded_findings": [],
                "analysis_summary": {
                    "total_findings": 0,
                    "kept_findings": 0,
                    "excluded_findings": 0,
                    "exclusion_breakdown": {}
                }
            }, stats

        logger.info(f"Filtering {len(findings)} security findings")

        # Initialize statistics
        stats = FilterStats(total_findings=len(findings))

        # Step 1: Apply hard exclusion rules
        findings_after_hard = []
        excluded_hard = []

        if self.use_hard_exclusions:
            for i, finding in enumerate(findings):
                exclusion_reason = HardExclusionRules.get_exclusion_reason(finding)
                if exclusion_reason:
                    excluded_hard.append({
                        "finding": finding,
                        "index": i,
                        "exclusion_reason": exclusion_reason,
                        "filter_stage": "hard_rules"
                    })
                    stats.hard_excluded += 1

                    # Track exclusion breakdown
                    key = exclusion_reason.split('(')[0].strip()
                    stats.exclusion_breakdown[key] = stats.exclusion_breakdown.get(key, 0) + 1
                else:
                    findings_after_hard.append((i, finding))

            logger.info(f"Hard exclusions removed {stats.hard_excluded} findings")
        else:
            findings_after_hard = [(i, f) for i, f in enumerate(findings)]

        # Step 2: Apply LLM filtering if enabled (one batched call for all remaining findings)
        findings_after_llm = []
        excluded_llm = []

        if self.use_llm_filtering and self.llm_client and findings_after_hard:
            logger.info(f"Reviewing {len(findings_after_hard)} findings through the Copilot CLI")
            batch = [finding for _, finding in findings_after_hard]
            success, decisions, error_msg = self.llm_client.analyze_findings(
                batch, pr_context, self.custom_filtering_instructions
            )
            if not success:
                logger.warning(f"LLM filtering failed, keeping all findings: {error_msg}")

            for position, (orig_idx, finding) in enumerate(findings_after_hard):
                decision = decisions.get(position) if success else None

                if decision:
                    confidence = decision.get('confidence_score', 10.0)
                    keep_finding = decision.get('keep_finding', True)
                    justification = decision.get('justification', '')
                    exclusion_reason = decision.get('exclusion_reason')

                    stats.confidence_scores.append(confidence)

                    if not keep_finding:
                        excluded_llm.append({
                            "finding": finding,
                            "confidence_score": confidence,
                            "exclusion_reason": exclusion_reason or f"Low confidence score: {confidence}",
                            "justification": justification,
                            "filter_stage": "llm"
                        })
                        stats.llm_excluded += 1
                    else:
                        enriched_finding = finding.copy()
                        enriched_finding['_filter_metadata'] = {
                            'confidence_score': confidence,
                            'justification': justification,
                        }
                        findings_after_llm.append(enriched_finding)
                        stats.kept_findings += 1
                else:
                    # No usable decision for this finding - keep it with a note
                    reason = error_msg if not success else 'No decision returned for this finding'
                    enriched_finding = finding.copy()
                    enriched_finding['_filter_metadata'] = {
                        'confidence_score': 10.0,  # Default high confidence
                        'justification': f'LLM filtering unavailable: {reason}',
                    }
                    findings_after_llm.append(enriched_finding)
                    stats.kept_findings += 1
        else:
            # LLM filtering disabled or no client - keep all findings from hard filter
            for orig_idx, finding in findings_after_hard:
                enriched_finding = finding.copy()
                enriched_finding['_filter_metadata'] = {
                    'confidence_score': 10.0,  # Default high confidence
                    'justification': 'LLM filtering disabled',
                }
                findings_after_llm.append(enriched_finding)
                stats.kept_findings += 1

        # Combine all excluded findings
        all_excluded = excluded_hard + excluded_llm

        # Calculate final statistics
        stats.runtime_seconds = time.time() - start_time

        # Build filtered results
        filtered_results = {
            "filtered_findings": findings_after_llm,
            "excluded_findings": all_excluded,
            "analysis_summary": {
                "total_findings": stats.total_findings,
                "kept_findings": stats.kept_findings,
                "excluded_findings": len(all_excluded),
                "hard_excluded": stats.hard_excluded,
                "llm_excluded": stats.llm_excluded,
                "exclusion_breakdown": stats.exclusion_breakdown,
                "average_confidence": sum(stats.confidence_scores) / len(stats.confidence_scores) if stats.confidence_scores else None,
                "runtime_seconds": stats.runtime_seconds
            }
        }

        logger.info(f"Filtering completed: {stats.kept_findings}/{stats.total_findings} findings kept "
                    f"({stats.runtime_seconds:.1f}s)")

        return True, filtered_results, stats
