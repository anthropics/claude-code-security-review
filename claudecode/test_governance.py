# Tests for governance policy integration.

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from claudecode.governance import (
    GovernancePolicy,
    load_governance_policy,
    apply_severity_overrides,
    apply_custom_rules,
    format_governance_prompt_section,
    _extract_added_lines,
    _matches_any_path,
)


SAMPLE_POLICY = {
    "governance": {
        "name": "org-security-policy",
        "severity_overrides": [
            {
                "pattern": "eval\\(",
                "context": "user_input",
                "severity": "critical",
            },
            {
                "pattern": "subprocess\\.call",
                "context": "hardcoded_args",
                "severity": "low",
            },
        ],
        "agent_governance": {
            "require_tool_allowlist": True,
            "flag_unrestricted_agents": True,
            "require_audit_trail": True,
        },
        "custom_rules": [
            {
                "name": "no-raw-sql-in-controllers",
                "pattern": "execute\\(.*SELECT|INSERT|UPDATE|DELETE",
                "paths": ["src/controllers/**", "src/api/**"],
                "severity": "high",
                "message": "Use ORM methods instead of raw SQL in API controllers",
            },
            {
                "name": "no-eval",
                "pattern": "eval\\(",
                "paths": [],
                "severity": "critical",
                "message": "Do not use eval() in any code",
            },
        ],
    }
}


class TestLoadGovernancePolicy:
    # Test governance policy loading.

    def test_load_valid_policy(self, tmp_path):
        policy_file = tmp_path / ".github" / "governance-policy.yaml"
        policy_file.parent.mkdir(parents=True)
        policy_file.write_text(yaml.dump(SAMPLE_POLICY))

        policy = load_governance_policy(policy_file)

        assert policy is not None
        assert policy.name == "org-security-policy"
        assert len(policy.severity_overrides) == 2
        assert len(policy.custom_rules) == 2
        assert policy.agent_governance["require_tool_allowlist"] is True

    def test_load_missing_file(self, tmp_path):
        policy_file = tmp_path / "nonexistent.yaml"
        policy = load_governance_policy(policy_file)
        assert policy is None

    def test_load_invalid_yaml(self, tmp_path):
        policy_file = tmp_path / "bad.yaml"
        policy_file.write_text(": : : invalid yaml [[[")

        policy = load_governance_policy(policy_file)
        assert policy is None

    def test_load_empty_file(self, tmp_path):
        policy_file = tmp_path / "empty.yaml"
        policy_file.write_text("")

        policy = load_governance_policy(policy_file)
        assert policy is None

    def test_load_policy_without_governance_key(self, tmp_path):
        # Policy file with rules at top level (no 'governance' wrapper).
        raw = {
            "name": "direct-policy",
            "severity_overrides": [
                {"pattern": "eval\\(", "severity": "critical"},
            ],
            "custom_rules": [],
        }
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(yaml.dump(raw))

        policy = load_governance_policy(policy_file)
        assert policy is not None
        assert policy.name == "direct-policy"
        assert len(policy.severity_overrides) == 1

    def test_load_policy_filters_invalid_overrides(self, tmp_path):
        raw = {
            "governance": {
                "name": "test",
                "severity_overrides": [
                    {"pattern": "valid", "severity": "high"},
                    {"no_pattern": True},  # Missing pattern
                    {"pattern": "missing_severity"},  # Missing severity
                ],
                "custom_rules": [],
            }
        }
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(yaml.dump(raw))

        policy = load_governance_policy(policy_file)
        assert policy is not None
        assert len(policy.severity_overrides) == 1

    def test_load_policy_filters_invalid_rules(self, tmp_path):
        raw = {
            "governance": {
                "name": "test",
                "severity_overrides": [],
                "custom_rules": [
                    {"name": "valid", "pattern": "eval\\(", "severity": "high", "message": "no eval"},
                    {"name": "no-pattern", "severity": "high"},  # Missing pattern
                    {"name": "no-severity", "pattern": "foo"},  # Missing severity
                ],
            }
        }
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(yaml.dump(raw))

        policy = load_governance_policy(policy_file)
        assert policy is not None
        assert len(policy.custom_rules) == 1

    def test_load_policy_with_null_sections(self, tmp_path):
        raw = {
            "governance": {
                "name": "minimal",
                "severity_overrides": None,
                "custom_rules": None,
                "agent_governance": None,
            }
        }
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(yaml.dump(raw))

        policy = load_governance_policy(policy_file)
        assert policy is not None
        assert policy.severity_overrides == []
        assert policy.custom_rules == []
        assert policy.agent_governance == {}


