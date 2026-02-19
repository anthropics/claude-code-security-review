#!/usr/bin/env python3
"""
Example demonstrating multi-provider Claude Code support.

This script shows how to use Claude Code with different providers:
- Direct Anthropic API
- AWS Bedrock
- Google Vertex AI
"""

import os
from claudecode.claude_client_factory import create_claude_client
from claudecode.env_validation import validate_environment_variables


def main():
    """Demonstrate multi-provider Claude Code functionality."""
    print("Claude Code Multi-Provider Example")
    print("=" * 40)
    
    try:
        # Validate environment variables
        print("Validating environment variables...")
        validate_environment_variables()
        print("✓ Environment validation passed")
        
        # Create client (automatically selects provider based on env vars)
        print("\nCreating Claude client...")
        client = create_claude_client()
        print(f"✓ Created client: {type(client).__name__}")
        
        # Validate API access
        print("\nValidating API access...")
        success, error_msg = client.validate_api_access()
        if success:
            print("✓ API access validation successful")
        else:
            print(f"✗ API access validation failed: {error_msg}")
            return
        
        # Example analysis
        print("\nTesting analysis functionality...")
        example_finding = {
            "rule": "test-rule",
            "file": "example.py",
            "line": 42,
            "severity": "HIGH",
            "message": "Example security finding for testing"
        }
        
        success, result, error_msg = client.analyze_single_finding(
            example_finding
        )
        
        if success:
            print("✓ Analysis completed successfully")
            print(f"Result: {result}")
        else:
            print(f"✗ Analysis failed: {error_msg}")
            
    except ValueError as e:
        print(f"✗ Configuration error: {e}")
    except ImportError as e:
        print(f"✗ Import error: {e}")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")


if __name__ == "__main__":
    main()
