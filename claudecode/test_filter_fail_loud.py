"""Tests for fail-loud false-positive filtering.

Regression cover for the defect these tests were written against: FindingsFilter used
to open with a fixed-model probe (validate_api_access, hard-coded to a model id that
was later retired). When the probe failed, filtering was silently switched off and the
audit reported hard-rules-only output as though the Claude filter had passed it. There
is no probe any more, and a configuration-class failure raises instead of degrading.
"""

import pytest
from unittest.mock import patch

from claudecode.claude_api_client import (
    ClaudeAPIClient,
    ClaudeFilteringUnavailableError,
    is_configuration_error,
)
from claudecode.findings_filter import FindingsFilter


NOT_FOUND = (
    "Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', "
    "'message': 'model: claude-3-5-haiku-20241022'}}"
)
RATE_LIMITED = (
    "Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error', "
    "'message': 'Number of requests has exceeded your rate limit'}}"
)
SPEND_CAP = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'API Error: 400 You have reached your specified workspace API usage "
    "limits. You will regain access on 2026-09-30 at 00:00 UTC.'}}"
)

A_FINDING = {
    'file': 'app/db.py',
    'line': 42,
    'severity': 'HIGH',
    'category': 'injection',
    'description': 'SQL injection: user input concatenated into a query string',
}


class TestConfigurationErrorClassification:
    """The classifier must be narrow: config errors only, never transient/billing."""

    @pytest.mark.parametrize('message', [
        NOT_FOUND,
        "Error code: 401 - {'error': {'type': 'authentication_error'}}",
        "Error code: 403 - {'error': {'type': 'permission_error'}}",
        "invalid x-api-key",
    ])
    def test_configuration_errors_are_detected(self, message):
        assert is_configuration_error(message) is True

    @pytest.mark.parametrize('message', [
        RATE_LIMITED,
        SPEND_CAP,
        "Error code: 529 - {'error': {'type': 'overloaded_error'}}",
        "Request timed out.",
        "Your credit balance is too low to access the Anthropic API.",
        "Connection error.",
        "",
    ])
    def test_transient_and_billing_errors_are_not_configuration_errors(self, message):
        assert is_configuration_error(message) is False


class TestNoStartupProbe:
    """Constructing the filter must not make an API call of its own."""

    def test_construction_makes_no_api_call(self):
        with patch('claudecode.claude_api_client.Anthropic') as anthropic:
            findings_filter = FindingsFilter(
                use_claude_filtering=True, api_key='test-key', model='claude-opus-5')
            assert findings_filter.use_claude_filtering is True
            assert findings_filter.claude_client is not None
            assert anthropic.return_value.messages.create.call_count == 0

    def test_client_has_no_validate_api_access(self):
        assert not hasattr(ClaudeAPIClient, 'validate_api_access')


class TestFailLoud:
    """A configuration-class failure must abort, never silently disable filtering."""

    def test_not_found_raises_instead_of_disabling_filtering(self):
        with patch('claudecode.claude_api_client.Anthropic') as anthropic, \
                patch('claudecode.claude_api_client.time.sleep'):
            anthropic.return_value.messages.create.side_effect = RuntimeError(NOT_FOUND)
            findings_filter = FindingsFilter(
                use_claude_filtering=True, api_key='test-key', model='claude-opus-5')
            with pytest.raises(ClaudeFilteringUnavailableError) as excinfo:
                findings_filter.filter_findings([dict(A_FINDING)])
            assert 'claude-opus-5' in str(excinfo.value)
            # Raised on the FIRST failure: no retry storm against an unknown model id.
            assert anthropic.return_value.messages.create.call_count == 1

    def test_transient_error_is_retried_not_treated_as_configuration(self):
        """Guards the classifier's narrowness: a rate limit must go down the RETRY path,
        not the configuration path. With a single finding the run still ends in a
        total-failure raise (see below), so what is pinned here is the retry behaviour and
        the error's WORDING — which is what narrowness actually means."""
        with patch('claudecode.claude_api_client.Anthropic') as anthropic, \
                patch('claudecode.claude_api_client.time.sleep'):
            anthropic.return_value.messages.create.side_effect = RuntimeError(RATE_LIMITED)
            findings_filter = FindingsFilter(
                use_claude_filtering=True, api_key='test-key', model='claude-opus-5')
            with pytest.raises(ClaudeFilteringUnavailableError) as excinfo:
                findings_filter.filter_findings([dict(A_FINDING)])
            assert anthropic.return_value.messages.create.call_count > 1
            assert 'no verdicts' in str(excinfo.value)

    def test_spend_cap_error_is_retried_not_treated_as_configuration(self):
        with patch('claudecode.claude_api_client.Anthropic') as anthropic, \
                patch('claudecode.claude_api_client.time.sleep'):
            anthropic.return_value.messages.create.side_effect = RuntimeError(SPEND_CAP)
            findings_filter = FindingsFilter(
                use_claude_filtering=True, api_key='test-key', model='claude-opus-5')
            with pytest.raises(ClaudeFilteringUnavailableError):
                findings_filter.filter_findings([dict(A_FINDING)])
            assert anthropic.return_value.messages.create.call_count > 1

    def test_a_total_transient_failure_raises_because_nothing_was_filtered(self):
        """A partial transient failure is a degraded real pass; a TOTAL one produced no
        verdict at all, and emitting that as a normal result is precisely the state
        ClaudeFilteringUnavailableError's docstring says must never happen."""
        with patch('claudecode.claude_api_client.Anthropic') as anthropic, \
                patch('claudecode.claude_api_client.time.sleep'):
            anthropic.return_value.messages.create.side_effect = RuntimeError(RATE_LIMITED)
            findings_filter = FindingsFilter(
                use_claude_filtering=True, api_key='test-key', model='claude-opus-5')
            with pytest.raises(ClaudeFilteringUnavailableError) as excinfo:
                findings_filter.filter_findings([dict(A_FINDING)])
            assert 'UNFILTERED' in str(excinfo.value)

    def test_a_partial_transient_failure_is_counted_not_raised(self):
        """The other half of the same rule — and the reason the count is reported at all:
        a partially-unfiltered result must be distinguishable from a clean pass."""
        good = {'keep_finding': True, 'confidence_score': 8, 'justification': 'real'}
        with patch('claudecode.claude_api_client.Anthropic'), \
                patch('claudecode.claude_api_client.time.sleep'), \
                patch('claudecode.claude_api_client.ClaudeAPIClient.analyze_single_finding') as asf:
            asf.side_effect = [(True, good, ''), (False, {}, RATE_LIMITED)]
            findings_filter = FindingsFilter(
                use_claude_filtering=True, api_key='test-key', model='claude-opus-5')
            other = dict(A_FINDING, file='app/web.py',
                         description='XSS: template renders unescaped user input')
            success, results, stats = findings_filter.filter_findings(
                [dict(A_FINDING), other])
            assert success is True
            assert stats.claude_api_failures == 1
            assert results['analysis_summary']['claude_api_failures'] == 1
