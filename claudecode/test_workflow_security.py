"""Tests for deterministic workflow security checks."""

from claudecode.workflow_security import find_unpinned_github_actions


def test_find_unpinned_github_actions_reports_mutable_refs():
    diff = """diff --git a/.github/workflows/security.yml b/.github/workflows/security.yml
new file mode 100644
--- /dev/null
+++ b/.github/workflows/security.yml
@@ -0,0 +1,8 @@
+name: Security
+jobs:
+  scan:
+    steps:
+      - uses: actions/checkout@v4
+      - uses: anthropics/claude-code-security-review@main
"""

    findings = find_unpinned_github_actions(diff)

    assert [finding["line"] for finding in findings] == [5, 6]
    assert findings[0]["file"] == ".github/workflows/security.yml"
    assert findings[0]["category"] == "unpinned_github_action"
    assert "actions/checkout@v4" in findings[0]["description"]
    assert findings[1]["severity"] == "MEDIUM"


def test_find_unpinned_github_actions_handles_quotes_and_inline_comments():
    diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -7,3 +7,6 @@
 jobs:
   lint:
     steps:
+      - name: Checkout
+        uses: "actions/checkout@v4" # trusted action
+      - uses: 'actions/setup-node@v4'
"""

    findings = find_unpinned_github_actions(diff)

    assert [finding["line"] for finding in findings] == [11, 12]
    assert "actions/checkout@v4" in findings[0]["description"]
    assert "actions/setup-node@v4" in findings[1]["description"]


def test_find_unpinned_github_actions_reports_reusable_workflows():
    diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1,2 +1,4 @@
 name: CI
 jobs:
+  shared:
+    uses: org/reusable/.github/workflows/ci.yml@main
"""

    findings = find_unpinned_github_actions(diff)

    assert len(findings) == 1
    assert findings[0]["line"] == 4
    assert (
        "org/reusable/.github/workflows/ci.yml@main"
        in findings[0]["description"]
    )


def test_find_unpinned_github_actions_ignores_full_sha_and_local_actions():
    pinned_sha = "a" * 40
    diff = f"""diff --git a/.github/workflows/ci.yaml b/.github/workflows/ci.yaml
--- a/.github/workflows/ci.yaml
+++ b/.github/workflows/ci.yaml
@@ -10,3 +10,7 @@
+      - uses: actions/checkout@{pinned_sha}
+      - uses: ./actions/setup
+      - uses: docker://alpine:3.20
+      - uses: owner/action/path@{pinned_sha}
"""

    assert find_unpinned_github_actions(diff) == []


def test_find_unpinned_github_actions_only_checks_added_workflow_lines():
    diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -20,4 +20,4 @@
-      - uses: actions/setup-python@v5
       - name: unchanged
         run: echo ok
diff --git a/docs/example.yml b/docs/example.yml
--- a/docs/example.yml
+++ b/docs/example.yml
@@ -1,2 +1,3 @@
+      - uses: actions/checkout@v4
"""

    assert find_unpinned_github_actions(diff) == []
