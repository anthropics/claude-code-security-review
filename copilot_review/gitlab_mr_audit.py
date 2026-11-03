#!/usr/bin/env python3
"""
GitLab merge request security audit powered by the GitHub Copilot CLI.

Runs inside a GitLab CI merge request pipeline: fetches the MR from the GitLab API, asks the Copilot CLI
(``copilot -p``) to review it for security vulnerabilities, filters likely false positives and posts the
findings as threads on the merge request.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from copilot_review.prompts import get_security_audit_prompt
from copilot_review.findings_filter import FindingsFilter
from copilot_review.copilot_runner import CopilotRunner
from copilot_review.copilot_filter_client import CopilotFilterClient
from copilot_review.gitlab_client import (
    GitLabClient,
    SEVERITY_ORDER,
    finding_fingerprint,
    format_summary_comment,
    normalize_finding_path,
)
from copilot_review.constants import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_SUCCESS,
    EXIT_GENERAL_ERROR,
)
from copilot_review.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_FINDING_THREADS = 20


class ConfigurationError(ValueError):
    """Raised when configuration is invalid or missing."""
    pass


class AuditError(ValueError):
    """Raised when security audit operations fail."""
    pass


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def get_environment_config() -> int:
    """Get and validate the merge request IID from the environment.

    Returns:
        The merge request IID

    Raises:
        ConfigurationError: If the IID is missing or invalid
    """
    mr_iid_str = os.environ.get('MR_IID') or os.environ.get('CI_MERGE_REQUEST_IID')
    if not mr_iid_str:
        raise ConfigurationError('CI_MERGE_REQUEST_IID (or MR_IID) environment variable required '
                                 '(run in a merge request pipeline)')
    try:
        return int(mr_iid_str)
    except ValueError:
        raise ConfigurationError(f'Invalid merge request IID: {mr_iid_str}')


def get_repo_dir() -> Path:
    repo_path = os.environ.get('REPO_PATH') or os.environ.get('CI_PROJECT_DIR')
    return Path(repo_path) if repo_path else Path.cwd()


def initialize_clients() -> Tuple[GitLabClient, CopilotRunner]:
    """Initialize GitLab and Copilot clients.

    Raises:
        ConfigurationError: If client initialization fails
    """
    try:
        gitlab_client = GitLabClient()
    except Exception as e:
        raise ConfigurationError(f'Failed to initialize GitLab client: {str(e)}')

    try:
        timeout = os.environ.get('COPILOT_TIMEOUT')
        copilot_runner = CopilotRunner(timeout_minutes=int(timeout) if timeout else None)
    except Exception as e:
        raise ConfigurationError(f'Failed to initialize Copilot runner: {str(e)}')

    return gitlab_client, copilot_runner


def initialize_findings_filter(copilot_runner: CopilotRunner,
                               repo_dir: Path,
                               custom_filtering_instructions: Optional[str] = None) -> FindingsFilter:
    """Initialize the findings filter based on environment configuration.

    Raises:
        ConfigurationError: If filter initialization fails
    """
    try:
        if _env_flag('ENABLE_LLM_FILTERING', True):
            return FindingsFilter(
                use_hard_exclusions=True,
                use_llm_filtering=True,
                llm_client=CopilotFilterClient(copilot_runner, repo_dir),
                custom_filtering_instructions=custom_filtering_instructions,
            )
        return FindingsFilter(use_hard_exclusions=True, use_llm_filtering=False)
    except Exception as e:
        raise ConfigurationError(f'Failed to initialize findings filter: {str(e)}')


def run_security_audit(copilot_runner: CopilotRunner, repo_dir: Path, prompt: str) -> Dict[str, Any]:
    """Run the security audit with the Copilot CLI.

    Raises:
        AuditError: If the audit fails
    """
    success, error_msg, results = copilot_runner.run(repo_dir, prompt, purpose='audit', required_key='findings')
    if not success:
        raise AuditError(f'Security audit failed: {error_msg}')
    return results


def normalize_findings(findings: Any, repo_dir: Path) -> List[Dict[str, Any]]:
    """Keep only dict findings and make their file paths repository-relative."""
    normalized = []
    prefix = str(repo_dir).rstrip('/') + '/'
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        finding = dict(finding)
        path = str(finding.get('file', '') or '')
        if path.startswith(prefix):
            path = path[len(prefix):]
        finding['file'] = normalize_finding_path(path)
        normalized.append(finding)
    return normalized


def apply_findings_filter(findings_filter, original_findings: List[Dict[str, Any]],
                          pr_context: Dict[str, Any], gitlab_client: GitLabClient
                          ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Apply findings filter to reduce false positives.

    Returns:
        Tuple of (kept_findings, excluded_findings, analysis_summary)
    """
    filter_success, filter_results, filter_stats = findings_filter.filter_findings(
        original_findings, pr_context
    )

    if filter_success:
        kept_findings = filter_results.get('filtered_findings', [])
        excluded_findings = filter_results.get('excluded_findings', [])
        analysis_summary = filter_results.get('analysis_summary', {})
    else:
        # Filtering failed, keep all findings
        kept_findings = original_findings
        excluded_findings = []
        analysis_summary = {}

    # Apply final directory exclusion filtering
    final_kept_findings = []
    directory_excluded_findings = []

    for finding in kept_findings:
        if _is_finding_in_excluded_directory(finding, gitlab_client):
            directory_excluded_findings.append(finding)
        else:
            final_kept_findings.append(finding)

    all_excluded_findings = excluded_findings + directory_excluded_findings
    analysis_summary['directory_excluded_count'] = len(directory_excluded_findings)

    return final_kept_findings, all_excluded_findings, analysis_summary


