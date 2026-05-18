"""Security audit prompt templates."""


def get_full_codebase_audit_prompt(pr_data=None, custom_scan_instructions=None):
    """Generate full-codebase security audit prompt for Claude Code.

    Audits the entire repository at the current commit instead of only PR diff.

    Args:
        pr_data: Optional PR data dictionary for context (PR number, repo, author).
            When omitted (e.g. push/workflow_dispatch), only repo metadata is used.
        custom_scan_instructions: Optional custom security categories to append.

    Returns:
        Formatted prompt string.
    """
    if pr_data:
        context_lines = [
            f"- Pull Request: #{pr_data['number']} \"{pr_data.get('title', '')}\"",
            f"- Repository: {pr_data.get('head', {}).get('repo', {}).get('full_name', 'unknown')}",
            f"- Author: {pr_data.get('user', 'unknown')}",
            "",
            "Note: Although this run is associated with a PR, you must audit the ENTIRE repository at the current checkout, not just the PR diff.",
        ]
    else:
        context_lines = [
            "- Trigger: non-PR event (push, schedule, or manual run)",
            "- Audit scope: ENTIRE repository at the current checkout.",
        ]
    context_section = "\n".join(context_lines)

    custom_categories_section = ""
    if custom_scan_instructions:
        custom_categories_section = f"\n{custom_scan_instructions}\n"

    return f"""
You are a senior security engineer conducting a full-codebase security audit.

CONTEXT:
{context_section}

OBJECTIVE:
Perform a security-focused review of the ENTIRE codebase at the current checkout to identify HIGH-CONFIDENCE security vulnerabilities with real exploitation potential. This is not limited to recent changes — examine all source files in the repository.

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
- Remote code execution via deserialization
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

Phase 1 - Repository Mapping (Use file search tools):
- Enumerate the major source directories and entry points (servers, handlers, CLIs, jobs, IaC)
- Identify languages, frameworks, and security libraries in use
- Locate authentication, authorization, and input-handling layers

Phase 2 - Threat Surface Identification:
- Map all externally reachable endpoints and trust boundaries
- Identify privileged operations (file I/O, network, subprocess, eval, deserialization)
- Find all locations consuming user-controlled or third-party input

Phase 3 - Vulnerability Assessment:
- Trace data flow from untrusted sources to sensitive sinks across the whole repo
- Examine each privileged operation for the security categories above
- Verify each suspected issue against existing sanitization/validation patterns before reporting

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
Focus on HIGH and MEDIUM findings only. Better to miss some theoretical issues than flood the report with false positives. Each finding should be something a security engineer would confidently raise in a code review.

IMPORTANT EXCLUSIONS - DO NOT REPORT:
- Denial of Service (DOS) vulnerabilities or resource exhaustion attacks
- Secrets/credentials stored on disk (these are managed separately)
- Rate limiting concerns or service overload scenarios. Services do not need to implement rate limiting.
- Memory consumption or CPU exhaustion issues.
- Lack of input validation on non-security-critical fields. If there isn't a proven problem from a lack of input validation, don't report it.

Begin your analysis now. Use the repository exploration tools to walk the entire codebase, then report findings.

Your final reply must contain the JSON and nothing else. You should not reply again after outputting the JSON.
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
You are a senior security engineer conducting a security review of GitHub PR #{pr_data['number']}: "{pr_data['title']}"

CONTEXT:
- Repository: {pr_data.get('head', {}).get('repo', {}).get('full_name', 'unknown')}
- Author: {pr_data['user']}
- Files changed: {pr_data['changed_files']}
- Lines added: {pr_data['additions']}
- Lines deleted: {pr_data['deletions']}

Files modified:
{files_changed}{diff_section}

OBJECTIVE:
Identify exploitable security vulnerabilities reachable through any file modified in this PR. Focus on real, demonstrable issues — but do not artificially limit yourself to lines added in this PR. If a touched file (or a function/route/class it exports) contains a clear vulnerability, report it. Pre-existing bugs in changed files are still in scope because the PR is your trigger to look. Use Read/Grep tools to follow data flow into adjacent files (callers, helpers, configs) when needed to confirm exploitability.

CRITICAL INSTRUCTIONS:
1. PRIORITIZE TRUE POSITIVES: Report any vulnerability where the exploit path is clear from the code, even if it pre-existed in a touched file. Confidence floor is 0.6.
2. AVOID PURE STYLE NOISE: Skip findings that are merely about code style, naming, or theoretical concerns with no concrete exploit.
3. INCLUDE HARDCODED SECRETS: Hardcoded API keys, passwords, JWT keys, AWS credentials, database URLs with credentials, or any other secrets in source / config / test / markdown files MUST be reported. This codebase does not have GitHub secret scanning enabled, so this action is the primary defense.
4. INCLUDE WEAK CRYPTO: Weak ciphers, hardcoded IVs, insecure random, missing certificate validation, MD5/SHA1 used for password hashing.
5. AUTHORIZATION GAPS: Missing JWT/API-key checks on routes that touch wallets, payments, payouts, admin endpoints, or service-to-service APIs.
6. PII / FINANCIAL EXPOSURE: Logging of full PANs, OTPs, JWTs, refresh tokens, password hashes, full email addresses in error messages, or PII in CloudWatch logs.

SECURITY CATEGORIES TO EXAMINE:

**Input Validation Vulnerabilities:**
- SQL / NoSQL injection via unsanitized user input
- Command / shell injection in system calls or subprocesses
- XXE injection in XML parsing
- Server-Side Template Injection in templating engines
- Path traversal in file operations or S3 keys
- Open redirect with user-controlled URL

**Authentication & Authorization Issues:**
- Authentication bypass logic
- Privilege escalation paths (e.g. role check missing on admin route)
- Session management flaws
- JWT token vulnerabilities (alg=none, weak signing, missing iss/aud/exp validation, not verifying signature)
- Authorization logic bypasses (IDOR, missing ownership check on wallet/payout/order)

**Crypto & Secrets Management:**
- Hardcoded API keys, passwords, tokens, RSA private keys, signing keys, AWS credentials, payment-provider keys
- Weak cryptographic algorithms (MD5, SHA1 for passwords, DES, RC4)
- Improper key storage or management
- Cryptographic randomness issues (Math.random for security)
- Certificate validation bypass (rejectUnauthorized=false, NODE_TLS_REJECT_UNAUTHORIZED=0, InsecureSkipVerify)

**Injection & Code Execution:**
- Remote code execution via deserialization
- Pickle / cloudpickle injection in Python
- YAML deserialization vulnerabilities
- eval / new Function / vm.runInNewContext on user input
- XSS in web applications (reflected, stored, DOM-based, dangerouslySetInnerHTML with user data)
- Prototype pollution in JS/TS

**Data Exposure:**
- Sensitive data logging or storage (OTP codes, JWTs, refresh tokens, full email/phone, payment card numbers, account numbers)
- PII handling violations
- API endpoint data leakage (returning full user objects with hashed passwords / tokens)
- Debug information exposure (stack traces in production responses, verbose error messages with table names)
- CORS misconfiguration (origin: true, wildcard with credentials)

**Infrastructure & Config:**
- Insecure default values committed to .env / .tfvars / docker-compose
- Public S3 buckets, missing encryption-at-rest
- Overly permissive IAM policies (wildcards on Resource, Action: "*")
- Missing TLS, weak TLS settings
{custom_categories_section}
ANALYSIS METHODOLOGY:

Phase 1 - Repository Context Research (Use Read/Grep tools):
- Identify existing security frameworks and libraries in use (Passport, NestJS Guards, etc.)
- Look for established secure coding patterns in the codebase
- Examine existing sanitization and validation patterns
- Understand the project's auth model (look at any *.guard.ts, middleware/, auth/, *.strategy.ts)

Phase 2 - Comparative Analysis:
- For each modified file, identify what it exports and how it's invoked
- Compare against existing patterns to flag deviations
- Check whether new routes/handlers are protected by the same guards as their siblings
- Inspect whether secrets/keys appear in plaintext

Phase 3 - Vulnerability Assessment:
- Examine each modified file for security implications
- Trace data flow from user inputs to sensitive operations (DB writes, payments, wallet credit/debit, file system, network)
- Look for privilege boundaries being crossed unsafely
- Identify injection points and unsafe deserialization
- Open package.json / requirements.txt / pyproject.toml etc. when modified — flag pinned versions known to be vulnerable

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
- **HIGH**: Directly exploitable vulnerabilities leading to RCE, data breach, authentication bypass, fund theft, or hardcoded production secrets
- **MEDIUM**: Vulnerabilities requiring specific conditions but with significant impact, weak crypto, IDOR, sensitive data in logs
- **LOW**: Defense-in-depth issues, hardcoded test credentials, weak randomness for non-secret use, minor info disclosure

CONFIDENCE SCORING:
- 0.9-1.0: Certain exploit path identified
- 0.8-0.9: Clear vulnerability pattern with known exploitation methods
- 0.7-0.8: Suspicious pattern requiring specific conditions to exploit
- 0.6-0.7: Probable issue, exploitability depends on caller context — still report
- Below 0.6: Don't report (too speculative)

Report HIGH, MEDIUM, AND LOW findings. Hardcoded secrets should always be reported regardless of estimated impact.

LIMITED EXCLUSIONS - DO NOT REPORT:
- Pure DoS via algorithmic complexity unless the bound is trivially attacker-controlled and the service has no rate limiting in front of it
- Memory-corruption findings in non-C/C++ code (the runtime prevents them)
- Style-only or naming-only findings

REPORT THESE EVEN IF EXISTING:
- Hardcoded credentials, API keys, JWT signing keys, AWS keys, payment-provider keys, or service-to-service shared secrets in any file under a touched directory
- Missing authentication/authorization on a touched route
- Verbose error responses leaking stack traces or DB internals on a touched endpoint
- CORS origin: true / wildcard with credentials in any modified app bootstrap
- Logging of OTPs, full JWTs, refresh tokens, password hashes

Begin your analysis now. Use the repository exploration tools to understand the codebase context, then analyze the PR changes for security implications.

Your final reply must contain the JSON and nothing else. You should not reply again after outputting the JSON.
"""
