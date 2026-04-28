#!/usr/bin/env python3
"""Whole-repo security audit using parallel Claude Code subprocesses.

Unlike github_action_audit.py (which scans a single PR diff), this entrypoint
walks an entire repository and dispatches multiple `claude` CLI invocations
in parallel — one per chunk — then merges and filters the findings.

Auth: relies on the `claude` CLI's own auth (OAuth via `claude /login` or
ANTHROPIC_API_KEY env var). The hard-coded API-key check in
SimpleClaudeRunner.validate_claude_available is intentionally bypassed.

Filtering: uses FindingsFilter with hard regex rules only (no Claude API
filter pass), so no API key is required.
"""

import argparse
import concurrent.futures
import fnmatch
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from claudecode.github_action_audit import SimpleClaudeRunner
from claudecode.findings_filter import FindingsFilter
from claudecode.prompts import get_repo_audit_prompt, get_tenant_scope_audit_prompt
from claudecode.logger import get_logger

logger = get_logger(__name__)


SOURCE_EXTENSIONS = {
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
    '.py', '.rb', '.php',
    '.go', '.rs', '.java', '.kt', '.scala', '.swift',
    '.c', '.cc', '.cpp', '.h', '.hpp',
    '.sql',
}

DEFAULT_EXCLUDE_PATTERNS = [
    # Dependency / build output
    'node_modules/',
    'dist/',
    'build/',
    'coverage/',
    '.next/',
    '.nuxt/',
    'vendor/',
    'target/',
    # Replit / scratch
    'attached_assets/',
    # Tests — typically not security-relevant and can be huge
    '__tests__/',
    '*.test.ts', '*.test.tsx', '*.test.js', '*.test.jsx',
    '*.spec.ts', '*.spec.tsx', '*.spec.js', '*.spec.jsx',
    '*_test.py', 'test_*.py',
    # Lockfiles / generated
    'package-lock.json',
    'yarn.lock',
    'pnpm-lock.yaml',
    'Cargo.lock',
    '*.min.js', '*.min.css',
    # Heuristic dead code
    '*-old.ts', '*-old.tsx', '*-old.js',
    '*-broken.ts', '*-broken.tsx', '*-broken.js',
    'storage-old.ts', 'storage-broken.ts',
]


