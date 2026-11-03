"""Unit tests for the GitLab client helpers and API calls (no network)."""

import pytest

from copilot_review.gitlab_client import (
    GitLabAPIError,
    GitLabClient,
    build_unified_diff,
    count_changes,
    finding_fingerprint,
    format_finding_comment,
    format_summary_comment,
    parse_diff_line_map,
    sanitize_markdown,
)

PATCH = """@@ -10,4 +10,6 @@ int main(void) {
 int a = 1;
-int b = 2;
+int b = 3;
+int c = 4;
 return a;
\\ No newline at end of file
@@ -40,2 +42,3 @@ void f(void) {
 x();
+y();
 z();
"""


class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None, text=''):
        self.status_code = status_code
        self._data = data
        self.headers = headers or {}
        self.text = text or (str(data) if data is not None else '')

    def json(self):
        return self._data


class FakeSession:
    """Routes requests by (method, path-suffix) to a callable or a canned response."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, params=None, data=None, **kwargs):
        self.calls.append({'method': method, 'url': url, 'params': params, 'data': data, 'headers': headers})
        for (route_method, suffix), handler in self.routes.items():
            if route_method == method and url.endswith(suffix):
                return handler(params, data) if callable(handler) else handler
        return FakeResponse(404, {'message': 'not found'}, text='404 not found')


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('CI_API_V4_URL', 'https://gitlab.example.com/api/v4')
    monkeypatch.setenv('GITLAB_TOKEN', 'glpat-test')
    monkeypatch.setenv('CI_PROJECT_ID', '42')
    monkeypatch.setenv('CI_PROJECT_PATH', 'group/project')
    monkeypatch.delenv('EXCLUDE_DIRECTORIES', raising=False)


MR = {
    'iid': 7,
    'title': 'Add parser',
    'description': 'parser',
    'author': {'username': 'dev'},
    'created_at': 'x', 'updated_at': 'y', 'state': 'opened',
    'web_url': 'https://gitlab.example.com/group/project/-/merge_requests/7',
    'source_branch': 'feature', 'target_branch': 'main', 'sha': 'headsha',
    'source_project_id': 42, 'target_project_id': 42,
    'diff_refs': {'base_sha': 'basesha', 'start_sha': 'startsha', 'head_sha': 'headsha'},
}

DIFFS = [
    {'old_path': 'src/main.c', 'new_path': 'src/main.c', 'diff': PATCH,
     'new_file': False, 'renamed_file': False, 'deleted_file': False},
    {'old_path': 'vendor/lib.c', 'new_path': 'vendor/lib.c', 'diff': '@@ -1 +1 @@\n-a\n+b\n',
     'new_file': False, 'renamed_file': False, 'deleted_file': False},
]


def make_client(routes):
    session = FakeSession(routes)
    return GitLabClient(session=session), session


class TestDiffHelpers:
    def test_line_map_added_and_context(self):
        mapping = parse_diff_line_map(PATCH)
        # first hunk: context a=10/10, removed b (old 11), added 11 and 12, context return 12 -> old 12
        assert mapping[10] == 10
        assert mapping[11] is None
        assert mapping[12] is None
        assert mapping[13] == 12
        # second hunk starts at new line 42
        assert mapping[42] == 40
        assert mapping[43] is None
        assert mapping[44] == 41
        # lines outside the hunks are not commentable
        assert 30 not in mapping

    def test_line_map_empty_patch(self):
        assert parse_diff_line_map('') == {}

    def test_count_changes(self):
        assert count_changes(PATCH) == (3, 1)

    def test_build_unified_diff_modified_and_new(self):
        text = build_unified_diff([
            DIFFS[0],
            {'old_path': 'a.c', 'new_path': 'a.c', 'diff': '@@ -0,0 +1 @@\n+x', 'new_file': True},
        ])
        assert 'diff --git a/src/main.c b/src/main.c' in text
        assert '--- a/src/main.c' in text and '+++ b/src/main.c' in text
        assert '--- /dev/null' in text
        assert text.endswith('+x\n')


class TestSanitize:
    def test_quick_action_lines_are_defused(self):
        cleaned = sanitize_markdown('fine\n/merge\n  /assign @bob')
        for line in cleaned.splitlines():
            assert not line.lstrip().startswith('/')

    def test_mentions_are_defused(self):
        assert '@bob' not in sanitize_markdown('ping @bob please')

    def test_none_is_empty(self):
        assert sanitize_markdown(None) == ''


class TestClientInit:
    def test_requires_token(self, monkeypatch, env):
        monkeypatch.delenv('GITLAB_TOKEN')
        with pytest.raises(ValueError, match='GITLAB_TOKEN'):
            GitLabClient()

    def test_requires_api_url(self, monkeypatch, env):
        monkeypatch.delenv('CI_API_V4_URL')
        monkeypatch.delenv('GITLAB_URL', raising=False)
        with pytest.raises(ValueError, match='CI_API_V4_URL'):
            GitLabClient()

    def test_requires_project_id(self, monkeypatch, env):
        monkeypatch.delenv('CI_PROJECT_ID')
        with pytest.raises(ValueError, match='CI_PROJECT_ID'):
            GitLabClient()

    def test_gitlab_url_fallback(self, monkeypatch, env):
        monkeypatch.delenv('CI_API_V4_URL')
        monkeypatch.setenv('GITLAB_URL', 'https://gl.internal/')
        assert GitLabClient().api_url == 'https://gl.internal/api/v4'


class TestMrData:
    def routes(self):
        return {
            ('GET', '/projects/42/merge_requests/7'): FakeResponse(200, MR),
            ('GET', '/projects/42/merge_requests/7/diffs'): FakeResponse(200, DIFFS),
        }

    def test_get_mr_data_shape(self, env):
        client, session = make_client(self.routes())
        data = client.get_mr_data(7)
        assert data['number'] == 7
        assert data['user'] == 'dev'
        assert data['head']['repo']['full_name'] == 'group/project'
        assert data['diff_refs'] == {'base_sha': 'basesha', 'start_sha': 'startsha', 'head_sha': 'headsha'}
        assert [f['filename'] for f in data['files']] == ['src/main.c', 'vendor/lib.c']
        assert data['additions'] == 4 and data['deletions'] == 2
        assert session.calls[0]['headers'] == {'PRIVATE-TOKEN': 'glpat-test'}

    def test_excluded_directories(self, monkeypatch, env):
        monkeypatch.setenv('EXCLUDE_DIRECTORIES', 'vendor')
        client, _ = make_client(self.routes())
        data = client.get_mr_data(7)
        assert [f['filename'] for f in data['files']] == ['src/main.c']
        assert 'vendor/lib.c' not in client.get_mr_diff(data)

    def test_diff_pagination(self, env):
        pages = {}

        def diffs(params, data):
            page = params['page']
            pages[page] = True
            if page == 1:
                return FakeResponse(200, [DIFFS[0]], headers={'X-Next-Page': '2'})
            return FakeResponse(200, [DIFFS[1]], headers={'X-Next-Page': ''})

        routes = self.routes()
        routes[('GET', '/projects/42/merge_requests/7/diffs')] = diffs
        client, _ = make_client(routes)
        assert len(client.get_mr_data(7)['files']) == 2
        assert pages == {1: True, 2: True}

    def test_falls_back_to_changes_endpoint(self, env):
        routes = self.routes()
        routes[('GET', '/projects/42/merge_requests/7/diffs')] = FakeResponse(404, {}, text='404 Not Found')
        routes[('GET', '/projects/42/merge_requests/7/changes')] = FakeResponse(200, {'changes': DIFFS})
        client, _ = make_client(routes)
        assert len(client.get_mr_data(7)['files']) == 2

    def test_api_error_is_raised(self, env):
        routes = {('GET', '/projects/42/merge_requests/7'): FakeResponse(401, {}, text='401 Unauthorized')}
        client, _ = make_client(routes)
        with pytest.raises(GitLabAPIError):
            client.get_mr_data(7)

    def test_generated_files_are_filtered(self, env):
        client, _ = make_client(self.routes())
        diff = 'diff --git a/a.c b/a.c\n@@ -1 +1 @@\n+// @generated by tool\ndiff --git a/b.c b/b.c\n+x\n'
        filtered = client._filter_generated_files(diff)
        assert 'a.c' not in filtered and 'b.c' in filtered


class TestPositions:
    def make(self, env):
        client, _ = make_client({
            ('GET', '/projects/42/merge_requests/7'): FakeResponse(200, MR),
            ('GET', '/projects/42/merge_requests/7/diffs'): FakeResponse(200, DIFFS),
        })
        return client, client.get_mr_data(7)

    def test_added_line_has_no_old_line(self, env):
        client, data = self.make(env)
        position = client.build_position(data, 'src/main.c', 11)
        assert position['new_line'] == 11
        assert 'old_line' not in position
        assert position['base_sha'] == 'basesha' and position['start_sha'] == 'startsha'
        assert position['head_sha'] == 'headsha'
        assert position['position_type'] == 'text'

    def test_context_line_has_both_lines(self, env):
        client, data = self.make(env)
        position = client.build_position(data, './src/main.c', '13')
        assert position['new_line'] == 13 and position['old_line'] == 12
        assert position['new_path'] == 'src/main.c'

    def test_line_outside_diff_or_unknown_file(self, env):
        client, data = self.make(env)
        assert client.build_position(data, 'src/main.c', 99) is None
        assert client.build_position(data, 'other.c', 11) is None
        assert client.build_position(data, 'src/main.c', 'abc') is None

    def test_missing_diff_refs(self, env):
        client, data = self.make(env)
        data['diff_refs'] = {'base_sha': None, 'start_sha': None, 'head_sha': 'h'}
        assert client.build_position(data, 'src/main.c', 11) is None


class TestPosting:
    FINDING = {'file': 'src/main.c', 'line': 11, 'severity': 'HIGH', 'category': 'buffer_overflow',
               'description': 'memcpy with attacker controlled length', 'recommendation': 'check len'}

    def make(self, env, discussion_handler):
        client, session = make_client({
            ('GET', '/projects/42/merge_requests/7'): FakeResponse(200, MR),
            ('GET', '/projects/42/merge_requests/7/diffs'): FakeResponse(200, DIFFS),
            ('POST', '/projects/42/merge_requests/7/discussions'): discussion_handler,
        })
        return client, session, client.get_mr_data(7)

    def test_inline_thread_uses_position_form_fields(self, env):
        client, session, data = self.make(env, lambda p, d: FakeResponse(201, {'id': 'x'}))
        assert client.post_finding(7, data, self.FINDING) == 'inline'
        post = [c for c in session.calls if c['method'] == 'POST'][0]
        assert post['data']['position[new_line]'] == '11'
        assert post['data']['position[head_sha]'] == 'headsha'
        assert post['data']['position[position_type]'] == 'text'
        assert 'copilot-security-review:finding' in post['data']['body']

    def test_falls_back_to_general_thread_when_position_rejected(self, env):
        def handler(params, data):
            if 'position[new_line]' in data:
                return FakeResponse(400, {}, text='400 line_code can not be blank')
            return FakeResponse(201, {'id': 'x'})

        client, session, data = self.make(env, handler)
        assert client.post_finding(7, data, self.FINDING) == 'general'
        posts = [c for c in session.calls if c['method'] == 'POST']
        assert len(posts) == 2
        assert 'position[new_line]' not in posts[1]['data']
        assert '`src/main.c` line 11' in posts[1]['data']['body']

    def test_finding_not_in_diff_goes_straight_to_general(self, env):
        client, session, data = self.make(env, lambda p, d: FakeResponse(201, {'id': 'x'}))
        finding = dict(self.FINDING, line=500)
        assert client.post_finding(7, data, finding) == 'general'
        assert len([c for c in session.calls if c['method'] == 'POST']) == 1

    def test_general_failure_raises(self, env):
        client, _, data = self.make(env, lambda p, d: FakeResponse(403, {}, text='403 Forbidden'))
        with pytest.raises(GitLabAPIError):
            client.post_finding(7, data, dict(self.FINDING, line=500))


class TestMarkersAndFormatting:
    def test_find_review_markers(self):
        discussions = [
            {'notes': [{'body': '<!-- copilot-security-review:summary sha=abc123 -->\n## Copilot Security Review'}]},
            {'notes': [{'body': '<!-- copilot-security-review:finding fp=deadbeef0001 sha=abc123 -->\nx'}]},
            {'notes': [{'body': 'unrelated comment'}]},
        ]
        shas, fps = GitLabClient.find_review_markers(discussions)
        assert shas == {'abc123'} and fps == {'deadbeef0001'}

    def test_fingerprint_is_stable_across_line_moves(self):
        a = {'file': './src/a.c', 'line': 10, 'category': 'X', 'description': 'Same issue'}
        b = {'file': 'src/a.c', 'line': 99, 'category': 'x', 'description': 'same issue'}
        assert finding_fingerprint(a) == finding_fingerprint(b)

    def test_finding_comment_contains_marker_and_neutralises_quick_actions(self):
        finding = {'file': 'a.c', 'line': 3, 'severity': 'high', 'category': 'rce',
                   'description': 'bad\n/merge', 'exploit_scenario': 'ping @bob', 'confidence': 0.9}
        body = format_finding_comment(finding, 'sha1', inline=True)
        assert 'copilot-security-review:finding fp=' in body
        assert 'sha=sha1' in body
        assert 'HIGH' in body
        assert not any(line.lstrip().startswith('/merge') for line in body.splitlines())
        assert '@bob' not in body

    def test_general_comment_names_location(self):
        body = format_finding_comment({'file': 'a.c', 'line': 3, 'severity': 'LOW', 'description': 'd'},
                                      'sha1', inline=False)
        assert 'Location: `a.c` line 3' in body

    def test_summary_comment(self):
        findings = [{'severity': 'HIGH'}, {'severity': 'LOW'}]
        body = format_summary_comment(findings, 'abcdef123456', 'claude-sonnet-5.5',
                                      {'total_original_findings': 3, 'excluded_findings': 1},
                                      not_inline=[{'file': 'x.c', 'line': 2, 'severity': 'LOW', 'description': 'd'}])
        assert 'copilot-security-review:summary sha=abcdef123456' in body
        assert '1 high, 0 medium, 1 low' in body
        assert '`x.c:2`' in body
        assert 'claude-sonnet-5.5' in body

    def test_summary_without_findings(self):
        body = format_summary_comment([], 'abcdef123456', 'm')
        assert 'No security findings' in body
