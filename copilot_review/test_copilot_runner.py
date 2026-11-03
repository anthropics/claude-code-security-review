"""Unit tests for the Copilot CLI runner (subprocess is mocked)."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from copilot_review.constants import WORK_DIR_NAME
from copilot_review.copilot_runner import CopilotRunner, find_json_with_key

GOOD = {'findings': [{'file': 'a.c', 'line': 1}], 'analysis_summary': {}}


def completed(stdout='', stderr='', returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ('COPILOT_MODEL', 'COPILOT_PROMPT_MODE', 'COPILOT_EXTRA_ARGS', 'COPILOT_ALLOW_TOOLS',
                 'COPILOT_DENY_TOOLS', 'COPILOT_KEEP_WORKDIR', 'COPILOT_BIN'):
        monkeypatch.delenv(name, raising=False)


class TestFindJson:
    def test_plain_json(self):
        assert find_json_with_key(json.dumps(GOOD), 'findings') == GOOD

    def test_json_in_chatter(self):
        text = 'Thinking {"not": "it"} done.\n```json\n' + json.dumps(GOOD) + '\n```\nbye'
        assert find_json_with_key(text, 'findings') == GOOD

    def test_missing_key_or_empty(self):
        assert find_json_with_key('{"a": 1}', 'findings') is None
        assert find_json_with_key('', 'findings') is None
        assert find_json_with_key('no json here', 'findings') is None

    def test_unbalanced_braces_do_not_crash(self):
        assert find_json_with_key('{ broken ' + json.dumps(GOOD), 'findings') == GOOD


class TestCommand:
    def test_default_flags(self, tmp_path):
        runner = CopilotRunner()
        cmd = runner.build_command(tmp_path, 'do it')
        assert cmd[0] == 'copilot'
        assert '-s' in cmd and '--no-ask-user' in cmd and '--no-color' in cmd
        assert '--model=claude-sonnet-5.5' in cmd
        assert f'--add-dir={tmp_path}' in cmd
        allow = [c for c in cmd if c.startswith('--allow-tool=')][0]
        assert 'read' in allow and f'write({WORK_DIR_NAME}/*)' in allow
        deny = [c for c in cmd if c.startswith('--deny-tool=')][0]
        assert 'url' in deny and 'shell(curl:*)' in deny
        assert cmd[-2:] == ['-p', 'do it']

    def test_model_override_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv('COPILOT_MODEL', 'claude-opus-5.5')
        assert '--model=claude-opus-5.5' in CopilotRunner().build_command(tmp_path, 'x')

    def test_stdin_mode_has_no_prompt_flag(self, tmp_path):
        cmd = CopilotRunner(prompt_mode='stdin').build_command(tmp_path, None)
        assert '-p' not in cmd

    def test_tool_overrides_and_extra_args(self, monkeypatch, tmp_path):
        monkeypatch.setenv('COPILOT_ALLOW_TOOLS', 'read, shell(git diff:*)')
        monkeypatch.setenv('COPILOT_DENY_TOOLS', 'url')
        monkeypatch.setenv('COPILOT_EXTRA_ARGS', '--log-level=error')
        cmd = CopilotRunner().build_command(tmp_path, 'x')
        assert '--allow-tool=read, shell(git diff:*)' in cmd
        assert '--deny-tool=url' in cmd
        assert '--log-level=error' in cmd

    def test_invalid_prompt_mode(self):
        with pytest.raises(ValueError):
            CopilotRunner(prompt_mode='pipe')

    def test_env_hides_gitlab_secrets_but_keeps_copilot_token(self, monkeypatch):
        monkeypatch.setenv('GITLAB_TOKEN', 'secret')
        monkeypatch.setenv('CI_JOB_TOKEN', 'secret2')
        monkeypatch.setenv('COPILOT_GITHUB_TOKEN', 'ghp-ok')
        env = CopilotRunner().build_env()
        assert 'GITLAB_TOKEN' not in env and 'CI_JOB_TOKEN' not in env
        assert env['COPILOT_GITHUB_TOKEN'] == 'ghp-ok'


class TestValidate:
    def test_not_installed(self):
        with patch('subprocess.run', side_effect=FileNotFoundError):
            ok, msg = CopilotRunner().validate_available()
        assert not ok and 'not installed' in msg

    def test_missing_token(self, monkeypatch):
        for name in ('COPILOT_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN'):
            monkeypatch.delenv(name, raising=False)
        with patch('subprocess.run', return_value=completed('1.0.0')):
            ok, msg = CopilotRunner().validate_available()
        assert not ok and 'COPILOT_GITHUB_TOKEN' in msg

    def test_ok(self, monkeypatch):
        monkeypatch.setenv('COPILOT_GITHUB_TOKEN', 'tok')
        with patch('subprocess.run', return_value=completed('1.0.0')):
            assert CopilotRunner().validate_available() == (True, '')

    def test_nonzero_exit(self, monkeypatch):
        monkeypatch.setenv('COPILOT_GITHUB_TOKEN', 'tok')
        with patch('subprocess.run', return_value=completed('', 'boom', 3)):
            ok, msg = CopilotRunner().validate_available()
        assert not ok and 'exit code 3' in msg


class TestRun:
    def test_missing_repo_dir(self, tmp_path):
        ok, err, _ = CopilotRunner().run(tmp_path / 'nope', 'p')
        assert not ok and 'does not exist' in err

    def test_file_mode_reads_result_file_and_cleans_up(self, tmp_path):
        seen = {}

        def fake_run(cmd, **kwargs):
            prompt_file = tmp_path / WORK_DIR_NAME / 'prompt-audit.md'
            seen['prompt'] = prompt_file.read_text()
            seen['cmd'] = cmd
            seen['cwd'] = kwargs['cwd']
            seen['env'] = kwargs['env']
            CopilotRunner.result_path_for(tmp_path, 'audit').write_text(json.dumps(GOOD))
            return completed('chatter without json')

        with patch('subprocess.run', side_effect=fake_run):
            ok, err, result = CopilotRunner().run(tmp_path, 'THE FULL PROMPT')

        assert ok and result == GOOD
        assert seen['prompt'] == 'THE FULL PROMPT'
        assert str(tmp_path / WORK_DIR_NAME / 'prompt-audit.md') in seen['cmd'][-1]
        assert seen['cwd'] == tmp_path
        assert not (tmp_path / WORK_DIR_NAME).exists()  # work dir removed after the run

    def test_keep_workdir(self, monkeypatch, tmp_path):
        monkeypatch.setenv('COPILOT_KEEP_WORKDIR', 'true')
        with patch('subprocess.run', return_value=completed(json.dumps(GOOD))):
            ok, _, _ = CopilotRunner().run(tmp_path, 'p')
        assert ok and (tmp_path / WORK_DIR_NAME / 'prompt-audit.md').exists()

    def test_falls_back_to_stdout(self, tmp_path):
        with patch('subprocess.run', return_value=completed('Here you go:\n' + json.dumps(GOOD))):
            ok, _, result = CopilotRunner().run(tmp_path, 'p')
        assert ok and result == GOOD

    def test_required_key_for_filter(self, tmp_path):
        payload = {'decisions': [{'index': 0, 'keep_finding': False}]}
        with patch('subprocess.run', return_value=completed(json.dumps(payload))):
            ok, _, result = CopilotRunner().run(tmp_path, 'p', purpose='filter', required_key='decisions')
        assert ok and result == payload

    def test_retries_after_failure(self, tmp_path):
        responses = [completed('', 'transient', 1), completed(json.dumps(GOOD))]
        with patch('subprocess.run', side_effect=responses) as run, patch('time.sleep'):
            ok, _, result = CopilotRunner().run(tmp_path, 'p')
        assert ok and result == GOOD and run.call_count == 2

    def test_gives_up_after_max_retries(self, tmp_path):
        with patch('subprocess.run', return_value=completed('', 'always fails', 1)) as run, patch('time.sleep'):
            ok, err, _ = CopilotRunner(max_retries=2).run(tmp_path, 'p')
        assert not ok and run.call_count == 2
        assert 'return code 1' in err and 'always fails' in err

    def test_unparsable_output_fails_after_retries(self, tmp_path):
        with patch('subprocess.run', return_value=completed('no json')) as run:
            ok, err, _ = CopilotRunner(max_retries=2).run(tmp_path, 'p')
        assert not ok and run.call_count == 2 and "no JSON with 'findings'" in err

    def test_prompt_too_long_detected(self, tmp_path):
        with patch('subprocess.run', return_value=completed('', 'Error: prompt is too long', 1)):
            ok, err, _ = CopilotRunner().run(tmp_path, 'p')
        assert not ok and err == 'PROMPT_TOO_LONG'

    def test_timeout(self, tmp_path):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('copilot', 60)):
            ok, err, _ = CopilotRunner(timeout_minutes=1).run(tmp_path, 'p')
        assert not ok and 'timed out after 1 minutes' in err

    def test_stdin_mode_passes_prompt_on_stdin(self, tmp_path):
        with patch('subprocess.run', return_value=completed(json.dumps(GOOD))) as run:
            ok, _, _ = CopilotRunner(prompt_mode='stdin').run(tmp_path, 'PROMPT')
        assert ok
        assert run.call_args.kwargs['input'] == 'PROMPT'
        assert '-p' not in run.call_args.args[0]

    def test_arg_mode_small_prompt_is_passed_as_argument(self, tmp_path):
        with patch('subprocess.run', return_value=completed(json.dumps(GOOD))) as run:
            CopilotRunner(prompt_mode='arg').run(tmp_path, 'SMALL')
        assert run.call_args.args[0][-1] == 'SMALL'

    def test_arg_mode_large_prompt_switches_to_file(self, tmp_path):
        big = 'x' * 200_000
        with patch('subprocess.run', return_value=completed(json.dumps(GOOD))) as run:
            CopilotRunner(prompt_mode='arg').run(tmp_path, big)
        assert run.call_args.args[0][-1] != big
        assert 'prompt-audit.md' in run.call_args.args[0][-1]
