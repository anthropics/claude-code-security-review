"""Security audit prompt templates."""

import json as _json


def get_tenant_scope_audit_prompt(file_list, shared_context=None,
                                  known_findings=None,
                                  chunk_index=None, chunk_count=None):
    """Generate a tenant-scope / authorization-focused audit prompt.

    Use this prompt when the goal is to find more instances of missing
    ownership checks on DB queries and route handlers (IDOR, cross-tenant
    access). Skip the generic SQL/XSS/crypto categories — those should be
    covered by get_repo_audit_prompt in a prior pass.

    Args:
        file_list: Newline-joined "- path/to/file.ext" list of files
        shared_context: Optional repo-level orientation (CLAUDE.md etc.)
        known_findings: Optional list of finding dicts already discovered;
            included as anchors to help Claude pattern-match for similar bugs
            and to avoid re-reporting the same locations
        chunk_index: 0-based chunk index
        chunk_count: total chunk count

    Returns:
        Prompt string
    """
    chunk_header = ""
    if chunk_index is not None and chunk_count is not None:
        chunk_header = f"This is chunk {chunk_index + 1} of {chunk_count} of a tenant-scope-focused audit.\n\n"

    shared_context_section = ""
    if shared_context:
        shared_context_section = f"""
REPOSITORY CONTEXT (from CLAUDE.md / README.md / AGENTS.md):
```
{shared_context}
```
"""

    anchors_section = ""
    if known_findings:
        # Render each anchor compactly to save tokens
        rendered = []
        for f in known_findings:
            rendered.append({
                "file": f.get("file", ""),
                "line": f.get("line", 0),
                "category": f.get("category", ""),
                "description": (f.get("description") or "")[:600],
            })
        anchors_section = f"""
KNOWN FINDINGS FROM A PRIOR PASS (DO NOT RE-REPORT THESE EXACT LOCATIONS — use them as PATTERNS to search for SIMILAR bugs elsewhere):
```json
{_json.dumps(rendered, indent=2)}
```

These confirm the bug shape exists in this codebase. Your job is to find OTHER instances of the same shape.
"""

    return f"""
You are a senior application security engineer auditing a multi-tenant SaaS codebase for AUTHORIZATION-BYPASS bugs only.

{chunk_header}OBJECTIVE:
Find HIGH-CONFIDENCE missing-tenant-scope / missing-ownership-check vulnerabilities. Specifically:

1. **DB queries that act on a record by ID without scoping to the requester's user/tenant.**
   Example shape: `db.update(table).where(eq(table.id, paramId))` with NO additional `eq(table.userId, currentUser.id)` clause, where `paramId` came from request input.

2. **Route handlers that mutate/read a resource by URL/body parameter without verifying ownership.**
   Example shape: `app.get('/foo/:id', auth, async (req, res) => {{ const x = await storage.getFoo(req.params.id); res.json(x); }})` with no check that `x.ownerId === req.user.id`.

3. **Storage / service functions that accept a `userId?` parameter as optional but never use it in the query.**
   The optional userId is a code smell — if it's not enforced, callers think they're scoping when they aren't.

4. **Bulk operations** (delete, update, list) that filter by a non-tenant column (e.g. email, slug, externalId) instead of a (tenant_id, externalId) tuple.

5. **Trust-boundary mistakes**: client-supplied IDs trusted as authoritative when they should be looked up via a join with the session user's tenant.

FILES TO AUDIT IN THIS CHUNK:
{file_list}
{shared_context_section}{anchors_section}

CRITICAL INSTRUCTIONS:
1. **Scope**: Findings must be in the chunk's files. You may read other files for context (schema, middleware, session shape) but report only what's in-chunk.
2. **Confidence**: Only flag if you can name the exact route/function, the exact missing scope predicate, and a concrete cross-tenant exploit. >85% confidence floor.
3. **DO NOT re-report** the locations in the KNOWN FINDINGS list above. Find NEW instances.
4. **DO NOT report**: generic input validation, DOS, rate-limit, XSS, SQL injection, crypto, or any non-authorization issue. Stay laser-focused on tenant scope / IDOR / missing ownership checks.
5. **Read the schema first**: figure out which tables have a `userId` / `accountId` / `tenantId` column. A query that omits that column when it exists on the table is the bug shape.
6. **Trace through `storage.ts` carefully**: it's the data-access layer. Functions there often take a `userId` arg they never use, or filter by a public-ish column (email, slug) without tenant scoping.

ANALYSIS METHODOLOGY:

Phase 1 — Orient:
- Read `shared/schema.ts` (or equivalent) once to learn the tenant column names.
- Read `server/auth.ts` and the session/middleware files once to learn how the current user is attached to the request (e.g., `req.user.id`).

Phase 2 — Per file in this chunk:
- For storage/service files: list every exported function that runs a SELECT/UPDATE/DELETE/INSERT. For each, ask: "could a caller pass an ID belonging to another tenant and have the query succeed?"
- For route files: list every protected route. For each, ask: "what record does this touch, and does the handler verify the current user owns that record before acting?"

Phase 3 — Confirm:
- For each candidate, trace the call path from route handler → service → storage to confirm the missing scope is real and not enforced upstream.
- Reject candidates that are scoped via middleware, JOINed via tenant column, or where the resource is intentionally global (e.g. public reference data).

REQUIRED OUTPUT FORMAT (identical schema to the general audit so results merge cleanly):

{{
  "findings": [
    {{
      "file": "path/to/file.ts",
      "line": 42,
      "severity": "HIGH",
      "category": "authorization_bypass",
      "description": "Brief technical description naming the function/route, the missing scope predicate, and the table involved",
      "exploit_scenario": "Concrete cross-tenant attack: authenticated user A calls endpoint X with B's resource ID and accomplishes Y",
      "recommendation": "Add `eq(table.userId, currentUser.id)` to the WHERE clause / verify ownership before the operation",
      "confidence": 0.9
    }}
  ],
  "analysis_summary": {{
    "files_reviewed": 8,
    "high_severity": 1,
    "medium_severity": 0,
    "low_severity": 0,
    "review_completed": true
  }}
}}

FINAL REMINDER:
A clean report is fine. Many chunks will legitimately have zero findings — most files don't touch the data layer. Do not pad the output. Your final reply must contain ONLY the JSON object — no preamble, no explanation, no markdown fences. Do not reply again after outputting the JSON.
"""


