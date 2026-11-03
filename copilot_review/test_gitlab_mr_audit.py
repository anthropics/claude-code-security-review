"""Tests for the main GitLab MR audit flow (GitLab and Copilot are mocked)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from copilot_review import gitlab_mr_audit
from copilot_review.gitlab_mr_audit import (
    ConfigurationError,
    get_environment_config,
    main,
    normalize_findings,
    post_results,
)

MR_DATA = {
    'number': 7, 'title': 'Add parser', 'body': 'desc', 'user': 'dev',
    'head': {'ref': 'f', 'sha': 'headsha', 'repo': {'full_name': 'group/project'}},
    'base': {'ref': 'main', 'sha': 'basesha'},
    'diff_refs': {'base_sha': 'basesha', 'start_sha': 'startsha', 'head_sha': 'headsha'},
    'files': [{'filename': 'src/a.c', 'status': 'modified', 'additions': 1, 'deletions': 0, 'changes': 1, 'patch': ''}],
    'additions': 1, 'deletions': 0, 'changed_files': 1,
    'source_project_id': 1, 'target_project_id': 1,
}

HIGH = {'file': 'src/a.c', 'line': 3, 'severity': 'HIGH', 'category': 'overflow',
        'description': 'memcpy with attacker controlled length', 'confidence': 0.95}
LOW = {'file': 'src/a.c', 'line': 8, 'severity': 'LOW', 'category': 'hardening',
       'description': 'weak check', 'confidence': 0.7}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('CI_MERGE_REQUEST_IID', '7')
    monkeypatch.setenv('REPO_PATH', str(tmp_path))
    monkeypatch.setenv('ENABLE_LLM_FILTERING', 'false')
    for name in ('MR_IID', 'DRY_RUN', 'RUN_EVERY_COMMIT', 'FAIL_ON_HIGH_SEVERITY', 'ALLOW_FORK_MRS',
                 'MAX_FINDING_THREADS', 'POST_CLEAN_SUMMARY', 'RESULTS_FILE',
                 'FALSE_POSITIVE_FILTERING_INSTRUCTIONS', 'CUSTOM_SECURITY_SCAN_INSTRUCTIONS'):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def fake_clients(mr_data=None, findings=None, shas=(), fps=(), audit_result=None):
    gitlab = MagicMock()
    gitlab.get_mr_data.return_value = dict(mr_data or MR_DATA)
    gitlab.get_mr_diff.return_value = 'diff --git a/src/a.c b/src/a.c\n+x\n'
    gitlab.list_discussions.return_value = []
    gitlab.find_review_markers.return_value = (set(shas), set(fps))
    gitlab._is_excluded.return_value = False
    gitlab.post_finding.return_value = 'inline'

    runner = MagicMock()
    runner.model = 'claude-sonnet-5.5'
    runner.validate_available.return_value = (True, '')
    runner.run.return_value = (True, '', audit_result or {
        'findings': findings if findings is not None else [HIGH, LOW],
        'analysis_summary': {'files_reviewed': 1},
    })
    return gitlab, runner


def run_main(gitlab, runner):
    with patch.object(gitlab_mr_audit, 'initialize_clients', return_value=(gitlab, runner)):
        with pytest.raises(SystemExit) as exc:
            main()
    return exc.value.code


class TestConfig:
    def test_missing_iid(self, monkeypatch, capsys):
        monkeypatch.delenv('CI_MERGE_REQUEST_IID', raising=False)
        monkeypatch.delenv('MR_IID', raising=False)
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
        assert 'CI_MERGE_REQUEST_IID' in json.loads(capsys.readouterr().out)['error']

    def test_invalid_iid(self, monkeypatch):
        monkeypatch.delenv('MR_IID', raising=False)
        monkeypatch.setenv('CI_MERGE_REQUEST_IID', 'abc')
        with pytest.raises(ConfigurationError, match='Invalid'):
            get_environment_config()

    def test_mr_iid_override(self, monkeypatch):
        monkeypatch.setenv('CI_MERGE_REQUEST_IID', '1')
        monkeypatch.setenv('MR_IID', '9')
        assert get_environment_config() == 9

    def test_client_configuration_error_exits_2(self, env, monkeypatch, capsys):
        monkeypatch.delenv('GITLAB_TOKEN', raising=False)
        monkeypatch.delenv('CI_API_V4_URL', raising=False)
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
        assert 'GitLab client' in json.loads(capsys.readouterr().out)['error']


class TestNormalize:
    def test_paths_made_relative_and_non_dicts_dropped(self, tmp_path):
        findings = normalize_findings(
            [{'file': f'{tmp_path}/src/a.c'}, {'file': './src/b.c'}, 'junk', None], tmp_path)
        assert [f['file'] for f in findings] == ['src/a.c', 'src/b.c']


class TestMainFlow:
    def test_posts_findings_and_summary(self, env, capsys):
        gitlab, runner = fake_clients()
        assert run_main(gitlab, runner) == 0
        assert gitlab.post_finding.call_count == 2
        # first thread is the HIGH finding (sorted by severity)
        assert gitlab.post_finding.call_args_list[0].args[2]['severity'] == 'HIGH'
        summary_body = gitlab.create_discussion.call_args.args[1]
        assert 'copilot-security-review:summary sha=headsha' in summary_body

        output = json.loads(capsys.readouterr().out)
        assert output['mr_iid'] == 7 and len(output['findings']) == 2
        assert output['posting']['posted_inline'] == 2
        assert (env / 'copilot-review-results.json').exists()

    def test_dry_run_posts_nothing(self, env, monkeypatch, capsys):
        monkeypatch.setenv('DRY_RUN', 'true')
        gitlab, runner = fake_clients()
        assert run_main(gitlab, runner) == 0
        gitlab.post_finding.assert_not_called()
        gitlab.create_discussion.assert_not_called()
        assert json.loads(capsys.readouterr().out)['posting'] == {'dry_run': True}

    def test_skips_when_mr_already_reviewed(self, env, capsys):
        gitlab, runner = fake_clients(shas={'oldsha'})
        assert run_main(gitlab, runner) == 0
        runner.run.assert_not_called()
        assert 'already reviewed' in json.loads(capsys.readouterr().out)['skipped']

    def test_run_every_commit_reviews_new_commit_but_not_same_commit(self, env, monkeypatch, capsys):
        monkeypatch.setenv('RUN_EVERY_COMMIT', 'true')
        gitlab, runner = fake_clients(shas={'oldsha'})
        assert run_main(gitlab, runner) == 0
        runner.run.assert_called_once()
        capsys.readouterr()

        gitlab, runner = fake_clients(shas={'headsha'})
        assert run_main(gitlab, runner) == 0
        runner.run.assert_not_called()
        assert 'already reviewed' in json.loads(capsys.readouterr().out)['skipped']

    def test_already_posted_findings_are_not_reposted(self, env, monkeypatch):
        from copilot_review.gitlab_client import finding_fingerprint
        monkeypatch.setenv('RUN_EVERY_COMMIT', 'true')
        gitlab, runner = fake_clients(shas={'oldsha'}, fps={finding_fingerprint(HIGH)})
        assert run_main(gitlab, runner) == 0
        assert gitlab.post_finding.call_count == 1
        assert gitlab.post_finding.call_args.args[2]['severity'] == 'LOW'

    def test_fork_mr_is_skipped(self, env, capsys):
        gitlab, runner = fake_clients(mr_data=dict(MR_DATA, source_project_id=2))
        assert run_main(gitlab, runner) == 0
        runner.run.assert_not_called()
        assert 'fork' in json.loads(capsys.readouterr().out)['skipped']

    def test_fork_mr_allowed_by_flag(self, env, monkeypatch):
        monkeypatch.setenv('ALLOW_FORK_MRS', 'true')
        gitlab, runner = fake_clients(mr_data=dict(MR_DATA, source_project_id=2))
        assert run_main(gitlab, runner) == 0
        runner.run.assert_called_once()

    def test_no_reviewable_files(self, env, capsys):
        gitlab, runner = fake_clients(mr_data=dict(MR_DATA, files=[]))
        assert run_main(gitlab, runner) == 0
        runner.run.assert_not_called()
        assert 'no reviewable files' in json.loads(capsys.readouterr().out)['skipped']

    def test_copilot_unavailable(self, env, capsys):
        gitlab, runner = fake_clients()
        runner.validate_available.return_value = (False, 'not installed')
        assert run_main(gitlab, runner) == 1
        assert 'Copilot CLI not available' in json.loads(capsys.readouterr().out)['error']

    def test_mr_fetch_failure(self, env, capsys):
        gitlab, runner = fake_clients()
        gitlab.get_mr_data.side_effect = RuntimeError('401')
        assert run_main(gitlab, runner) == 1
        assert 'Failed to fetch MR data' in json.loads(capsys.readouterr().out)['error']

    def test_audit_failure(self, env, capsys):
        gitlab, runner = fake_clients()
        runner.run.return_value = (False, 'no json', {})
        assert run_main(gitlab, runner) == 1
        assert 'Security audit failed' in json.loads(capsys.readouterr().out)['error']
        gitlab.create_discussion.assert_not_called()

    def test_prompt_too_long_retries_without_diff(self, env):
        gitlab, runner = fake_clients()
        runner.run.side_effect = [(False, 'PROMPT_TOO_LONG', {}), (True, '', {'findings': [HIGH]})]
        assert run_main(gitlab, runner) == 0
        assert runner.run.call_count == 2
        first, second = (c.args[1] for c in runner.run.call_args_list)
        assert 'MR DIFF CONTENT' in first and 'MR DIFF CONTENT' not in second
        assert 'diff was omitted' in second

    def test_fail_on_high_severity_is_opt_in(self, env, monkeypatch):
        gitlab, runner = fake_clients()
        assert run_main(gitlab, runner) == 0
        monkeypatch.setenv('FAIL_ON_HIGH_SEVERITY', 'true')
        gitlab, runner = fake_clients()
        assert run_main(gitlab, runner) == 1
        gitlab, runner = fake_clients(findings=[LOW])
        assert run_main(gitlab, runner) == 0

    def test_llm_filtering_runs_second_copilot_call(self, env, monkeypatch, capsys):
        monkeypatch.setenv('ENABLE_LLM_FILTERING', 'true')
        gitlab, runner = fake_clients()
        runner.run.side_effect = [
            (True, '', {'findings': [HIGH, LOW]}),
            (True, '', {'decisions': [{'index': 0, 'keep_finding': True, 'confidence_score': 9},
                                      {'index': 1, 'keep_finding': False, 'confidence_score': 2,
                                       'exclusion_reason': 'noise'}]}),
        ]
        assert run_main(gitlab, runner) == 0
        assert runner.run.call_count == 2
        assert runner.run.call_args_list[1].kwargs['purpose'] == 'filter'
        output = json.loads(capsys.readouterr().out)
        assert len(output['findings']) == 1 and output['filtering_summary']['excluded_findings'] == 1
        assert gitlab.post_finding.call_count == 1

    def test_directory_excluded_findings_are_dropped(self, env):
        gitlab, runner = fake_clients()
        gitlab._is_excluded.side_effect = lambda path: path == 'src/a.c'
        assert run_main(gitlab, runner) == 0
        gitlab.post_finding.assert_not_called()

    def test_custom_instruction_files_are_loaded(self, env, monkeypatch, tmp_path):
        scan = tmp_path / 'scan.txt'
        scan.write_text('**Custom Category:**\n- check CAN frames')
        monkeypatch.setenv('CUSTOM_SECURITY_SCAN_INSTRUCTIONS', str(scan))
        gitlab, runner = fake_clients()
        assert run_main(gitlab, runner) == 0
        assert 'check CAN frames' in runner.run.call_args_list[0].args[1]


class TestPostResults:
    def test_failed_finding_does_not_abort_and_is_listed_in_summary(self):
        gitlab = MagicMock()
        gitlab.post_finding.side_effect = [RuntimeError('boom'), 'inline']
        stats = post_results(gitlab, 7, MR_DATA, [HIGH, LOW], {}, 'm')
        assert stats['failed'] == 1 and stats['posted_inline'] == 1
        summary = gitlab.create_discussion.call_args.args[1]
        assert 'could not be attached' in summary and 'src/a.c:3' in summary

    def test_general_threads_are_listed_in_summary(self):
        gitlab = MagicMock()
        gitlab.post_finding.return_value = 'general'
        stats = post_results(gitlab, 7, MR_DATA, [HIGH], {}, 'm')
        assert stats['posted_general'] == 1
        assert 'src/a.c:3' in gitlab.create_discussion.call_args.args[1]

    def test_thread_limit(self):
        gitlab = MagicMock()
        gitlab.post_finding.return_value = 'inline'
        stats = post_results(gitlab, 7, MR_DATA, [HIGH, LOW], {}, 'm', max_threads=1)
        assert gitlab.post_finding.call_count == 1 and stats['over_limit'] == 1

    def test_clean_summary_can_be_disabled(self):
        gitlab = MagicMock()
        post_results(gitlab, 7, MR_DATA, [], {}, 'm', post_clean_summary=False)
        gitlab.create_discussion.assert_not_called()
        post_results(gitlab, 7, MR_DATA, [], {}, 'm', post_clean_summary=True)
        assert 'No security findings' in gitlab.create_discussion.call_args.args[1]

    def test_summary_failure_is_counted_not_raised(self):
        gitlab = MagicMock()
        gitlab.create_discussion.side_effect = RuntimeError('403')
        assert post_results(gitlab, 7, MR_DATA, [], {}, 'm')['failed'] == 1
