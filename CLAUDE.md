# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository purpose

This repo ships **two** things that share the same security-audit logic:

1. A **GitHub composite Action** (`action.yml`) that runs on PRs, invokes the `claude` CLI to perform a security review, filters findings, and posts review comments.
2. A **`/security-review` slash command** (`.claude/commands/security-review.md`) that performs the equivalent review locally inside Claude Code.

The Python package under `claudecode/` is the engine for path 1. Path 2 is a single markdown prompt file.

## Common commands

```bash
# Python unit tests (run from repo root — pytest.ini's testpaths=tests is wrong;
# the tests actually live in claudecode/ and the README's invocation is canonical)
PYTHONPATH=. pytest claudecode -v

# Single test file / single test
PYTHONPATH=. pytest claudecode/test_findings_filter.py -v
PYTHONPATH=. pytest claudecode/test_main_function.py::TestClass::test_name -v

# JS/Bun tests for the PR-comment script
cd scripts && bun install && bun test

# Run the audit locally against a real PR (clones into ~/code/audit by default)
ANTHROPIC_API_KEY=... GITHUB_TOKEN=... python -m claudecode.evals.run_eval owner/repo#123 --verbose
```

The `claudecode` package imports itself as `from claudecode.x import y` (absolute imports), so it must be run with the repo root on `PYTHONPATH` — never `cd claudecode && python ...`.

## Architecture

The audit runs as a **subprocess shelling out to the `claude` CLI**, not via the Anthropic SDK. The SDK is only used for the secondary false-positive filter pass.

End-to-end flow when the GitHub Action fires (`action.yml` → `claudecode/github_action_audit.py:main`):

1. **Cache gate** (`action.yml`): `actions/cache` with key `claudecode-<repo>-pr-<num>-<sha>` plus a `.claudecode-marker/marker.json` file. If the marker exists from a prior run, the audit is skipped to avoid duplicate findings on the same SHA. `run-every-commit: true` bypasses this. The marker is written *before* the scan ("reservation") to prevent concurrent runs.
2. **PR fetch** (`GitHubActionClient`): pulls PR metadata, file list, and unified diff via the GitHub REST API. Filters out `EXCLUDE_DIRECTORIES` and files marked `@generated`.
3. **Prompt construction** (`prompts.py:get_security_audit_prompt`): builds a single large prompt containing PR metadata, file list, and the full diff. If `custom_scan_instructions` (from `CUSTOM_SECURITY_SCAN_INSTRUCTIONS` file) is set, it's appended.
4. **Claude CLI invocation** (`SimpleClaudeRunner.run_security_audit`): runs `claude --output-format json --model <DEFAULT_CLAUDE_MODEL> --disallowed-tools 'Bash(ps:*)'` with the prompt on **stdin** (not argv — the prompt routinely exceeds `ARG_MAX`). Retries up to 3 times. If Claude returns `"Prompt is too long"`, the caller retries once with `include_diff=False` so Claude must use file-exploration tools instead of reading the diff inline.
5. **Two-stage filtering** (`findings_filter.py:FindingsFilter`):
   - **Hard rules** (`HardExclusionRules`): regex-based exclusions for known-noisy categories (DOS, rate-limiting, resource leaks, open redirect, regex injection). Memory-safety findings are excluded *unless* the file extension is `.c/.cc/.cpp/.h`. SSRF findings are excluded *if* the file is `.html`. Findings in `.md` files are always dropped.
   - **Claude API filter** (`ClaudeAPIClient`): each surviving finding is sent one-at-a-time to the Anthropic SDK for a keep/exclude decision with a confidence score. Custom filtering rules (from `FALSE_POSITIVE_FILTERING_INSTRUCTIONS` file) are concatenated into this prompt.
   - A final pass re-applies `EXCLUDE_DIRECTORIES` to the per-finding `file` paths (the diff filter only catches files in the diff header, not findings Claude attributes elsewhere).
6. **Output**: full JSON written to stdout → captured into `claudecode-results.json` by the action shell. The action then runs `scripts/comment-pr-findings.js` (Node, uses `gh` CLI, **not** `@actions/github`) to post review comments inline on the PR.

### Key invariants when editing

- **Two model configs exist**: `DEFAULT_CLAUDE_MODEL` in `claudecode/constants.py` (used for both the CLI subprocess and the filter API client) reads from `CLAUDE_MODEL` env. `action.yml` exposes this as the `claude-model` input. The filter client also hard-codes `claude-3-5-haiku-20241022` for its `validate_api_access` ping — leave that alone, it's intentionally cheap.
- **Exit codes signal severity**: `main()` exits `EXIT_GENERAL_ERROR (1)` if any HIGH-severity finding survives filtering, else `EXIT_SUCCESS (0)`. The action shell ignores non-zero exits and parses the JSON anyway, so changing exit semantics will not fail CI but may surprise local users.
- **The `result` field is unwrapped**: `_extract_security_findings` only accepts the Claude Code wrapper format (`{type, subtype, result: "<json string>"}`); a bare `{findings: [...]}` is silently dropped. The audit prompt's "output JSON only" instruction is load-bearing.
- **Prompt-size fallback path**: when retrying without the diff, the prompt tells Claude to use file-exploration tools — this only works because the action checks out the PR head ref (`fetch-depth: 2`) into the runner's workspace. Don't break that checkout step.

### What lives where

- `claudecode/github_action_audit.py` — main entrypoint, GitHub client, Claude CLI runner
- `claudecode/prompts.py` — the audit prompt (load-bearing; small wording changes affect false-positive rate)
- `claudecode/findings_filter.py` — two-stage filter (regex rules + Claude API)
- `claudecode/claude_api_client.py` — thin Anthropic SDK wrapper used only by the filter
- `claudecode/json_parser.py` — tolerant JSON extraction (handles markdown-fenced, trailing-text Claude output)
- `claudecode/evals/` — local PR evaluation harness (clones repo, runs the audit in a worktree)
- `scripts/comment-pr-findings.js` — Node script that posts findings as PR review comments via `gh api`
- `.claude/commands/security-review.md` — the slash-command equivalent of the action; keep in sync with `prompts.py` when changing audit semantics
- `docs/`, `examples/` — user-facing docs for `false-positive-filtering-instructions` and `custom-security-scan-instructions` action inputs

## Conventions

- All third-party `uses:` in workflows and `action.yml` are pinned to commit SHAs (with a `# vX.Y.Z` comment). Preserve this when adding steps.
- The action is **not hardened against prompt injection** — see the warning in README.md. Don't add features that grant the audited code more authority over the runner.
