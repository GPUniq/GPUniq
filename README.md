# GPUniq

Python client for GPUniq LLM API.

## Installation

```bash
pip install GPUniq
```

## Usage

### Basic Example

```python
import gpuniq

# Initialize client with your API key
client = gpuniq.init("gpuniq_your_api_key_here")

# Send a simple request
response = client.request(
    "openai/gpt-oss-120b",
    "Привет, как дела?"
)
print(response)
```

### Multi-turn Conversation

```python
import gpuniq

client = gpuniq.init("gpuniq_your_api_key_here")

# Send multiple messages
response = client.chat(
    model="openai/gpt-oss-120b",
    messages=[
        {"role": "user", "content": "Привет!"},
        {"role": "assistant", "content": "Здравствуйте! Чем могу помочь?"},
        {"role": "user", "content": "Расскажи о GPUniq"}
    ]
)

print(response['content'])
print(f"Tokens used: {response['tokens_used']}")
```

### Error Handling

```python
import gpuniq

client = gpuniq.init("gpuniq_your_api_key_here")

try:
    response = client.request("openai/gpt-oss-120b", "Hello!")
    print(response)
except gpuniq.GPUniqError as e:
    print(f"Error: {e.message}")
    print(f"Error code: {e.error_code}")
    print(f"HTTP status: {e.http_status}")
```

## API Reference

### `gpuniq.init(api_key: str) -> GPUniqClient`

Initialize and return a GPUniq client.

**Parameters:**
- `api_key` (str): Your GPUniq API key (starts with 'gpuniq_')

**Returns:**
- `GPUniqClient`: Initialized client instance

### `GPUniqClient.request(model: str, message: str, role: str = "user", timeout: int = 30) -> str`

Send a simple request to the LLM.

**Parameters:**
- `model` (str): Model identifier (e.g., 'openai/gpt-oss-120b')
- `message` (str): Message content to send
- `role` (str, optional): Message role (default: 'user')
- `timeout` (int, optional): Request timeout in seconds (default: 30)

**Returns:**
- `str`: Response content from the LLM

### `GPUniqClient.chat(model: str, messages: List[Dict[str, str]], timeout: int = 30) -> Dict[str, Any]`

Send a multi-turn conversation to the LLM.

**Parameters:**
- `model` (str): Model identifier
- `messages` (List[Dict]): List of message dicts with 'role' and 'content' keys
- `timeout` (int, optional): Request timeout in seconds (default: 30)

**Returns:**
- `dict`: Full API response data including content, tokens_used, tokens_remaining, etc.

## License

MIT
