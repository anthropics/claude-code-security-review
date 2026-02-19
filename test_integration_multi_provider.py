#!/usr/bin/env python3
"""
Integration tests for multi-provider Claude Code functionality.
Run these with real credentials to test actual provider integration.
"""

import os
import pytest
from unittest.mock import patch
from claudecode.claude_client_factory import create_claude_client
from claudecode.env_validation import validate_environment_variables


class TestIntegrationAnthropicAPI:
    """Integration tests for direct Anthropic API."""
    
    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        reason="No Anthropic credentials available"
    )
    def test_anthropic_api_client_creation(self):
        """Test creating and validating Anthropic API client."""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY', 'dummy'),
            'CLAUDE_CODE_USE_BEDROCK': '',
            'CLAUDE_CODE_USE_VERTEX': ''
        }):
            client = create_claude_client()
            assert client is not None
            assert type(client).__name__ == 'ClaudeAPIClient'
            
            # Test API validation
            success, error = client.validate_api_access()
            if os.environ.get("ANTHROPIC_API_KEY"):
                assert success is True, f"API validation failed: {error}"
    
    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        reason="No Anthropic credentials available"
    )
    def test_anthropic_finding_analysis(self):
        """Test actual finding analysis with Anthropic API."""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY', 'dummy'),
            'CLAUDE_CODE_USE_BEDROCK': '',
            'CLAUDE_CODE_USE_VERTEX': ''
        }):
            client = create_claude_client()
            
            test_finding = {
                "rule": "test-sql-injection",
                "file": "app.py",
                "line": 42,
                "severity": "HIGH",
                "message": "Potential SQL injection vulnerability: user input directly interpolated into SQL query"
            }
            
            success, result, error = client.analyze_single_finding(test_finding)
            if os.environ.get("ANTHROPIC_API_KEY"):
                assert success is True, f"Finding analysis failed: {error}"
                assert "keep_finding" in result
                assert "confidence_score" in result


class TestIntegrationBedrock:
    """Integration tests for AWS Bedrock."""
    
    @pytest.mark.skipif(
        not all([
            os.environ.get("AWS_REGION"),
            os.environ.get("AWS_ACCESS_KEY_ID"), 
            os.environ.get("AWS_SECRET_ACCESS_KEY")
        ]),
        reason="AWS Bedrock credentials not available"
    )
    def test_bedrock_client_creation(self):
        """Test creating and validating Bedrock client."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_BEDROCK': '1',
            'CLAUDE_CODE_USE_VERTEX': '',
            'AWS_REGION': os.environ.get('AWS_REGION'),
            'AWS_ACCESS_KEY_ID': os.environ.get('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': os.environ.get('AWS_SECRET_ACCESS_KEY')
        }):
            client = create_claude_client()
            assert client is not None
            assert type(client).__name__ == 'ClaudeBedrockClient'
            
            # Test API validation
            success, error = client.validate_api_access()
            assert success is True, f"Bedrock validation failed: {error}"
    
    @pytest.mark.skipif(
        not all([
            os.environ.get("AWS_REGION"),
            os.environ.get("AWS_ACCESS_KEY_ID"), 
            os.environ.get("AWS_SECRET_ACCESS_KEY")
        ]),
        reason="AWS Bedrock credentials not available"
    )
    def test_bedrock_finding_analysis(self):
        """Test actual finding analysis with Bedrock."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_BEDROCK': '1',
            'CLAUDE_CODE_USE_VERTEX': '',
            'AWS_REGION': os.environ.get('AWS_REGION'),
            'AWS_ACCESS_KEY_ID': os.environ.get('AWS_ACCESS_KEY_ID'),
            'AWS_SECRET_ACCESS_KEY': os.environ.get('AWS_SECRET_ACCESS_KEY')
        }):
            client = create_claude_client()
            
            test_finding = {
                "rule": "test-xss",
                "file": "web.py", 
                "line": 15,
                "severity": "MEDIUM",
                "message": "Potential XSS vulnerability: user input rendered without escaping"
            }
            
            success, result, error = client.analyze_single_finding(test_finding)
            assert success is True, f"Finding analysis failed: {error}"
            assert "keep_finding" in result
            assert "confidence_score" in result


class TestIntegrationVertex:
    """Integration tests for Google Vertex AI."""
    
    @pytest.mark.skipif(
        not all([
            os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID"),
            os.environ.get("CLOUD_ML_REGION")
        ]),
        reason="Google Vertex AI credentials not available"
    )
    def test_vertex_client_creation(self):
        """Test creating and validating Vertex AI client."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_USE_VERTEX': '1',
            'CLAUDE_CODE_USE_BEDROCK': '',
            'ANTHROPIC_VERTEX_PROJECT_ID': os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID'),
            'CLOUD_ML_REGION': os.environ.get('CLOUD_ML_REGION')
        }):
            client = create_claude_client()
            assert client is not None
            assert type(client).__name__ == 'ClaudeVertexClient'
            
            # Test API validation  
            success, error = client.validate_api_access()
            assert success is True, f"Vertex validation failed: {error}"


def test_multi_provider_example_script():
    """Test the example script runs without errors."""
    import subprocess
    import sys
    
    # Run the example script and check it doesn't crash
    result = subprocess.run([
        sys.executable, 
        "/Users/elhayef/elhays/claude-code-security-review/examples/multi-provider-example.py"
    ], capture_output=True, text=True, timeout=30)
    
    # Script should not crash (exit code 0 or handled error)
    # It may fail due to missing credentials, but shouldn't crash
    assert result.returncode in [0], f"Script crashed with: {result.stderr}"


if __name__ == "__main__":
    # Run with: python -m pytest test_integration_multi_provider.py -v
    pytest.main([__file__, "-v"])