def _is_finding_in_excluded_directory(finding: Dict[str, Any], gitlab_client: GitLabClient) -> bool:
    """Check if a finding references a file in an excluded directory."""
    file_path = finding.get('file', '')
    if not file_path:
        return False
    return gitlab_client._is_excluded(file_path)


def post_results(gitlab_client: GitLabClient,
                 mr_iid: int,
                 mr_data: Dict[str, Any],
                 findings: List[Dict[str, Any]],
                 filtering_summary: Dict[str, Any],
                 model: str,
                 already_posted: Optional[set] = None,
                 max_threads: int = DEFAULT_MAX_FINDING_THREADS,
                 post_clean_summary: bool = True) -> Dict[str, int]:
    """Post findings as MR threads followed by one summary thread.

    Findings already posted on an earlier commit (same fingerprint) are skipped. Failures to post a
    single finding never abort the run.
    """
    already_posted = already_posted or set()
    head_sha = (mr_data.get('diff_refs') or {}).get('head_sha') or ''

    fresh = [f for f in findings if finding_fingerprint(f) not in already_posted]
    fresh.sort(key=lambda f: SEVERITY_ORDER.get(str(f.get('severity', '')).upper(), 99))

    stats = {'posted_inline': 0, 'posted_general': 0, 'failed': 0,
             'skipped_duplicates': len(findings) - len(fresh), 'over_limit': 0}
    not_inline: List[Dict[str, Any]] = []

    for index, finding in enumerate(fresh):
        if index >= max_threads:
            stats['over_limit'] += 1
            not_inline.append(finding)
            continue
        try:
            mode = gitlab_client.post_finding(mr_iid, mr_data, finding)
        except Exception as e:
            logger.error(f"Failed to post finding for {finding.get('file')}: {e}")
            stats['failed'] += 1
            not_inline.append(finding)
            continue
        if mode == 'inline':
            stats['posted_inline'] += 1
        else:
            stats['posted_general'] += 1
            not_inline.append(finding)

    if findings or post_clean_summary:
        summary = format_summary_comment(findings, head_sha, model, filtering_summary, not_inline)
        try:
            gitlab_client.create_discussion(mr_iid, summary)
        except Exception as e:
            logger.error(f"Failed to post summary thread: {e}")
            stats['failed'] += 1

    return stats


