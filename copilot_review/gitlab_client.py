"""GitLab API client for merge request security reviews.

Fetches MR metadata and diffs and posts findings as MR discussion threads. Findings that map to a
line inside the MR diff become inline (diff) threads; everything else falls back to a general thread.
"""

import hashlib
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from copilot_review.constants import FINDING_MARKER, SUMMARY_MARKER
from copilot_review.logger import get_logger

logger = get_logger(__name__)

_HUNK_RE = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')
_SUMMARY_MARKER_RE = re.compile(rf'<!--\s*{re.escape(SUMMARY_MARKER)}\s+sha=([0-9a-fA-F]+)\s*-->')
_FINDING_MARKER_RE = re.compile(rf'<!--\s*{re.escape(FINDING_MARKER)}\s+fp=([0-9a-fA-F]+)')

SEVERITY_ORDER = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
REQUEST_TIMEOUT = 30


class GitLabAPIError(RuntimeError):
    """Raised when a GitLab API call fails."""


def parse_diff_line_map(patch: str) -> Dict[int, Optional[int]]:
    """Map new-side line numbers to old-side line numbers for a hunk-only GitLab diff.

    Added lines map to ``None``; context lines map to their old line number. Lines that are not part
    of the diff are absent, which means GitLab cannot attach an inline thread to them.
    """
    mapping: Dict[int, Optional[int]] = {}
    old_line: Optional[int] = None
    new_line: Optional[int] = None

    for line in (patch or '').splitlines():
        match = _HUNK_RE.match(line)
        if match:
            old_line = int(match.group(1))
            new_line = int(match.group(2))
            continue
        if old_line is None or new_line is None:
            continue
        if line.startswith('+'):
            mapping[new_line] = None
            new_line += 1
        elif line.startswith('-'):
            old_line += 1
        elif line.startswith('\\'):
            continue  # "\ No newline at end of file"
        else:
            mapping[new_line] = old_line
            old_line += 1
            new_line += 1
    return mapping


def count_changes(patch: str) -> Tuple[int, int]:
    """Count (additions, deletions) in a hunk-only diff."""
    additions = deletions = 0
    in_hunk = False
    for line in (patch or '').splitlines():
        if _HUNK_RE.match(line):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith('+'):
            additions += 1
        elif line.startswith('-'):
            deletions += 1
    return additions, deletions


def build_unified_diff(raw_diffs: List[Dict[str, Any]]) -> str:
    """Rebuild a ``git diff`` style text from GitLab diff entries (which contain hunks only)."""
    sections = []
    for entry in raw_diffs:
        old_path = entry.get('old_path') or entry.get('new_path') or ''
        new_path = entry.get('new_path') or old_path
        body = entry.get('diff') or ''
        old_header = '/dev/null' if entry.get('new_file') else f'a/{old_path}'
        new_header = '/dev/null' if entry.get('deleted_file') else f'b/{new_path}'
        header = f'diff --git a/{old_path} b/{new_path}\n--- {old_header}\n+++ {new_header}\n'
        if body and not body.endswith('\n'):
            body += '\n'
        sections.append(header + body)
    return ''.join(sections)


def sanitize_markdown(text: Any) -> str:
    """Neutralise model-generated text before it is posted as an MR note.

    * GitLab executes quick actions (``/merge``, ``/assign`` ...) found at the start of a line, using
      the token owner's permissions, so such lines are defused.
    * ``@user`` mentions would notify people, so they are defused too.
    """
    if text is None:
        return ''
    cleaned = []
    for line in str(text).splitlines():
        if line.lstrip().startswith('/'):
            line = '​' + line
        cleaned.append(line)
    result = '\n'.join(cleaned)
    return re.sub(r'(?<![\w`])@(?=\w)', '@​', result)


def finding_fingerprint(finding: Dict[str, Any]) -> str:
    """Stable short fingerprint used to avoid reposting the same finding on later commits."""
    file_path = normalize_finding_path(finding.get('file', ''))
    category = str(finding.get('category', '')).lower()
    description = str(finding.get('description', '')).lower()[:120]
    digest = hashlib.sha1(f'{file_path}|{category}|{description}'.encode('utf-8')).hexdigest()
    return digest[:12]


def normalize_finding_path(path: Any) -> str:
    path = str(path or '').strip()
    while path.startswith('./'):
        path = path[2:]
    return path