class TestApplySeverityOverrides:
    # Test severity override application.

    def _make_policy(self, overrides):
        return GovernancePolicy(severity_overrides=overrides)

    def test_override_matches_pattern(self):
        policy = self._make_policy([
            {"pattern": "eval\\(", "severity": "CRITICAL"},
        ])
        findings = [
            {"file": "app.py", "severity": "MEDIUM", "description": "Use of eval() on user input"},
        ]

        result = apply_severity_overrides(findings, policy)
        assert result[0]["severity"] == "CRITICAL"
        assert result[0]["original_severity"] == "MEDIUM"
        assert result[0]["governance_override"] is True

    def test_override_with_context(self):
        policy = self._make_policy([
            {"pattern": "eval\\(", "context": "user_input", "severity": "CRITICAL"},
        ])

        # Match: description contains both pattern and context
        findings = [
            {"file": "app.py", "severity": "MEDIUM", "description": "eval() with user_input"},
        ]
        result = apply_severity_overrides(findings, policy)
        assert result[0]["severity"] == "CRITICAL"

    def test_override_context_no_match(self):
        policy = self._make_policy([
            {"pattern": "eval\\(", "context": "user_input", "severity": "CRITICAL"},
        ])

        # No match: pattern matches but context does not
        findings = [
            {"file": "test.py", "severity": "HIGH", "description": "eval() on constant"},
        ]
        result = apply_severity_overrides(findings, policy)
        assert result[0]["severity"] == "HIGH"  # Unchanged
        assert "governance_override" not in result[0]

    def test_no_overrides(self):
        policy = self._make_policy([])
        findings = [{"file": "a.py", "severity": "HIGH", "description": "issue"}]
        result = apply_severity_overrides(findings, policy)
        assert result[0]["severity"] == "HIGH"

    def test_first_matching_rule_wins(self):
        policy = self._make_policy([
            {"pattern": "eval", "severity": "CRITICAL"},
            {"pattern": "eval", "severity": "LOW"},
        ])
        findings = [{"file": "a.py", "severity": "MEDIUM", "description": "eval() call"}]
        result = apply_severity_overrides(findings, policy)
        assert result[0]["severity"] == "CRITICAL"

    def test_invalid_regex_in_override_skipped(self):
        policy = self._make_policy([
            {"pattern": "[invalid(", "severity": "CRITICAL"},
        ])
        findings = [{"file": "a.py", "severity": "HIGH", "description": "test"}]
        result = apply_severity_overrides(findings, policy)
        assert result[0]["severity"] == "HIGH"  # Unchanged

    def test_override_does_not_mutate_original(self):
        policy = self._make_policy([
            {"pattern": "eval", "severity": "CRITICAL"},
        ])
        original = {"file": "a.py", "severity": "MEDIUM", "description": "eval()"}
        findings = [original]
        result = apply_severity_overrides(findings, policy)
        assert original["severity"] == "MEDIUM"  # Original unchanged
        assert result[0]["severity"] == "CRITICAL"


class TestApplyCustomRules:
    # Test custom rule application against diffs.

    def _make_policy(self, rules):
        return GovernancePolicy(custom_rules=rules)

    def test_rule_matches_added_line(self):
        policy = self._make_policy([
            {
                "name": "no-eval",
                "pattern": "eval\\(",
                "paths": [],
                "severity": "CRITICAL",
                "message": "Do not use eval()",
            },
        ])
        diff = """diff --git a/app.py b/app.py
@@ -1,3 +1,5 @@
 def process(data):
-    return data
+    result = eval(data)
+    return result
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 1
        assert findings[0]["file"] == "app.py"
        assert findings[0]["severity"] == "CRITICAL"
        assert findings[0]["category"] == "governance_policy"
        assert findings[0]["governance_rule"] == "no-eval"

    def test_rule_with_path_filter_match(self):
        policy = self._make_policy([
            {
                "name": "no-raw-sql",
                "pattern": "execute\\(",
                "paths": ["src/controllers/**"],
                "severity": "HIGH",
                "message": "No raw SQL in controllers",
            },
        ])
        diff = """diff --git a/src/controllers/user.py b/src/controllers/user.py
@@ -1,3 +1,4 @@
 def get_user(user_id):
+    cursor.execute("SELECT * FROM users WHERE id = " + user_id)
     return user
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 1
        assert findings[0]["file"] == "src/controllers/user.py"

    def test_rule_with_path_filter_no_match(self):
        policy = self._make_policy([
            {
                "name": "no-raw-sql",
                "pattern": "execute\\(",
                "paths": ["src/controllers/**"],
                "severity": "HIGH",
                "message": "No raw SQL in controllers",
            },
        ])
        diff = """diff --git a/tests/test_user.py b/tests/test_user.py
@@ -1,3 +1,4 @@
 def test_get_user():
+    cursor.execute("SELECT * FROM users")
     assert True
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 0  # Path doesn't match

    def test_no_match_on_deleted_lines(self):
        policy = self._make_policy([
            {
                "name": "no-eval",
                "pattern": "eval\\(",
                "paths": [],
                "severity": "HIGH",
                "message": "No eval",
            },
        ])
        diff = """diff --git a/app.py b/app.py