def main():
    """Main execution function for the GitLab CI job."""
    try:
        # Get environment configuration
        try:
            mr_iid = get_environment_config()
        except ConfigurationError as e:
            print(json.dumps({'error': str(e)}))
            sys.exit(EXIT_CONFIGURATION_ERROR)

        # Load custom filtering instructions if provided
        custom_filtering_instructions = None
        filtering_file = os.environ.get('FALSE_POSITIVE_FILTERING_INSTRUCTIONS', '')
        if filtering_file and Path(filtering_file).exists():
            try:
                with open(filtering_file, 'r', encoding='utf-8') as f:
                    custom_filtering_instructions = f.read()
                    logger.info(f"Loaded custom filtering instructions from {filtering_file}")
            except Exception as e:
                logger.warning(f"Failed to read filtering instructions file {filtering_file}: {e}")

        # Load custom security scan instructions if provided
        custom_scan_instructions = None
        scan_file = os.environ.get('CUSTOM_SECURITY_SCAN_INSTRUCTIONS', '')
        if scan_file and Path(scan_file).exists():
            try:
                with open(scan_file, 'r', encoding='utf-8') as f:
                    custom_scan_instructions = f.read()
                    logger.info(f"Loaded custom security scan instructions from {scan_file}")
            except Exception as e:
                logger.warning(f"Failed to read security scan instructions file {scan_file}: {e}")

        repo_dir = get_repo_dir()
        dry_run = _env_flag('DRY_RUN')
        run_every_commit = _env_flag('RUN_EVERY_COMMIT')

        # Initialize components
        try:
            gitlab_client, copilot_runner = initialize_clients()
            findings_filter = initialize_findings_filter(copilot_runner, repo_dir, custom_filtering_instructions)
        except ConfigurationError as e:
            print(json.dumps({'error': str(e)}))
            sys.exit(EXIT_CONFIGURATION_ERROR)

        # Validate the Copilot CLI is available and authenticated
        copilot_ok, copilot_error = copilot_runner.validate_available()
        if not copilot_ok:
            print(json.dumps({'error': f'Copilot CLI not available: {copilot_error}'}))
            sys.exit(EXIT_GENERAL_ERROR)

        # Get MR data
        try:
            mr_data = gitlab_client.get_mr_data(mr_iid)
            mr_diff = gitlab_client.get_mr_diff(mr_data)
        except Exception as e:
            print(json.dumps({'error': f'Failed to fetch MR data: {str(e)}'}))
            sys.exit(EXIT_GENERAL_ERROR)

        # Merge requests from forks are untrusted input for an agent that holds secrets
        source_project = mr_data.get('source_project_id')
        target_project = mr_data.get('target_project_id')
        if source_project and target_project and source_project != target_project \
                and not _env_flag('ALLOW_FORK_MRS'):
            print(json.dumps({'skipped': 'MR comes from a fork; set ALLOW_FORK_MRS=true to review it'}))
            sys.exit(EXIT_SUCCESS)

        head_sha = (mr_data.get('diff_refs') or {}).get('head_sha') or ''

        # Skip if this MR (or this commit) has already been reviewed
        posted_fingerprints: set = set()
        try:
            discussions = gitlab_client.list_discussions(mr_iid)
            summary_shas, posted_fingerprints = gitlab_client.find_review_markers(discussions)
            if summary_shas and not run_every_commit:
                print(json.dumps({'skipped': 'MR already reviewed (set RUN_EVERY_COMMIT=true to review every commit)'}))
                sys.exit(EXIT_SUCCESS)
            if head_sha and head_sha in summary_shas:
                print(json.dumps({'skipped': f'commit {head_sha[:8]} already reviewed'}))
                sys.exit(EXIT_SUCCESS)
        except SystemExit:
            raise
        except Exception as e:
            logger.warning(f"Could not read existing discussions, continuing without duplicate checks: {e}")

        if not mr_data['files']:
            print(json.dumps({'skipped': 'no reviewable files in this MR'}))
            sys.exit(EXIT_SUCCESS)

        # Generate security audit prompt and run the audit
        result_path = CopilotRunner.result_path_for(repo_dir, 'audit')
        prompt = get_security_audit_prompt(mr_data, mr_diff, custom_scan_instructions=custom_scan_instructions,
                                           result_path=result_path)
        success, error_msg, results = copilot_runner.run(repo_dir, prompt, purpose='audit', required_key='findings')

        # If prompt is too long, retry without diff
        if not success and error_msg == "PROMPT_TOO_LONG":
            print(f"[Info] Prompt too long, retrying without diff. Original prompt length: {len(prompt)} characters",
                  file=sys.stderr)
            prompt_without_diff = get_security_audit_prompt(
                mr_data, mr_diff, include_diff=False,
                custom_scan_instructions=custom_scan_instructions, result_path=result_path)
            print(f"[Info] New prompt length: {len(prompt_without_diff)} characters", file=sys.stderr)
            success, error_msg, results = copilot_runner.run(
                repo_dir, prompt_without_diff, purpose='audit', required_key='findings')

        if not success:
            print(json.dumps({'error': f'Security audit failed: {error_msg}'}))
            sys.exit(EXIT_GENERAL_ERROR)

        original_findings = normalize_findings(results.get('findings', []), repo_dir)

        # Prepare MR context for better filtering
        pr_context = {
            'repo_name': mr_data['head']['repo']['full_name'],
            'pr_number': mr_iid,
            'title': mr_data.get('title', ''),
            'description': mr_data.get('body', '')
        }

        kept_findings, excluded_findings, analysis_summary = apply_findings_filter(
            findings_filter, original_findings, pr_context, gitlab_client
        )

        filtering_summary = {
            'total_original_findings': len(original_findings),
            'excluded_findings': len(excluded_findings),
            'kept_findings': len(kept_findings),
            'filter_analysis': analysis_summary,
            'excluded_findings_details': excluded_findings  # Include full details of what was filtered
        }

        # Post findings to the merge request as threads
        posting: Dict[str, Any] = {'dry_run': dry_run}
        if not dry_run:
            max_threads = int(os.environ.get('MAX_FINDING_THREADS') or DEFAULT_MAX_FINDING_THREADS)
            posting.update(post_results(
                gitlab_client, mr_iid, mr_data, kept_findings, filtering_summary,
                model=copilot_runner.model,
                already_posted=posted_fingerprints,
                max_threads=max_threads,
                post_clean_summary=_env_flag('POST_CLEAN_SUMMARY', True),
            ))

        output = {
            'mr_iid': mr_iid,
            'repo': mr_data['head']['repo']['full_name'],
            'head_sha': head_sha,
            'model': copilot_runner.model,
            'findings': kept_findings,
            'analysis_summary': results.get('analysis_summary', {}),
            'filtering_summary': filtering_summary,
            'posting': posting,
        }

        results_file = Path(os.environ.get('RESULTS_FILE') or (repo_dir / 'copilot-review-results.json'))
        try:
            results_file.write_text(json.dumps(output, indent=2), encoding='utf-8')
        except OSError as e:
            logger.warning(f"Could not write results file {results_file}: {e}")

        print(json.dumps(output, indent=2))

        # Exit with appropriate code. Failing the job on HIGH findings is opt-in in CI.
        high_severity_count = len([f for f in kept_findings if str(f.get('severity', '')).upper() == 'HIGH'])
        if high_severity_count > 0 and _env_flag('FAIL_ON_HIGH_SEVERITY'):
            sys.exit(EXIT_GENERAL_ERROR)
        sys.exit(EXIT_SUCCESS)

    except SystemExit:
        raise
    except Exception as e:
        print(json.dumps({'error': f'Unexpected error: {str(e)}'}))
        sys.exit(EXIT_CONFIGURATION_ERROR)


if __name__ == '__main__':
    main()