def get_repo_audit_prompt(file_list, shared_context=None, custom_scan_instructions=None,
                          chunk_index=None, chunk_count=None):
    """Generate security audit prompt for a chunk of a whole-repo scan.

    Unlike get_security_audit_prompt (which is PR-diff shaped), this prompt
    asks Claude to audit a specific set of files within an already-checked-out
    repository. Claude must use its file-reading tools to examine the listed
    files; the file contents are NOT inlined in the prompt.

    Args:
        file_list: Newline-joined "- path/to/file.ext" list of files to audit
        shared_context: Optional repo-level context (e.g., concatenated
            CLAUDE.md / README.md / AGENTS.md) to orient Claude
        custom_scan_instructions: Optional extra instructions to append
        chunk_index: Optional 0-based chunk index for logging context
        chunk_count: Optional total chunk count

    Returns:
        Formatted prompt string
    """

    chunk_header = ""
    if chunk_index is not None and chunk_count is not None:
        chunk_header = f"This is chunk {chunk_index + 1} of {chunk_count} in a whole-repository security audit.\n\n"

    shared_context_section = ""
    if shared_context:
        shared_context_section = f"""
REPOSITORY CONTEXT (from CLAUDE.md / README.md / AGENTS.md):
```
{shared_context}
```

Use this context to understand the project's purpose, threat model, and conventions before auditing.
"""

    custom_categories_section = ""
    if custom_scan_instructions:
        custom_categories_section = f"\n{custom_scan_instructions}\n"

    return f"""
You are a senior security engineer conducting a focused security review of a portion of a codebase.

{chunk_header}OBJECTIVE:
Audit the files listed below for HIGH-CONFIDENCE security vulnerabilities. The repository is already checked out at your current working directory — read the files yourself using your file-reading tools. You may also read OTHER files in the repo (callers, helpers, schema definitions) to gain context, but findings you report must be located within the chunk's files.

FILES TO AUDIT IN THIS CHUNK:
{file_list}
{shared_context_section}
CRITICAL INSTRUCTIONS:
1. MINIMIZE FALSE POSITIVES: Only flag issues where you're >80% confident of actual exploitability.
2. AVOID NOISE: Skip theoretical issues, style concerns, or low-impact findings.
3. FOCUS ON IMPACT: Prioritize vulnerabilities that could lead to unauthorized access, data breaches, or system compromise.
4. SCOPE: Findings must be in the chunk's files. If you spot something elsewhere, ignore it — another chunk will cover it.
5. EXCLUSIONS — DO NOT report:
   - Denial of Service (DOS) / resource exhaustion / rate limiting concerns
   - Memory consumption or CPU exhaustion issues
   - Secrets/credentials stored on disk (handled separately)
   - Generic input validation without proven impact
   - Open redirect vulnerabilities
   - Memory safety issues in non-C/C++ code
   - Style, performance, or maintainability concerns

SECURITY CATEGORIES TO EXAMINE:

**Input Validation Vulnerabilities:**
- SQL injection via unsanitized user input
- Command injection in system calls or subprocesses
- XXE injection in XML parsing
- Template injection in templating engines
- NoSQL injection in database queries
- Path traversal in file operations

**Authentication & Authorization Issues:**
- Authentication bypass logic
- Privilege escalation paths
- Session management flaws
- JWT token vulnerabilities
- Authorization logic bypasses (missing tenant/user scoping on queries, IDOR)

**Crypto & Secrets Management:**
- Hardcoded API keys, passwords, or tokens
- Weak cryptographic algorithms or implementations
- Improper key storage or management
- Cryptographic randomness issues
- Certificate validation bypasses

**Injection & Code Execution:**
- Remote code execution via deserialization
- Pickle / YAML deserialization vulnerabilities
- Eval injection in dynamic code execution
- XSS vulnerabilities (reflected, stored, DOM-based)
- SSRF in server-side request handling

**Data Exposure:**
- Sensitive data logging or storage
- PII handling violations
- API endpoint data leakage (e.g., over-fetching, missing field filtering)
- Debug information exposure
{custom_categories_section}
ANALYSIS METHODOLOGY:

1. Skim the file list and infer the chunk's role in the system (routes? services? data layer? client UI?).
2. Read each file in the chunk. For files >40KB, use targeted reads (offset/limit) rather than reading wholesale — but ensure you cover all suspicious surfaces.
3. When a file calls into another module, follow it (Read or Grep) just deeply enough to confirm or refute a vulnerability.
4. Trace data flow from user/external inputs to sensitive sinks (SQL, shell, filesystem, HTTP, eval).
5. For each finding, verify exploitability by tracing the actual call path, not just pattern matching.

REQUIRED OUTPUT FORMAT:

You MUST output your findings as structured JSON with this exact schema:

{{
  "findings": [
    {{
      "file": "path/to/file.py",
      "line": 42,
      "severity": "HIGH",
      "category": "sql_injection",
      "description": "User input passed to SQL query without parameterization",
      "exploit_scenario": "Attacker could extract database contents by manipulating the 'search' parameter with SQL injection payloads like '1; DROP TABLE users--'",
      "recommendation": "Replace string formatting with parameterized queries using SQLAlchemy or equivalent",
      "confidence": 0.95
    }}
  ],
  "analysis_summary": {{
    "files_reviewed": 8,
    "high_severity": 1,
    "medium_severity": 0,
    "low_severity": 0,
    "review_completed": true
  }}
}}

SEVERITY GUIDELINES:
- **HIGH**: Directly exploitable vulnerabilities leading to RCE, data breach, or authentication bypass
- **MEDIUM**: Vulnerabilities requiring specific conditions but with significant impact
- **LOW**: Defense-in-depth issues or lower-impact vulnerabilities

CONFIDENCE SCORING:
- 0.9-1.0: Certain exploit path identified
- 0.8-0.9: Clear vulnerability pattern with known exploitation methods
- 0.7-0.8: Suspicious pattern requiring specific conditions to exploit
- Below 0.7: Don't report (too speculative)

FINAL REMINDER:
Better to miss theoretical issues than flood the report with false positives. Your final reply must contain ONLY the JSON object — no preamble, no explanation, no markdown fences. Do not reply again after outputting the JSON.
"""