@@ -1,3 +1,2 @@
 def process(data):
-    result = eval(data)
     return data
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 0  # Only deleted, not added

    def test_empty_diff(self):
        policy = self._make_policy([
            {"name": "test", "pattern": "eval", "paths": [], "severity": "HIGH", "message": "msg"},
        ])
        findings = apply_custom_rules("", policy)
        assert len(findings) == 0

    def test_no_rules(self):
        policy = self._make_policy([])
        findings = apply_custom_rules("diff --git a/test.py b/test.py\n+eval()", policy)
        assert len(findings) == 0

    def test_invalid_regex_in_rule_skipped(self):
        policy = self._make_policy([
            {"name": "bad-regex", "pattern": "[invalid(", "paths": [], "severity": "HIGH", "message": "msg"},
        ])
        diff = """diff --git a/app.py b/app.py
@@ -1,2 +1,3 @@
 def f():
+    x = 1
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 0

    def test_one_finding_per_rule_per_file(self):
        policy = self._make_policy([
            {"name": "no-eval", "pattern": "eval\\(", "paths": [], "severity": "HIGH", "message": "msg"},
        ])
        diff = """diff --git a/app.py b/app.py
@@ -1,2 +1,4 @@
 def f():
+    x = eval("1")
+    y = eval("2")
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 1  # One per rule per file

    def test_multiple_files_multiple_rules(self):
        policy = self._make_policy([
            {"name": "no-eval", "pattern": "eval\\(", "paths": [], "severity": "HIGH", "message": "no eval"},
            {"name": "no-exec", "pattern": "exec\\(", "paths": [], "severity": "HIGH", "message": "no exec"},
        ])
        diff = """diff --git a/a.py b/a.py
@@ -1,2 +1,3 @@
 def f():
+    eval("x")
diff --git a/b.py b/b.py
@@ -1,2 +1,3 @@
 def g():
+    exec("y")
"""
        findings = apply_custom_rules(diff, policy)
        assert len(findings) == 2


class TestExtractAddedLines:
    # Test diff line extraction.

    def test_basic_extraction(self):
        section = """diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1,3 +1,5 @@
 line1
+added_line_1
 line2
+added_line_2
"""
        lines = _extract_added_lines(section)
        assert len(lines) == 2
        assert lines[0] == (2, "added_line_1")
        assert lines[1] == (4, "added_line_2")

    def test_no_added_lines(self):
        section = """diff --git a/test.py b/test.py
@@ -1,3 +1,2 @@
 line1
-removed_line
 line2
"""
        lines = _extract_added_lines(section)
        assert len(lines) == 0


class TestMatchesAnyPath:
    # Test path glob matching.

    def test_simple_glob(self):
        assert _matches_any_path("src/controllers/user.py", ["src/controllers/*.py"])

    def test_double_star_glob(self):
        assert _matches_any_path("src/controllers/v2/user.py", ["src/controllers/**"])

    def test_no_match(self):
        assert not _matches_any_path("tests/test_user.py", ["src/controllers/**"])

    def test_empty_patterns(self):
        assert not _matches_any_path("anything.py", [])

    def test_multiple_patterns(self):
        assert _matches_any_path("src/api/routes.py", ["src/controllers/**", "src/api/**"])


class TestFormatGovernancePromptSection:
    # Test prompt section generation.

    def test_full_policy(self):
        policy = GovernancePolicy(
            name="test-policy",
            severity_overrides=[
                {"pattern": "eval\\(", "context": "user_input", "severity": "CRITICAL"},
            ],
            custom_rules=[
                {"name": "no-sql", "pattern": "execute", "paths": ["src/api/**"], "severity": "HIGH", "message": "No raw SQL"},
            ],
            agent_governance={
                "require_tool_allowlist": True,
                "flag_unrestricted_agents": True,
                "require_audit_trail": True,
            },
        )

        result = format_governance_prompt_section(policy)
        assert "ORGANIZATIONAL GOVERNANCE POLICY" in result
        assert "test-policy" in result
        assert "Severity Overrides" in result
        assert "eval\\(" in result
        assert "Custom Governance Rules" in result
        assert "no-sql" in result
        assert "Agent Governance Requirements" in result
        assert "tool allowlist" in result

    def test_empty_policy(self):
        policy = GovernancePolicy(name="empty")
        result = format_governance_prompt_section(policy)
        assert "ORGANIZATIONAL GOVERNANCE POLICY" in result
        assert "empty" in result
        assert "Severity Overrides" not in result
        assert "Custom Governance Rules" not in result

    def test_policy_without_name(self):
        policy = GovernancePolicy()
        result = format_governance_prompt_section(policy)
        assert "ORGANIZATIONAL GOVERNANCE POLICY" in result


