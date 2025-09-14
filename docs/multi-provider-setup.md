# Multi-Provider Setup for Claude Code

Claude Code now supports multiple providers for accessing Claude models:

1. **Direct Anthropic API** (default)
2. **AWS Bedrock**
3. **Google Vertex AI**

## Configuration

### Direct Anthropic API (Default)

This is the default provider when no other providers are configured.

**Required Environment Variables:**
- `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`

**Example:**
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

### AWS Bedrock

To use AWS Bedrock, set the following environment variables:

**Required Environment Variables:**
- `CLAUDE_CODE_USE_BEDROCK=1` (to enable)
- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

**Example:**
```bash
export CLAUDE_CODE_USE_BEDROCK=1
export AWS_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
```

**Dependencies:**
```bash
pip install boto3
```

### Google Vertex AI

To use Google Vertex AI, set the following environment variables:

**Required Environment Variables:**
- `CLAUDE_CODE_USE_VERTEX=1` (to enable)
- `ANTHROPIC_VERTEX_PROJECT_ID`
- `CLOUD_ML_REGION`

**Example:**
```bash
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID="your-project-id"
export CLOUD_ML_REGION="us-central1"
```

**Dependencies:**
```bash
pip install 'anthropic[vertex]'
```

**Authentication:**
You'll also need to authenticate with Google Cloud. This can be done via:
- Service account key file
- Application Default Credentials (ADC)
- Google Cloud SDK authentication

## Usage

The multi-provider functionality is transparent to existing code. The client factory automatically selects the appropriate provider based on environment variables.

```python
from claudecode.claude_client_factory import create_claude_client

# Automatically selects provider based on environment variables
client = create_claude_client()

# Use the client normally
success, result, error = client.analyze_single_finding(finding)
```

## Validation

Environment variables are automatically validated when creating a client:

```python
from claudecode.env_validation import validate_environment_variables

try:
    validate_environment_variables()
    print("Configuration is valid!")
except ValueError as e:
    print(f"Configuration error: {e}")
```

## Model Support

Different providers support different Claude models:

### Direct Anthropic API
- `claude-3-5-haiku-20241022`
- `claude-3-5-sonnet-20241022`
- `claude-3-opus-20240229`
- `claude-opus-4-1-20250805`

### AWS Bedrock
- `anthropic.claude-3-5-haiku-20241022-v1:0`
- `anthropic.claude-3-5-sonnet-20241022-v2:0`
- `anthropic.claude-3-opus-20240229-v1:0`

### Google Vertex AI
- `claude-3-5-haiku@20241022`
- `claude-3-5-sonnet-v2@20241022`
- `claude-3-opus@20240229`

The client automatically maps between model names and provider-specific identifiers.

## Error Handling

Each provider has specific error handling:

- **Rate limiting**: Progressive backoff with different keywords per provider
- **Authentication**: Provider-specific authentication error messages
- **Quotas**: Automatic retry with exponential backoff

## Examples

See `examples/multi-provider-example.py` for a complete example demonstrating:
- Environment validation
- Client creation
- API access validation
- Security finding analysis