def get_security_audit_prompt(pr_data, pr_diff=None, include_diff=True, custom_scan_instructions=None):
    """Generate security audit prompt for Claude Code.
    
    Args:
        pr_data: PR data dictionary from GitHub API
        pr_diff: Optional complete PR diff in unified format
        include_diff: Whether to include the diff in the prompt (default: True)
        custom_scan_instructions: Optional custom security categories to append
        
    Returns:
        Formatted prompt string
    """
    
    files_changed = "\n".join([f"- {f['filename']}" for f in pr_data['files']])
    
    # Add diff section if provided and include_diff is True
    diff_section = ""
    if pr_diff and include_diff:
        diff_section = f"""

PR DIFF CONTENT:
```
{pr_diff}
```

Review the complete diff above. This contains all code changes in the PR.
"""
    elif pr_diff and not include_diff:
        diff_section = """

NOTE: PR diff was omitted due to size constraints. Please use the file exploration tools to examine the specific files that were changed in this PR.
"""
    
    # Add custom security categories if provided
    custom_categories_section = ""
    if custom_scan_instructions:
        custom_categories_section = f"\n{custom_scan_instructions}\n"
    
    return f"""
You are a senior security engineer conducting a focused security review of GitHub PR #{pr_data['number']}: "{pr_data['title']}"

CONTEXT:
- Repository: {pr_data.get('head', {}).get('repo', {}).get('full_name', 'unknown')}
- Author: {pr_data['user']}
- Files changed: {pr_data['changed_files']}
- Lines added: {pr_data['additions']}
- Lines deleted: {pr_data['deletions']}

Files modified:
{files_changed}{diff_section}

OBJECTIVE:
Perform a security-focused code review to identify HIGH-CONFIDENCE security vulnerabilities that could have real exploitation potential. This is not a general code review - focus ONLY on security implications newly added by this PR. Do not comment on existing security concerns.

CRITICAL INSTRUCTIONS:
1. MINIMIZE FALSE POSITIVES: Only flag issues where you're >80% confident of actual exploitability
2. AVOID NOISE: Skip theoretical issues, style concerns, or low-impact findings
3. FOCUS ON IMPACT: Prioritize vulnerabilities that could lead to unauthorized access, data breaches, or system compromise
4. EXCLUSIONS: Do NOT report the following issue types:
   - Denial of Service (DOS) vulnerabilities, even if they allow service disruption
   - Secrets or sensitive data stored on disk (these are handled by other processes)
   - Rate limiting or resource exhaustion issues

SECURITY CATEGORIES TO EXAMINE:

**Input Validation Vulnerabilities:**
- SQL injection via unsanitized user input
- Command injection in system calls or subprocesses
- XXE injection in XML parsing
- Template injection in templating engines
- NoSQL injection in database queries
- Path traversal in file operations

**Authentication & Authorization Issues:**
- Authentication bypass logic
- Privilege escalation paths
- Session management flaws
- JWT token vulnerabilities
- Authorization logic bypasses

**Crypto & Secrets Management:**
- Hardcoded API keys, passwords, or tokens
- Weak cryptographic algorithms or implementations
- Improper key storage or management
- Cryptographic randomness issues
- Certificate validation bypasses

**Injection & Code Execution:**
- Remote code execution via deseralization
- Pickle injection in Python
- YAML deserialization vulnerabilities
- Eval injection in dynamic code execution
- XSS vulnerabilities in web applications (reflected, stored, DOM-based)

**Data Exposure:**
- Sensitive data logging or storage
- PII handling violations
- API endpoint data leakage
- Debug information exposure
{custom_categories_section}
Additional notes:
- Even if something is only exploitable from the local network, it can still be a HIGH severity issue

ANALYSIS METHODOLOGY:

Phase 1 - Repository Context Research (Use file search tools):
- Identify existing security frameworks and libraries in use
- Look for established secure coding patterns in the codebase
- Examine existing sanitization and validation patterns
- Understand the project's security model and threat model

Phase 2 - Comparative Analysis:
- Compare new code changes against existing security patterns
- Identify deviations from established secure practices
- Look for inconsistent security implementations
- Flag code that introduces new attack surfaces

Phase 3 - Vulnerability Assessment:
- Examine each modified file for security implications
- Trace data flow from user inputs to sensitive operations
- Look for privilege boundaries being crossed unsafely
- Identify injection points and unsafe deserialization

REQUIRED OUTPUT FORMAT:

You MUST output your findings as structured JSON with this exact schema:

{{
  "findings": [
    {{
      "file": "path/to/file.py",
      "line": 42,
      "severity": "HIGH",
      "category": "sql_injection",
      "description": "User input passed to SQL query without parameterization",
      "exploit_scenario": "Attacker could extract database contents by manipulating the 'search' parameter with SQL injection payloads like '1; DROP TABLE users--'",
      "recommendation": "Replace string formatting with parameterized queries using SQLAlchemy or equivalent",
      "confidence": 0.95
    }}
  ],
  "analysis_summary": {{
    "files_reviewed": 8,
    "high_severity": 1,
    "medium_severity": 0,
    "low_severity": 0,
    "review_completed": true,
  }}
}}

SEVERITY GUIDELINES:
- **HIGH**: Directly exploitable vulnerabilities leading to RCE, data breach, or authentication bypass
- **MEDIUM**: Vulnerabilities requiring specific conditions but with significant impact
- **LOW**: Defense-in-depth issues or lower-impact vulnerabilities

CONFIDENCE SCORING:
- 0.9-1.0: Certain exploit path identified, tested if possible
- 0.8-0.9: Clear vulnerability pattern with known exploitation methods  
- 0.7-0.8: Suspicious pattern requiring specific conditions to exploit
- Below 0.7: Don't report (too speculative)

FINAL REMINDER:
Focus on HIGH and MEDIUM findings only. Better to miss some theoretical issues than flood the report with false positives. Each finding should be something a security engineer would confidently raise in a PR review.

IMPORTANT EXCLUSIONS - DO NOT REPORT:
- Denial of Service (DOS) vulnerabilities or resource exhaustion attacks
- Secrets/credentials stored on disk (these are managed separately)
- Rate limiting concerns or service overload scenarios. Services do not need to implement rate limiting.
- Memory consumption or CPU exhaustion issues.
- Lack of input validation on non-security-critical fields. If there isn't a proven problem from a lack of input validation, don't report it.

Begin your analysis now. Use the repository exploration tools to understand the codebase context, then analyze the PR changes for security implications.

Your final reply must contain the JSON and nothing else. You should not reply again after outputting the JSON.
"""