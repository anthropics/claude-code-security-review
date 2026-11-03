"""Tests for LLM filtering through the Copilot CLI and its integration with FindingsFilter."""

from unittest.mock import MagicMock

from copilot_review.copilot_filter_client import CopilotFilterClient
from copilot_review.findings_filter import FindingsFilter, HardExclusionRules

FINDINGS = [
    {'file': 'src/a.c', 'line': 3, 'severity': 'HIGH', 'category': 'overflow', 'description': 'memcpy overflow'},
    {'file': 'src/b.c', 'line': 9, 'severity': 'MEDIUM', 'category': 'authz', 'description': 'missing check'},
]


def runner_returning(success, error, result):
    runner = MagicMock()
    runner.run.return_value = (success, error, result)
    return runner


class TestFilterClient:
    def test_no_findings_makes_no_call(self, tmp_path):
        runner = runner_returning(True, '', {})
        ok, decisions, err = CopilotFilterClient(runner, tmp_path).analyze_findings([])
        assert ok and decisions == {} and err == ''
        runner.run.assert_not_called()

    def test_decisions_are_keyed_by_index(self, tmp_path):
        result = {'decisions': [
            {'index': 1, 'keep_finding': False, 'confidence_score': 2},
            {'index': 0, 'keep_finding': True, 'confidence_score': 9},
            {'index': 7, 'keep_finding': False},      # out of range, ignored
            {'index': 'x'},                            # invalid, ignored
            'garbage',
        ]}
        runner = runner_returning(True, '', result)
        ok, decisions, _ = CopilotFilterClient(runner, tmp_path).analyze_findings(FINDINGS, {'pr_number': 5})
        assert ok and set(decisions) == {0, 1}
        assert decisions[1]['keep_finding'] is False

    def test_prompt_lists_findings_and_result_file(self, tmp_path):
        runner = runner_returning(True, '', {'decisions': []})
        CopilotFilterClient(runner, tmp_path).analyze_findings(
            FINDINGS, {'repo_name': 'g/p', 'pr_number': 5, 'title': 'T'}, custom_filtering_instructions='CUSTOM RULES')
        prompt = runner.run.call_args.args[1]
        assert 'memcpy overflow' in prompt and '"index": 1' in prompt
        assert 'CUSTOM RULES' in prompt and 'HARD EXCLUSIONS' not in prompt
        assert 'result-filter.json' in prompt
        assert 'MR !5' in prompt
        assert runner.run.call_args.kwargs == {'purpose': 'filter', 'required_key': 'decisions'}

    def test_default_rules_used_without_custom(self, tmp_path):
        runner = runner_returning(True, '', {'decisions': []})
        CopilotFilterClient(runner, tmp_path).analyze_findings(FINDINGS)
        assert 'HARD EXCLUSIONS' in runner.run.call_args.args[1]

    def test_runner_failure(self, tmp_path):
        runner = runner_returning(False, 'boom', {})
        ok, decisions, err = CopilotFilterClient(runner, tmp_path).analyze_findings(FINDINGS)
        assert not ok and decisions == {} and err == 'boom'


class TestFindingsFilterWithLlm:
    def test_llm_excludes_and_keeps(self):
        client = MagicMock()
        client.analyze_findings.return_value = (True, {
            0: {'keep_finding': True, 'confidence_score': 9, 'justification': 'real'},
            1: {'keep_finding': False, 'confidence_score': 2, 'exclusion_reason': 'noise', 'justification': 'n'},
        }, '')
        flt = FindingsFilter(use_llm_filtering=True, llm_client=client)
        ok, results, stats = flt.filter_findings(FINDINGS)
        assert ok and stats.kept_findings == 1 and stats.llm_excluded == 1
        assert results['filtered_findings'][0]['file'] == 'src/a.c'
        assert results['filtered_findings'][0]['_filter_metadata']['confidence_score'] == 9
        assert results['excluded_findings'][0]['filter_stage'] == 'llm'
        assert results['analysis_summary']['llm_excluded'] == 1
        client.analyze_findings.assert_called_once()

    def test_single_batched_call_only_gets_findings_that_passed_hard_rules(self):
        client = MagicMock()
        client.analyze_findings.return_value = (True, {0: {'keep_finding': True}}, '')
        findings = [{'file': 'a.c', 'description': 'Missing rate limiting'},
                    {'file': 'b.c', 'description': 'SQL injection'}]
        FindingsFilter(llm_client=client).filter_findings(findings)
        batch = client.analyze_findings.call_args.args[0]
        assert [f['file'] for f in batch] == ['b.c']

    def test_llm_failure_keeps_everything(self):
        client = MagicMock()
        client.analyze_findings.return_value = (False, {}, 'copilot down')
        ok, results, stats = FindingsFilter(llm_client=client).filter_findings(FINDINGS)
        assert ok and stats.kept_findings == 2 and stats.llm_excluded == 0
        assert 'copilot down' in results['filtered_findings'][0]['_filter_metadata']['justification']

    def test_missing_decision_keeps_finding(self):
        client = MagicMock()
        client.analyze_findings.return_value = (True, {0: {'keep_finding': False, 'confidence_score': 1}}, '')
        ok, results, stats = FindingsFilter(llm_client=client).filter_findings(FINDINGS)
        assert stats.llm_excluded == 1 and stats.kept_findings == 1

    def test_no_client_means_hard_rules_only(self):
        flt = FindingsFilter(use_llm_filtering=True, llm_client=None)
        assert flt.use_llm_filtering is False
        ok, results, stats = flt.filter_findings(FINDINGS)
        assert stats.kept_findings == 2


class TestEmbeddedMemorySafetyRules:
    def reason(self, path, text='stack buffer overflow in parser'):
        return HardExclusionRules.get_exclusion_reason({'file': path, 'description': text})

    def test_cpp_header_and_source_variants_are_kept(self):
        for path in ('a.c', 'a.cc', 'a.cpp', 'a.cxx', 'a.h', 'a.hh', 'a.hpp', 'a.hxx', 'A.HPP'):
            assert self.reason(path) is None, path

    def test_java_and_python_memory_findings_are_excluded(self):
        for path in ('A.java', 'a.py', 'Makefile'):
            assert 'non-C/C++' in self.reason(path), path

    def test_safe_rust_memory_finding_is_excluded(self):
        assert 'non-C/C++' in self.reason('lib.rs', 'buffer overflow in vector code')

    def test_unsafe_rust_memory_finding_is_kept(self):
        assert self.reason('lib.rs', 'out of bounds read in unsafe block using get_unchecked') is None
        assert self.reason('ffi.rs', 'buffer overflow when copying from raw pointer') is None
