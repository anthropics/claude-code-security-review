#!/usr/bin/env python3
"""
Tests for the two defects fixed in the Freehold fork:

1. A pull request of more than 300 files or 20,000 lines gets a 406 from
   GitHub's diff rendering. The client must rebuild the diff from the
   paged files endpoint instead of giving up.
2. The false-positive filter validates the API key on the configured
   model, not on a retired model name.
"""

import json
import os
from unittest.mock import Mock, patch

import pytest
import requests

from claudecode.claude_api_client import ClaudeAPIClient
from claudecode.github_action_audit import GitHubActionClient


def _json_response(payload, next_url=None):
    """A page of the files endpoint. GitHub names the next page in Link."""
    response = Mock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.headers = {}
    if next_url:
        response.headers['Link'] = f'<{next_url}>; rel="next", <{next_url}>; rel="last"'
    return response


def _diff_refused_response():
    """The response GitHub gives for application/vnd.github.diff above the limits."""
    response = Mock()
    response.status_code = 406
    response.text = json.dumps({
        'message': 'Sorry, the diff exceeded the maximum number of files (300).',
        'errors': [{'resource': 'PullRequest', 'field': 'diff', 'code': 'too_large'}]
    })
    http_error = requests.HTTPError('406 Client Error: Not Acceptable')
    response.raise_for_status.side_effect = http_error
    return response


def _file_entry(index, patch=True, status='modified'):
    filename = f'store/src/generated/file{index:04d}.ts'
    entry = {
        'filename': filename,
        'status': status,
        'additions': 1,
        'deletions': 0,
        'changes': 1,
    }
    if patch:
        entry['patch'] = f'@@ -0,0 +1 @@\n+export const value{index} = {index};'
    return entry