def format_finding_comment(finding: Dict[str, Any], head_sha: str, inline: bool) -> str:
    """Markdown body for one finding thread."""
    severity = str(finding.get('severity', 'UNKNOWN')).upper()
    category = sanitize_markdown(finding.get('category', 'security'))
    fp = finding_fingerprint(finding)

    lines = [
        f'<!-- {FINDING_MARKER} fp={fp} sha={head_sha} -->',
        f'**Security finding: {severity}** (`{category}`)',
        '',
    ]
    if not inline:
        location = normalize_finding_path(finding.get('file', ''))
        if location:
            line_no = finding.get('line')
            lines.append(f'Location: `{location}`' + (f' line {line_no}' if line_no else ''))
            lines.append('')

    lines.append(sanitize_markdown(finding.get('description', '')))

    if finding.get('exploit_scenario'):
        lines += ['', '**Exploit scenario**', '', sanitize_markdown(finding['exploit_scenario'])]
    if finding.get('recommendation'):
        lines += ['', '**Recommendation**', '', sanitize_markdown(finding['recommendation'])]

    confidence = finding.get('confidence')
    if confidence is not None:
        lines += ['', f'_Confidence: {confidence}_']
    return '\n'.join(lines)


def format_summary_comment(findings: List[Dict[str, Any]],
                           head_sha: str,
                           model: str,
                           filtering_summary: Optional[Dict[str, Any]] = None,
                           not_inline: Optional[List[Dict[str, Any]]] = None) -> str:
    """Markdown body for the summary thread (also acts as the 'already reviewed' marker)."""
    counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for finding in findings:
        sev = str(finding.get('severity', '')).upper()
        if sev in counts:
            counts[sev] += 1

    lines = [f'<!-- {SUMMARY_MARKER} sha={head_sha} -->', '## Copilot Security Review', '']
    if not findings:
        lines.append('No security findings were reported for this merge request.')
    else:
        lines.append(f'{len(findings)} finding(s): '
                     f'{counts["HIGH"]} high, {counts["MEDIUM"]} medium, {counts["LOW"]} low.')
        if not_inline:
            lines += ['', 'Findings that could not be attached to a diff line:']
            for finding in not_inline:
                loc = normalize_finding_path(finding.get('file', '')) or 'unknown file'
                if finding.get('line'):
                    loc += f':{finding["line"]}'
                lines.append(f'- `{loc}` ({str(finding.get("severity", "")).upper()}) '
                             f'{sanitize_markdown(finding.get("description", ""))[:200]}')

    if filtering_summary:
        original = filtering_summary.get('total_original_findings')
        excluded = filtering_summary.get('excluded_findings')
        if original is not None and excluded is not None:
            lines += ['', f'_Filtering: {original} raw finding(s), {excluded} excluded as likely false positives._']

    lines += ['', f'_Model: `{model}` · commit `{head_sha[:8]}` · automated review, verify findings before acting._']
    return '\n'.join(lines)


