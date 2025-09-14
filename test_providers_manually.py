#!/usr/bin/env python3
"""
Manual testing script for multi-provider functionality.
Run this script to quickly test different provider configurations.
"""

import os
import sys
from claudecode.env_validation import validate_environment_variables, get_provider_type
from claudecode.claude_client_factory import create_claude_client


def test_current_configuration():
    """Test the current environment configuration."""
    print("🔍 Testing Current Configuration")
    print("=" * 50)
    
    try:
        print("1. Environment validation...")
        validate_environment_variables()
        print("   ✅ Environment validation passed")
        
        print("2. Provider detection...")
        provider = get_provider_type()
        print(f"   ✅ Detected provider: {provider}")
        
        print("3. Client creation...")
        client = create_claude_client()
        print(f"   ✅ Created client: {type(client).__name__}")
        
        print("4. API access validation...")
        success, error = client.validate_api_access()
        if success:
            print("   ✅ API access validated successfully")
        else:
            print(f"   ❌ API access validation failed: {error}")
            return False
            
        print("5. Test finding analysis...")
        test_finding = {
            "rule": "test-rule",
            "file": "test.py",
            "line": 1,
            "severity": "HIGH", 
            "message": "Test security finding for validation"
        }
        
        success, result, error = client.analyze_single_finding(test_finding)
        if success:
            print("   ✅ Finding analysis successful")
            print(f"   Result: {result}")
        else:
            print(f"   ❌ Finding analysis failed: {error}")
            
    except Exception as e:
        print(f"   ❌ Configuration test failed: {e}")
        return False
    
    return True


def test_anthropic_api_configuration():
    """Test Anthropic API configuration."""
    print("\n🔍 Testing Anthropic API Configuration")
    print("=" * 50)
    
    # Temporarily set environment for Anthropic API
    original_env = dict(os.environ)
    try:
        # Clear provider flags
        os.environ.pop('CLAUDE_CODE_USE_BEDROCK', None)
        os.environ.pop('CLAUDE_CODE_USE_VERTEX', None)
        
        # Check for Anthropic credentials
        if not os.environ.get('ANTHROPIC_API_KEY') and not os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'):
            print("   ⚠️  No Anthropic credentials available - skipping")
            return
            
        return test_current_configuration()
        
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


def test_bedrock_configuration():
    """Test AWS Bedrock configuration."""
    print("\n🔍 Testing AWS Bedrock Configuration")
    print("=" * 50)
    
    # Check for AWS credentials
    required_vars = ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"   ⚠️  Missing AWS credentials: {', '.join(missing_vars)} - skipping")
        return
    
    original_env = dict(os.environ)
    try:
        # Set Bedrock provider
        os.environ['CLAUDE_CODE_USE_BEDROCK'] = '1'
        os.environ.pop('CLAUDE_CODE_USE_VERTEX', None)
        
        return test_current_configuration()
        
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


def test_vertex_configuration():
    """Test Google Vertex AI configuration.""" 
    print("\n🔍 Testing Google Vertex AI Configuration")
    print("=" * 50)
    
    # Check for Vertex credentials
    required_vars = ['ANTHROPIC_VERTEX_PROJECT_ID', 'CLOUD_ML_REGION']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"   ⚠️  Missing Vertex credentials: {', '.join(missing_vars)} - skipping")
        return
    
    original_env = dict(os.environ)
    try:
        # Set Vertex provider
        os.environ['CLAUDE_CODE_USE_VERTEX'] = '1'
        os.environ.pop('CLAUDE_CODE_USE_BEDROCK', None)
        
        return test_current_configuration()
        
    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)


def main():
    """Run all available tests."""
    print("🚀 Multi-Provider Claude Code Testing")
    print("=" * 50)
    
    # Test current configuration first
    success = test_current_configuration()
    
    # Test other configurations if credentials are available
    test_anthropic_api_configuration()
    test_bedrock_configuration() 
    test_vertex_configuration()
    
    print("\n✅ Testing complete!")
    print("\n💡 Tips:")
    print("   - Set ANTHROPIC_API_KEY for direct API access")
    print("   - Set CLAUDE_CODE_USE_BEDROCK=1 + AWS vars for Bedrock")
    print("   - Set CLAUDE_CODE_USE_VERTEX=1 + GCP vars for Vertex AI")


if __name__ == "__main__":
    main()
