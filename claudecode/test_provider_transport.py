"""Exercise action configuration through the real SDK's serialized HTTP requests."""

import json
import os
import subprocess
from unittest.mock import patch

import pytest
from anthropic import _base_client

from claudecode.claude_api_client import ClaudeAPIClient
from claudecode.constants import DEFAULT_CLAUDE_MODEL, PROMPT_TOKEN_LIMIT
from claudecode.github_action_audit import initialize_findings_filter, SimpleClaudeRunner

# Intercept the installed SDK's transport: newer releases use httpx2.
httpx = getattr(_base_client, "httpx2", None) or _base_client.httpx


@pytest.fixture
def requests_sent(monkeypatch):
    """Intercept HTTP only, leaving provider resolution and SDK serialization real."""
    requests = []

    def send(client, request, **kwargs):
        body = json.loads(request.content)
        requests.append((str(request.url), body))
        return httpx.Response(200, request=request, json={
            "id": "msg_fixture", "type": "message", "role": "assistant",
            "model": body["model"],
            "content": [
                {"type": "thinking", "thinking": "Fixture reasoning", "signature": "fixture"},
                {"type": "text", "text": '{"keep_finding": true, "confidence_score": 9}'},
            ],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    monkeypatch.setattr(httpx.Client, "send", send)
    with patch.dict(os.environ, {}, clear=True):
        yield requests


def assert_server_defaults(body):
    # Omitted thinking/effort means adaptive/max for Flash and disabled for M3.
    # No incompatible disabled/none/service tier overrides should be synthesized.
    for field in ("thinking", "output_config", "reasoning_effort", "service_tier"):
        assert field not in body


@pytest.mark.parametrize("region,host", [
    ("", "api.minimax.io"), ("global_en", "api.minimax.io"), ("cn_zh", "api.minimaxi.com"),
])
@pytest.mark.parametrize("model", ["", "MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "custom-model"])
def test_action_default_and_explicit_models(requests_sent, monkeypatch, tmp_path, region, host, model):
    """The startup probe, findings filter, and CLI use the same resolved selection."""
    monkeypatch.setenv("ENABLE_CLAUDE_FILTERING", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CLAUDE_PROVIDER", "minimax")
    monkeypatch.setenv("CLAUDE_REGION", region)
    monkeypatch.setenv("CLAUDE_MODEL", model)
    expected_model = model or "MiniMax-M3.1-Flash"
    filter_instance = initialize_findings_filter()
    assert filter_instance.use_claude_filtering
    success, result, error = filter_instance.claude_client.analyze_single_finding({
        "description": "SQL injection", "severity": "HIGH",
    })
    assert success, error
    assert result["keep_finding"] is True
    assert len(requests_sent) == 2
    for url, body in requests_sent:
        assert url == f"https://{host}/anthropic/v1/messages"
        assert body["model"] == expected_model
        assert_server_defaults(body)
    assert requests_sent[0][1]["max_tokens"] == 10
    assert requests_sent[1][1]["max_tokens"] == PROMPT_TOKEN_LIMIT
    assert "system" in requests_sent[1][1]

    def run(cmd, **kwargs):
        assert cmd[cmd.index("--model") + 1] == expected_model
        assert os.environ["ANTHROPIC_BASE_URL"] == f"https://{host}/anthropic"
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": '{"findings": []}'}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert SimpleClaudeRunner().run_security_audit(tmp_path, "Review this code")[0]
    filter_instance.claude_client.client.close()


@pytest.mark.parametrize("provider", [None, "minimax"])
@pytest.mark.parametrize("base_url", [
    "https://api.minimax.io/anthropic", "https://api.minimaxi.com/anthropic",
    "https://proxy.example/anthropic",
])
def test_explicit_endpoint_and_model_preserved(requests_sent, monkeypatch, provider, base_url):
    monkeypatch.setenv("ENABLE_CLAUDE_FILTERING", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CLAUDE_MODEL", "saved-proxy-model")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)
    if provider:
        monkeypatch.setenv("CLAUDE_PROVIDER", provider)
        monkeypatch.setenv("CLAUDE_REGION", "cn_zh")
    filter_instance = initialize_findings_filter()
    assert filter_instance.use_claude_filtering
    assert filter_instance.claude_client.call_with_retry("Review this code")[0]
    for url, body in requests_sent:
        assert url == f"{base_url}/v1/messages"
        assert body["model"] == "saved-proxy-model"
        assert_server_defaults(body)
    assert os.environ["CLAUDE_MODEL"] == "saved-proxy-model"
    assert os.environ["ANTHROPIC_BASE_URL"] == base_url
    filter_instance.claude_client.client.close()


@pytest.mark.parametrize("model", ["MiniMax-M3.1-Flash", "MiniMax-M3"])
def test_content_blocks_are_not_rewritten(requests_sent, model):
    client = ClaudeAPIClient(api_key="test-key", provider="minimax", model=model)
    blocks = [
        {"type": "text", "text": "Review these inputs"},
        {"type": "image", "source": {"type": "url", "url": "https://example.com/image.png"}},
        {"type": "video", "source": {"type": "url", "url": "https://example.com/video.mp4"}},
    ]
    success, text, error = client.call_with_retry(blocks, max_tokens=4096)
    assert success, error
    assert "Fixture reasoning" not in text
    assert requests_sent[0][1]["messages"] == [{"role": "user", "content": blocks}]
    assert_server_defaults(requests_sent[0][1])
    client.client.close()


def test_default_provider_behavior_unchanged(requests_sent):
    client = ClaudeAPIClient(api_key="test-key")
    assert client.validate_api_access()[0]
    assert client.call_with_retry("Review this code")[0]
    assert requests_sent[0][1]["model"] == "claude-3-5-haiku-20241022"
    assert requests_sent[1][1]["model"] == DEFAULT_CLAUDE_MODEL
    for url, body in requests_sent:
        assert url == "https://api.anthropic.com/v1/messages"
        assert_server_defaults(body)
    client.client.close()