class TestGovernanceIntegration:
    # Integration tests for governance in the main audit flow.

    @patch('pathlib.Path.cwd')
    @patch('claudecode.github_action_audit.get_security_audit_prompt')
    @patch('claudecode.github_action_audit.FindingsFilter')
    @patch('claudecode.github_action_audit.SimpleClaudeRunner')
    @patch('claudecode.github_action_audit.GitHubActionClient')
    @patch('claudecode.github_action_audit.load_governance_policy')
    def test_main_with_governance_policy(self, mock_load_gov, mock_client_class,
                                          mock_runner_class, mock_filter_class,
                                          mock_prompt_func, mock_cwd, capsys):
        # Test main function with governance policy loaded.
        from claudecode.github_action_audit import main

        # Setup governance policy
        mock_load_gov.return_value = GovernancePolicy(
            name="test-policy",
            severity_overrides=[
                {"pattern": "eval\\(", "severity": "CRITICAL"},
            ],
            custom_rules=[],
        )

        # Setup mocks
        mock_client = Mock()
        mock_client.get_pr_data.return_value = {
            'number': 123, 'title': 'Test PR', 'body': 'Description',
        }
        mock_client.get_pr_diff.return_value = "diff content"
        mock_client._is_excluded.return_value = False
        mock_client_class.return_value = mock_client

        findings = [
            {'file': 'app.py', 'line': 10, 'severity': 'MEDIUM', 'description': 'Use of eval() on input'},
        ]

        mock_runner = Mock()
        mock_runner.validate_claude_available.return_value = (True, "")
        mock_runner.run_security_audit.return_value = (
            True, "", {'findings': findings, 'analysis_summary': {}}
        )
        mock_runner_class.return_value = mock_runner

        mock_filter = Mock()
        mock_filter.filter_findings.return_value = (
            True,
            {'filtered_findings': findings, 'excluded_findings': [], 'analysis_summary': {}},
            Mock(),
        )
        mock_filter_class.return_value = mock_filter

        mock_prompt_func.return_value = "prompt"
        mock_cwd.return_value = Path('/tmp/repo')

        with patch.dict(os.environ, {
            'GITHUB_REPOSITORY': 'owner/repo',
            'PR_NUMBER': '123',
            'GITHUB_TOKEN': 'test-token',
        }):
            with pytest.raises(SystemExit):
                main()

            captured = capsys.readouterr()
            output = json.loads(captured.out)

            assert 'governance_summary' in output
            assert output['governance_summary']['policy_name'] == 'test-policy'
            # The finding should have its severity overridden
            assert output['findings'][0]['severity'] == 'CRITICAL'
            assert output['findings'][0]['governance_override'] is True

    @patch('pathlib.Path.cwd')
    @patch('claudecode.github_action_audit.get_security_audit_prompt')
    @patch('claudecode.github_action_audit.FindingsFilter')
    @patch('claudecode.github_action_audit.SimpleClaudeRunner')
    @patch('claudecode.github_action_audit.GitHubActionClient')
    @patch('claudecode.github_action_audit.load_governance_policy')
    def test_main_without_governance_policy(self, mock_load_gov, mock_client_class,
                                             mock_runner_class, mock_filter_class,
                                             mock_prompt_func, mock_cwd, capsys):
        # Test main function without governance policy (default behavior).
        from claudecode.github_action_audit import main

        mock_load_gov.return_value = None

        mock_client = Mock()
        mock_client.get_pr_data.return_value = {
            'number': 123, 'title': 'Test PR', 'body': 'Description',
        }
        mock_client.get_pr_diff.return_value = "diff content"
        mock_client._is_excluded.return_value = False
        mock_client_class.return_value = mock_client

        mock_runner = Mock()
        mock_runner.validate_claude_available.return_value = (True, "")
        mock_runner.run_security_audit.return_value = (
            True, "", {'findings': [], 'analysis_summary': {}}
        )
        mock_runner_class.return_value = mock_runner

        mock_filter = Mock()
        mock_filter.filter_findings.return_value = (
            True,
            {'filtered_findings': [], 'excluded_findings': [], 'analysis_summary': {}},
            Mock(),
        )
        mock_filter_class.return_value = mock_filter

        mock_prompt_func.return_value = "prompt"
        mock_cwd.return_value = Path('/tmp/repo')

        with patch.dict(os.environ, {
            'GITHUB_REPOSITORY': 'owner/repo',
            'PR_NUMBER': '123',
            'GITHUB_TOKEN': 'test-token',
        }):
            with pytest.raises(SystemExit):
                main()

            captured = capsys.readouterr()
            output = json.loads(captured.out)

            assert 'governance_summary' not in output