class GitLabClient:
    """Minimal GitLab REST API v4 client for MR security reviews."""

    def __init__(self,
                 api_url: Optional[str] = None,
                 token: Optional[str] = None,
                 project_id: Optional[str] = None,
                 session: Optional[requests.Session] = None):
        api_url = api_url or os.environ.get('CI_API_V4_URL')
        if not api_url and os.environ.get('GITLAB_URL'):
            api_url = os.environ['GITLAB_URL'].rstrip('/') + '/api/v4'
        if not api_url:
            raise ValueError("CI_API_V4_URL (or GITLAB_URL) environment variable required")
        self.api_url = api_url.rstrip('/')

        self.token = token or os.environ.get('GITLAB_TOKEN')
        if not self.token:
            raise ValueError("GITLAB_TOKEN environment variable required "
                             "(project access token with 'api' scope; CI_JOB_TOKEN cannot post MR notes)")

        self.project_id = str(project_id or os.environ.get('CI_PROJECT_ID') or '')
        if not self.project_id:
            raise ValueError("CI_PROJECT_ID environment variable required")

        self.session = session or requests.Session()
        self.headers = {'PRIVATE-TOKEN': self.token}

        exclude_dirs = os.environ.get('EXCLUDE_DIRECTORIES', '')
        self.excluded_dirs = [d.strip() for d in exclude_dirs.split(',') if d.strip()] if exclude_dirs else []
        if self.excluded_dirs:
            print(f"[Debug] Excluded directories: {self.excluded_dirs}", file=sys.stderr)

        # new_path -> {'old_path': str, 'line_map': {new_line: old_line|None}}
        self._file_info: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ HTTP helpers
    def _url(self, path: str) -> str:
        return f'{self.api_url}{path}'

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """HTTP request with a small retry for rate limits and transient server errors."""
        last_response = None
        for attempt in range(3):
            response = self.session.request(
                method, self._url(path), headers=self.headers, timeout=REQUEST_TIMEOUT, **kwargs
            )
            last_response = response
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                retry_after = response.headers.get('Retry-After', '')
                delay = int(retry_after) if retry_after.isdigit() else 2 * (attempt + 1)
                time.sleep(min(delay, 30))
                continue
            break
        return last_response

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        response = self._request('GET', path, params=params)
        if response.status_code >= 400:
            raise GitLabAPIError(f'GET {path} failed: {response.status_code} {response.text[:300]}')
        return response.json()

    def _get_paginated(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        items: List[Any] = []
        page = 1
        while True:
            query = dict(params or {})
            query.update({'per_page': 100, 'page': page})
            response = self._request('GET', path, params=query)
            if response.status_code >= 400:
                raise GitLabAPIError(f'GET {path} failed: {response.status_code} {response.text[:300]}')
            data = response.json()
            items.extend(data)
            next_page = response.headers.get('X-Next-Page', '')
            if not next_page:
                break
            page = int(next_page)
        return items

    # ------------------------------------------------------------------ MR data
    def _project_path(self) -> str:
        path = os.environ.get('CI_PROJECT_PATH')
        if path:
            return path
        try:
            project = self._get(f'/projects/{self.project_id}')
            return project.get('path_with_namespace') or self.project_id
        except Exception:
            return self.project_id

    def get_mr_diffs(self, mr_iid: int) -> List[Dict[str, Any]]:
        """List the diff entries of an MR (``/diffs``, falling back to the older ``/changes``)."""
        base = f'/projects/{self.project_id}/merge_requests/{mr_iid}'
        try:
            return self._get_paginated(f'{base}/diffs')
        except GitLabAPIError as e:
            if '404' not in str(e):
                raise
            logger.info("/diffs endpoint not available, falling back to /changes")
            return self._get(f'{base}/changes').get('changes', [])

    def get_mr_data(self, mr_iid: int) -> Dict[str, Any]:
        """Get MR metadata and changed files in the shape the prompt builder expects."""
        base = f'/projects/{self.project_id}/merge_requests/{mr_iid}'
        mr = self._get(base)

        # diff_refs can be null right after an MR is created or updated
        for _ in range(3):
            if mr.get('diff_refs'):
                break
            time.sleep(3)
            mr = self._get(base)

        raw_diffs = self.get_mr_diffs(mr_iid)

        files = []
        self._file_info = {}
        for entry in raw_diffs:
            new_path = entry.get('new_path') or entry.get('old_path') or ''
            if self._is_excluded(new_path):
                continue
            patch = entry.get('diff') or ''
            additions, deletions = count_changes(patch)
            if entry.get('new_file'):
                status = 'added'
            elif entry.get('deleted_file'):
                status = 'removed'
            elif entry.get('renamed_file'):
                status = 'renamed'
            else:
                status = 'modified'
            files.append({
                'filename': new_path,
                'status': status,
                'additions': additions,
                'deletions': deletions,
                'changes': additions + deletions,
                'patch': patch,
            })
            self._file_info[new_path] = {
                'old_path': entry.get('old_path') or new_path,
                'line_map': parse_diff_line_map(patch),
            }

        diff_refs = mr.get('diff_refs') or {}
        return {
            'number': mr['iid'],
            'title': mr.get('title', ''),
            'body': mr.get('description') or '',
            'user': (mr.get('author') or {}).get('username', 'unknown'),
            'created_at': mr.get('created_at'),
            'updated_at': mr.get('updated_at'),
            'state': mr.get('state'),
            'web_url': mr.get('web_url'),
            'source_project_id': mr.get('source_project_id'),
            'target_project_id': mr.get('target_project_id'),
            'head': {
                'ref': mr.get('source_branch'),
                'sha': diff_refs.get('head_sha') or mr.get('sha'),
                'repo': {'full_name': self._project_path()},
            },
            'base': {
                'ref': mr.get('target_branch'),
                'sha': diff_refs.get('base_sha'),
            },
            'diff_refs': {
                'base_sha': diff_refs.get('base_sha'),
                'start_sha': diff_refs.get('start_sha'),
                'head_sha': diff_refs.get('head_sha') or mr.get('sha'),
            },
            'files': files,
            'additions': sum(f['additions'] for f in files),
            'deletions': sum(f['deletions'] for f in files),
            'changed_files': len(files),
            '_raw_diffs': raw_diffs,
        }

    def get_mr_diff(self, mr_data: Dict[str, Any]) -> str:
        """Unified diff for the prompt, without generated files and excluded directories."""
        return self._filter_generated_files(build_unified_diff(mr_data.get('_raw_diffs', [])))

    def _is_excluded(self, filepath: str) -> bool:
        """Check if a file should be excluded based on directory patterns."""
        for excluded_dir in self.excluded_dirs:
            normalized_excluded = excluded_dir[2:] if excluded_dir.startswith('./') else excluded_dir
            if filepath.startswith(excluded_dir + '/'):
                return True
            if filepath.startswith(normalized_excluded + '/'):
                return True
            if '/' + normalized_excluded + '/' in filepath:
                return True
        return False

    def _filter_generated_files(self, diff_text: str) -> str:
        """Filter out generated files and excluded directories from diff content."""
        file_sections = re.split(r'(?=^diff --git)', diff_text, flags=re.MULTILINE)
        filtered_sections = []

        for section in file_sections:
            if not section.strip():
                continue
            if ('@generated' in section or
                    'Code generated by OpenAPI Generator' in section or
                    'Code generated by protoc-gen-go' in section):
                continue
            match = re.match(r'^diff --git a/(.*?) b/', section)
            if match and self._is_excluded(match.group(1)):
                print(f"[Debug] Filtering out excluded file: {match.group(1)}", file=sys.stderr)
                continue
            filtered_sections.append(section)

        return ''.join(filtered_sections)

    # ------------------------------------------------------------------ discussions
    def list_discussions(self, mr_iid: int) -> List[Dict[str, Any]]:
        return self._get_paginated(f'/projects/{self.project_id}/merge_requests/{mr_iid}/discussions')

    @staticmethod
    def find_review_markers(discussions: List[Dict[str, Any]]) -> Tuple[Set[str], Set[str]]:
        """Return (shas that already have a summary thread, fingerprints of already posted findings)."""
        summary_shas: Set[str] = set()
        fingerprints: Set[str] = set()
        for discussion in discussions:
            for note in discussion.get('notes', []):
                body = note.get('body') or ''
                for match in _SUMMARY_MARKER_RE.finditer(body):
                    summary_shas.add(match.group(1))
                for match in _FINDING_MARKER_RE.finditer(body):
                    fingerprints.add(match.group(1))
        return summary_shas, fingerprints

    def build_position(self, mr_data: Dict[str, Any], file_path: str, line: Any) -> Optional[Dict[str, Any]]:
        """Build the ``position`` for an inline thread, or None if the line is not part of the diff."""
        refs = mr_data.get('diff_refs') or {}
        if not (refs.get('base_sha') and refs.get('start_sha') and refs.get('head_sha')):
            return None
        info = self._file_info.get(normalize_finding_path(file_path))
        if not info:
            return None
        try:
            line_no = int(line)
        except (TypeError, ValueError):
            return None
        line_map = info['line_map']
        if line_no not in line_map:
            return None

        position: Dict[str, Any] = {
            'position_type': 'text',
            'base_sha': refs['base_sha'],
            'start_sha': refs['start_sha'],
            'head_sha': refs['head_sha'],
            'old_path': info['old_path'],
            'new_path': normalize_finding_path(file_path),
            'new_line': line_no,
        }
        old_line = line_map[line_no]
        if old_line is not None:  # unchanged context line needs both sides
            position['old_line'] = old_line
        return position

    def create_discussion(self, mr_iid: int, body: str, position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a new MR thread (optionally anchored to a diff line)."""
        data: Dict[str, Any] = {'body': body}
        if position:
            for key, value in position.items():
                data[f'position[{key}]'] = str(value)
        response = self._request('POST', f'/projects/{self.project_id}/merge_requests/{mr_iid}/discussions',
                                 data=data)
        if response.status_code >= 400:
            raise GitLabAPIError(f'Creating discussion failed: {response.status_code} {response.text[:300]}')
        return response.json()

    def post_finding(self, mr_iid: int, mr_data: Dict[str, Any], finding: Dict[str, Any]) -> str:
        """Post one finding as a thread. Returns ``'inline'`` or ``'general'``."""
        head_sha = (mr_data.get('diff_refs') or {}).get('head_sha') or ''
        position = self.build_position(mr_data, finding.get('file', ''), finding.get('line'))

        if position:
            try:
                self.create_discussion(mr_iid, format_finding_comment(finding, head_sha, inline=True), position)
                return 'inline'
            except GitLabAPIError as e:
                # GitLab answers 400/500 when the position does not resolve; fall back to a general thread
                logger.warning(f"Inline thread rejected, posting a general thread instead: {e}")

        self.create_discussion(mr_iid, format_finding_comment(finding, head_sha, inline=False))
        return 'general'