def list_source_files(repo_dir: Path) -> List[Path]:
    """List source files via `git ls-files` (respects .gitignore).

    Falls back to filesystem walk if the directory is not a git repo.
    """
    try:
        result = subprocess.run(
            ['git', '-C', str(repo_dir), 'ls-files'],
            capture_output=True, text=True, check=True, timeout=30,
        )
        paths = [Path(line) for line in result.stdout.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("git ls-files unavailable; falling back to filesystem walk")
        paths = []
        for root, dirs, files in os.walk(repo_dir):
            # Prune common heavy directories early
            dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', 'dist', 'build', 'coverage'}]
            for fn in files:
                full = Path(root) / fn
                paths.append(full.relative_to(repo_dir))

    return [p for p in paths if p.suffix.lower() in SOURCE_EXTENSIONS]


def is_excluded(rel_path: Path, patterns: List[str]) -> bool:
    """Check whether a relative path matches any exclude pattern.

    Patterns ending in '/' are treated as directory prefixes (matches anywhere
    in the path). Other patterns are fnmatch-checked against the filename and
    against the full posix-style path.
    """
    s = rel_path.as_posix()
    name = rel_path.name
    for pat in patterns:
        if pat.endswith('/'):
            dir_name = pat.rstrip('/')
            if s.startswith(dir_name + '/') or f'/{dir_name}/' in s:
                return True
        elif '*' in pat or '?' in pat or '[' in pat:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(s, pat):
                return True
        else:
            if name == pat or s == pat or s.endswith('/' + pat):
                return True
    return False


def apply_excludes(files: List[Path], patterns: List[str]) -> List[Path]:
    return [f for f in files if not is_excluded(f, patterns)]


def plan_chunks(
    files: List[Path],
    repo_dir: Path,
    max_chunk_bytes: int,
    max_chunk_files: int,
) -> List[List[Path]]:
    """Group files into chunks: by directory, splitting when oversized.

    Files larger than max_chunk_bytes get their own solo chunk. Within a
    directory, files are bin-packed in alphabetical order until either the
    byte cap or the file-count cap is hit, then a new chunk starts.
    """
    by_dir: Dict[str, List[Path]] = {}
    for f in files:
        by_dir.setdefault(f.parent.as_posix(), []).append(f)

    chunks: List[List[Path]] = []
    for parent in sorted(by_dir.keys()):
        group = sorted(by_dir[parent], key=lambda p: p.as_posix())
        current: List[Path] = []
        current_bytes = 0

        for f in group:
            try:
                size = (repo_dir / f).stat().st_size
            except OSError:
                size = 0

            if size > max_chunk_bytes:
                if current:
                    chunks.append(current)
                    current, current_bytes = [], 0
                chunks.append([f])
                continue

            if current and (current_bytes + size > max_chunk_bytes
                            or len(current) >= max_chunk_files):
                chunks.append(current)
                current, current_bytes = [], 0

            current.append(f)
            current_bytes += size

        if current:
            chunks.append(current)

    return chunks


def load_shared_context(repo_dir: Path, max_bytes_per_file: int = 8000) -> str:
    """Read repo-level orientation files into a single context blob."""
    parts: List[str] = []
    for fname in ['CLAUDE.md', 'AGENTS.md', 'README.md']:
        p = repo_dir / fname
        if not (p.exists() and p.is_file()):
            continue
        try:
            content = p.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        if len(content) > max_bytes_per_file:
            content = content[:max_bytes_per_file] + '\n... [truncated] ...'
        parts.append(f"### {fname}\n{content}")
    return '\n\n'.join(parts)


def chunk_label(chunk: List[Path]) -> str:
    """Human-friendly one-line summary of a chunk for logging."""
    if len(chunk) == 1:
        return chunk[0].as_posix()
    parents = sorted({f.parent.as_posix() for f in chunk})
    if len(parents) == 1:
        return f"{parents[0]}/ ({len(chunk)} files)"
    return f"{parents[0]}/+{len(parents) - 1} dirs ({len(chunk)} files)"


def chunk_bytes(chunk: List[Path], repo_dir: Path) -> int:
    total = 0
    for f in chunk:
        try:
            total += (repo_dir / f).stat().st_size
        except OSError:
            pass
    return total


def run_chunk(
    chunk_id: int,
    chunk_count: int,
    chunk_files: List[Path],
    repo_dir: Path,
    shared_context: str,
    timeout_minutes: int,
    custom_scan_instructions: Optional[str],
    mode: str = 'general',
    known_findings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run a single chunk through the Claude CLI and return its result."""
    runner = SimpleClaudeRunner(timeout_minutes=timeout_minutes)
    file_list_str = '\n'.join(f"- {f.as_posix()}" for f in chunk_files)
    if mode == 'tenant-scope':
        prompt = get_tenant_scope_audit_prompt(
            file_list=file_list_str,
            shared_context=shared_context,
            known_findings=known_findings,
            chunk_index=chunk_id,
            chunk_count=chunk_count,
        )
    else:
        prompt = get_repo_audit_prompt(
            file_list=file_list_str,
            shared_context=shared_context,
            custom_scan_instructions=custom_scan_instructions,
            chunk_index=chunk_id,
            chunk_count=chunk_count,
        )

    label = chunk_label(chunk_files)
    logger.info(f"[chunk {chunk_id + 1}/{chunk_count}] starting: {label}")
    started = time.time()

    success, error_msg, results = runner.run_security_audit(repo_dir, prompt)
    elapsed = time.time() - started

    findings = results.get('findings', []) if success else []
    for f in findings:
        f['_chunk_id'] = chunk_id

    logger.info(
        f"[chunk {chunk_id + 1}/{chunk_count}] done in {elapsed:.0f}s — "
        f"{'OK' if success else 'FAIL'}, {len(findings)} findings"
    )

    return {
        'chunk_id': chunk_id,
        'label': label,
        'files': [f.as_posix() for f in chunk_files],
        'success': success,
        'error': None if success else error_msg,
        'findings': findings,
        'elapsed_seconds': elapsed,
    }


def dedupe_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate findings with the same (file, line, category) key.

    When duplicates collide, keep the highest-confidence record.
    """
    SEVERITY_RANK = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}

    by_key: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
    for f in findings:
        key = (
            f.get('file', ''),
            int(f.get('line', 0) or 0),
            (f.get('category') or '').lower(),
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = f
            continue

        # Prefer higher severity, then higher confidence
        ex_sev = SEVERITY_RANK.get((existing.get('severity') or '').upper(), 0)
        new_sev = SEVERITY_RANK.get((f.get('severity') or '').upper(), 0)
        if new_sev > ex_sev:
            by_key[key] = f
        elif new_sev == ex_sev:
            if (f.get('confidence') or 0) > (existing.get('confidence') or 0):
                by_key[key] = f

    return list(by_key.values())


def check_claude_cli() -> Tuple[bool, str]:
    """Verify the `claude` CLI is on PATH. Does NOT require ANTHROPIC_API_KEY."""
    try:
        result = subprocess.run(
            ['claude', '--version'],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, f"claude --version exited {result.returncode}: {result.stderr}"
    except FileNotFoundError:
        return False, "`claude` CLI not found on PATH. Install via `npm install -g @anthropic-ai/claude-code`."
    except subprocess.TimeoutExpired:
        return False, "`claude --version` timed out"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='python -m claudecode.repo_audit',
        description="Run a security audit across an entire repository in parallel chunks.",
    )
    p.add_argument('repo_path', help="Path to the repository to audit")
    p.add_argument('-o', '--output', default='repo-audit-results.json',
                   help="Output JSON path (default: repo-audit-results.json)")
    p.add_argument('-c', '--concurrency', type=int, default=3,
                   help="Number of parallel `claude` invocations (default: 3)")
    p.add_argument('-t', '--timeout-minutes', type=int, default=15,
                   help="Per-chunk timeout in minutes (default: 15)")
    p.add_argument('--max-chunk-bytes', type=int, default=150_000,
                   help="Max source bytes per chunk (default: 150000)")
    p.add_argument('--max-chunk-files', type=int, default=25,
                   help="Max files per chunk (default: 25)")
    p.add_argument('--exclude', action='append', default=[],
                   help="Additional exclude pattern (repeatable). Trailing / = directory prefix; * = glob.")
    p.add_argument('--no-default-excludes', action='store_true',
                   help="Disable the built-in default exclude list")
    p.add_argument('--custom-scan-instructions',
                   help="Path to a text file appended to each chunk's prompt (general mode only)")
    p.add_argument('--mode', choices=['general', 'tenant-scope'], default='general',
                   help="Audit mode: 'general' (default) or 'tenant-scope' (focused IDOR/authz pass)")
    p.add_argument('--known-findings',
                   help="Path to a prior repo-audit-results.json. Findings are passed as anchors "
                        "(tenant-scope mode) so Claude looks for similar bugs without re-reporting them.")
    p.add_argument('--dry-run', action='store_true',
                   help="Print the chunk plan and exit without invoking Claude")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    repo_dir = Path(args.repo_path).resolve()
    if not repo_dir.is_dir():
        print(f"error: not a directory: {repo_dir}", file=sys.stderr)
        return 2

    # Build the file list
    files = list_source_files(repo_dir)
    patterns = list(args.exclude)
    if not args.no_default_excludes:
        patterns = DEFAULT_EXCLUDE_PATTERNS + patterns
    files = apply_excludes(files, patterns)

    if not files:
        print("error: no source files left after applying excludes", file=sys.stderr)
        return 2

    chunks = plan_chunks(files, repo_dir, args.max_chunk_bytes, args.max_chunk_files)

    total_bytes = sum(chunk_bytes(c, repo_dir) for c in chunks)
    logger.info(
        f"planned {len(chunks)} chunks across {len(files)} files "
        f"({total_bytes // 1024} KB total source)"
    )
    for i, chunk in enumerate(chunks):
        logger.info(
            f"  [{i + 1:3d}/{len(chunks)}] {chunk_bytes(chunk, repo_dir) // 1024:4d}KB  "
            f"{chunk_label(chunk)}"
        )

    if args.dry_run:
        return 0

    # Pre-flight: claude CLI must be installed
    cli_ok, cli_msg = check_claude_cli()
    if not cli_ok:
        print(f"error: {cli_msg}", file=sys.stderr)
        return 2
    logger.info(f"claude CLI: {cli_msg}")

    # Custom scan instructions
    custom_scan_instructions: Optional[str] = None
    if args.custom_scan_instructions:
        cp = Path(args.custom_scan_instructions)
        if cp.exists():
            custom_scan_instructions = cp.read_text(encoding='utf-8')
        else:
            logger.warning(f"--custom-scan-instructions not found: {cp}")

    shared_context = load_shared_context(repo_dir)
    if shared_context:
        logger.info(f"loaded shared context ({len(shared_context)} chars)")

    # Optional anchors from a previous run (tenant-scope mode)
    known_findings: Optional[List[Dict[str, Any]]] = None
    if args.known_findings:
        kp = Path(args.known_findings)
        if kp.exists():
            try:
                prior = json.loads(kp.read_text(encoding='utf-8'))
                known_findings = prior.get('findings', []) or []
                logger.info(f"loaded {len(known_findings)} known findings from {kp}")
            except Exception as e:
                logger.warning(f"failed to load --known-findings {kp}: {e}")
        else:
            logger.warning(f"--known-findings not found: {kp}")

    # Dispatch chunks in parallel
    chunk_results: List[Dict[str, Any]] = []
    started_all = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {
            ex.submit(
                run_chunk,
                i, len(chunks), chunk, repo_dir, shared_context,
                args.timeout_minutes, custom_scan_instructions,
                args.mode, known_findings,
            ): i
            for i, chunk in enumerate(chunks)
        }
        for fut in concurrent.futures.as_completed(futures):
            idx = futures[fut]
            try:
                chunk_results.append(fut.result())
            except Exception as e:
                logger.error(f"[chunk {idx + 1}/{len(chunks)}] crashed: {e}")
                chunk_results.append({
                    'chunk_id': idx,
                    'label': chunk_label(chunks[idx]),
                    'files': [f.as_posix() for f in chunks[idx]],
                    'success': False,
                    'error': f"orchestrator exception: {e}",
                    'findings': [],
                    'elapsed_seconds': 0.0,
                })

    chunk_results.sort(key=lambda r: r['chunk_id'])
    total_elapsed = time.time() - started_all

    # Aggregate
    raw_findings: List[Dict[str, Any]] = []
    for r in chunk_results:
        raw_findings.extend(r['findings'])

    deduped = dedupe_findings(raw_findings)
    logger.info(f"merged {len(raw_findings)} raw findings → {len(deduped)} after dedup")

    # Hard-rule filter only (OAuth-friendly: no API key needed)
    findings_filter = FindingsFilter(
        use_hard_exclusions=True,
        use_claude_filtering=False,
    )
    ok, filtered, _stats = findings_filter.filter_findings(deduped, pr_context=None)
    if ok:
        kept = filtered['filtered_findings']
        excluded = filtered['excluded_findings']
        breakdown = filtered['analysis_summary'].get('exclusion_breakdown', {})
    else:
        kept, excluded, breakdown = deduped, [], {}

    succeeded = sum(1 for r in chunk_results if r['success'])
    output = {
        'repo': str(repo_dir),
        'total_elapsed_seconds': total_elapsed,
        'chunks_planned': len(chunks),
        'chunks_succeeded': succeeded,
        'chunks_failed': len(chunks) - succeeded,
        'raw_finding_count': len(raw_findings),
        'deduped_finding_count': len(deduped),
        'kept_finding_count': len(kept),
        'excluded_finding_count': len(excluded),
        'exclusion_breakdown': breakdown,
        'findings': kept,
        'excluded_findings': excluded,
        'chunk_results': [
            {k: v for k, v in r.items() if k != 'findings'}
            for r in chunk_results
        ],
    }

    Path(args.output).write_text(json.dumps(output, indent=2))
    logger.info(
        f"DONE in {total_elapsed:.0f}s — {succeeded}/{len(chunks)} chunks ok, "
        f"{len(kept)} findings → {args.output}"
    )

    high = sum(1 for f in kept if (f.get('severity') or '').upper() == 'HIGH')
    return 1 if high > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