class TestGetPrDiffFallback:
    """get_pr_diff must survive GitHub refusing to render a large diff."""

    @patch('requests.get')
    def test_rebuilds_diff_from_paged_files_on_406(self, mock_get):
        page_one = [_file_entry(i) for i in range(100)]
        page_two = [_file_entry(i) for i in range(100, 200)]
        page_three = [
            _file_entry(200, status='added'),
            _file_entry(201, patch=False),          # too large: no patch field
            {                                       # binary: no patch field
                'filename': 'store/public/logo.png',
                'status': 'added',
                'additions': 0,
                'deletions': 0,
                'changes': 0,
            },
        ]
        files = 'https://api.github.com/repos/owner/repo/pulls/40/files?per_page=100'
        mock_get.side_effect = [
            _diff_refused_response(),
            _json_response(page_one, next_url=f'{files}&page=2'),
            _json_response(page_two, next_url=f'{files}&page=3'),
            _json_response(page_three),
        ]

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            diff = client.get_pr_diff('owner/repo', 40)

        # The diff rendering was asked for first, then every page of files
        urls = [call.args[0] for call in mock_get.call_args_list]
        assert urls == [
            'https://api.github.com/repos/owner/repo/pulls/40',
            'https://api.github.com/repos/owner/repo/pulls/40/files?per_page=100',
            'https://api.github.com/repos/owner/repo/pulls/40/files?per_page=100&page=2',
            'https://api.github.com/repos/owner/repo/pulls/40/files?per_page=100&page=3',
        ]
        assert mock_get.call_args_list[0].kwargs['headers']['Accept'] == 'application/vnd.github.diff'
        assert mock_get.call_args_list[1].kwargs['headers']['Accept'] == 'application/vnd.github.v3+json'

        # Every file with a patch is in the diff, as its own unified section
        assert diff.count('diff --git ') == 201
        assert 'diff --git a/store/src/generated/file0000.ts b/store/src/generated/file0000.ts' in diff
        assert '+export const value199 = 199;' in diff
        assert '--- /dev/null\n+++ b/store/src/generated/file0200.ts' in diff
        assert '--- a/store/src/generated/file0000.ts\n+++ b/store/src/generated/file0000.ts' in diff

        # The files without a patch are left out and named in the summary
        assert 'file0201.ts' not in diff
        assert 'logo.png' not in diff
        assert client.diff_summary == {
            'source': 'files-endpoint',
            'files_without_patch': ['store/src/generated/file0201.ts', 'store/public/logo.png'],
        }

    @patch('requests.get')
    def test_rebuilt_diff_records_renames_and_deletions(self, mock_get):
        entries = [
            {
                'filename': 'store/src/new-name.ts',
                'previous_filename': 'store/src/old-name.ts',
                'status': 'renamed',
                'additions': 1, 'deletions': 1, 'changes': 2,
                'patch': '@@ -1 +1 @@\n-old\n+new',
            },
            {
                'filename': 'store/src/gone.ts',
                'status': 'removed',
                'additions': 0, 'deletions': 1, 'changes': 1,
                'patch': '@@ -1 +0,0 @@\n-gone',
            },
        ]
        mock_get.side_effect = [_diff_refused_response(), _json_response(entries)]

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            diff = client.get_pr_diff('owner/repo', 40)

        assert ('diff --git a/store/src/old-name.ts b/store/src/new-name.ts\n'
                'rename from store/src/old-name.ts\nrename to store/src/new-name.ts\n'
                '--- a/store/src/old-name.ts\n+++ b/store/src/new-name.ts\n') in diff
        assert '--- a/store/src/gone.ts\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n' in diff

    @patch('requests.get')
    def test_rebuilt_diff_still_drops_excluded_and_generated_files(self, mock_get):
        entries = [
            _file_entry(1),
            {
                'filename': 'showcases/demo/app.js',
                'status': 'modified',
                'additions': 1, 'deletions': 0, 'changes': 1,
                'patch': '@@ -1 +1,2 @@\n console.log(1)\n+console.log(2)',
            },
            {
                'filename': 'store/src/api.gen.ts',
                'status': 'modified',
                'additions': 1, 'deletions': 0, 'changes': 1,
                'patch': '@@ -1 +1,2 @@\n // @generated by openapi\n+export {}',
            },
        ]
        mock_get.side_effect = [_diff_refused_response(), _json_response(entries)]

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token', 'EXCLUDE_DIRECTORIES': 'showcases'}):
            client = GitHubActionClient()
            diff = client.get_pr_diff('owner/repo', 40)

        assert 'file0001.ts' in diff
        assert 'showcases/demo/app.js' not in diff
        assert 'api.gen.ts' not in diff

    @patch('requests.get')
    def test_small_pr_keeps_the_single_call_and_says_so(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.text = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n'
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            diff = client.get_pr_diff('owner/repo', 7)

        assert mock_get.call_count == 1
        assert diff == response.text
        assert client.diff_summary == {'source': 'pull-request-diff', 'files_without_patch': []}

    @patch('requests.get')
    def test_other_http_errors_still_raise(self, mock_get):
        response = Mock()
        response.status_code = 500
        response.raise_for_status.side_effect = requests.HTTPError('500 Server Error')
        mock_get.return_value = response

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            with pytest.raises(requests.HTTPError, match='500'):
                client.get_pr_diff('owner/repo', 7)

        assert mock_get.call_count == 1
        assert client.diff_summary is None


class TestGetPrDataPagesFiles:
    """get_pr_data used to read the first 100 files only."""

    @patch('requests.get')
    def test_lists_every_page_of_files(self, mock_get):
        pr_payload = {
            'number': 40, 'title': 'Big', 'body': '', 'user': {'login': 'u'},
            'created_at': 't', 'updated_at': 't', 'state': 'open',
            'head': {'ref': 'b', 'sha': 'h', 'repo': {'full_name': 'owner/repo'}},
            'base': {'ref': 'main', 'sha': 'm'},
            'additions': 471, 'deletions': 0, 'changed_files': 471,
        }
        pages = [
            [_file_entry(i) for i in range(0, 100)],
            [_file_entry(i) for i in range(100, 200)],
            [_file_entry(i) for i in range(200, 300)],
            [_file_entry(i) for i in range(300, 400)],
            [_file_entry(i) for i in range(400, 471)],
        ]
        files = 'https://api.github.com/repos/owner/repo/pulls/40/files?per_page=100'
        mock_get.side_effect = [_json_response(pr_payload)] + [
            _json_response(page, next_url=None if n == len(pages) else f'{files}&page={n + 1}')
            for n, page in enumerate(pages, start=1)
        ]

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            data = client.get_pr_data('owner/repo', 40)

        assert len(data['files']) == 471
        assert data['files'][-1]['filename'] == 'store/src/generated/file0470.ts'
        assert mock_get.call_count == 6
        assert mock_get.call_args_list[-1].args[0].endswith('files?per_page=100&page=5')

    @patch('requests.get')
    def test_a_full_page_without_a_link_header_is_the_last_page(self, mock_get):
        pr_payload = {
            'number': 1, 'title': 'T', 'body': '', 'user': {'login': 'u'},
            'created_at': 't', 'updated_at': 't', 'state': 'open',
            'head': {'ref': 'b', 'sha': 'h', 'repo': {'full_name': 'owner/repo'}},
            'base': {'ref': 'main', 'sha': 'm'},
            'additions': 100, 'deletions': 0, 'changed_files': 100,
        }
        mock_get.side_effect = [
            _json_response(pr_payload),
            _json_response([_file_entry(i) for i in range(100)]),
        ]

        with patch.dict(os.environ, {'GITHUB_TOKEN': 'test-token'}):
            client = GitHubActionClient()
            data = client.get_pr_data('owner/repo', 1)

        assert len(data['files']) == 100
        assert mock_get.call_count == 2


class TestValidateApiAccessModel:
    """The key check must ping the model the filter will use."""

    @patch('claudecode.claude_api_client.Anthropic')
    def test_pings_the_configured_model(self, mock_anthropic_class):
        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        client = ClaudeAPIClient(model='claude-sonnet-5', api_key='test-key')
        valid, error = client.validate_api_access()

        assert valid is True
        assert error == ''
        mock_client.messages.create.assert_called_once()
        assert mock_client.messages.create.call_args.kwargs['model'] == 'claude-sonnet-5'

    @patch('claudecode.claude_api_client.Anthropic')
    def test_default_model_comes_from_constants_not_a_literal(self, mock_anthropic_class):
        from claudecode.constants import DEFAULT_CLAUDE_MODEL

        mock_client = Mock()
        mock_anthropic_class.return_value = mock_client

        client = ClaudeAPIClient(api_key='test-key')
        client.validate_api_access()

        model_used = mock_client.messages.create.call_args.kwargs['model']
        assert model_used == DEFAULT_CLAUDE_MODEL
        assert model_used != 'claude-3-5-haiku-20241022'

    @patch('claudecode.claude_api_client.Anthropic')
    def test_reports_failure_when_the_model_is_refused(self, mock_anthropic_class):
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception('404 model: not-a-model')
        mock_anthropic_class.return_value = mock_client

        client = ClaudeAPIClient(model='not-a-model', api_key='test-key')
        valid, error = client.validate_api_access()

        assert valid is False
        assert 'not-a-model' in error
