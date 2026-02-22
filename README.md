# GPUniq

![PyPI Version](https://img.shields.io/pypi/v/GPUniq) ![License](https://img.shields.io/badge/license-MIT-blue)

**GPUniq** is a Python SDK for the GPUniq GPU Meta-Cloud platform — rent GPUs, deploy containers, manage volumes, and use LLM models through a unified API.

## Installation

```bash
pip install GPUniq
```

## Quick Start

```python
from gpuniq import GPUniq

client = GPUniq(api_key="gpuniq_your_key_here")

# Browse GPU marketplace
gpus = client.marketplace.list(sort_by="price-low", page_size=10)

# Rent a GPU
order = client.marketplace.create_order(agent_id=123, pricing_type="hour")

# Manage instances
instances = client.instances.list()
client.instances.start(task_id=456)
client.instances.stop(task_id=456)

# LLM chat
response = client.llm.chat("openai/gpt-oss-120b", "Hello!")
print(response)
```

## Modules

### Marketplace

Browse available GPUs with filters and create rental orders.

```python
# List GPUs with filters
gpus = client.marketplace.list(
    gpu_model=["RTX 4090"],
    min_vram_gb=24,
    sort_by="price-low",
    page=1,
    page_size=20,
)

# Get offer details
agent = client.marketplace.get_agent(agent_id=123)

# Check availability
available = client.marketplace.check_availability(agent_id=123)

# Create order (async with polling)
job = client.marketplace.create_order_async(
    agent_id=123,
    pricing_type="hour",
    docker_image="pytorch/pytorch:latest",
    ssh_key_ids=[1, 2],
    disk_gb=100,
)
status = client.marketplace.get_order_status(job["job_id"])
```

### Instances

Manage your rented GPU instances.

```python
# List active instances
instances = client.instances.list(page=1, page_size=20)

# Get instance details
details = client.instances.get(task_id=456)

# Start / stop / delete
client.instances.start(task_id=456)
client.instances.stop(task_id=456)
client.instances.delete(task_id=456)

# Rename
client.instances.rename(task_id=456, name="my-training-run")

# Get logs and SLA
logs = client.instances.logs(task_id=456)
sla = client.instances.sla(task_id=456)

# SSH key management per instance
client.instances.attach_ssh_key(task_id=456, ssh_key_id=1)
client.instances.detach_ssh_key(task_id=456, key_id=1)
```

### Volumes

Persistent storage that can be attached to instances.

```python
# Create a volume
vol = client.volumes.create(name="my-dataset", size_limit_gb=50)

# List volumes
volumes = client.volumes.list()

# Upload a file
client.volumes.upload(volume_id=1, file_path="/local/data.tar.gz", subpath="datasets/")

# List files
files = client.volumes.list_files(volume_id=1, subpath="datasets/")

# Download a file
content = client.volumes.download(volume_id=1, path="datasets/data.tar.gz")
# Or save directly to disk
client.volumes.download_to(volume_id=1, remote_path="datasets/data.tar.gz", local_path="./data.tar.gz")

# Delete
client.volumes.delete(volume_id=1)
```

### GPU Cloud

Deploy GPU instances by GPU type (simplified marketplace).

```python
# Browse available GPU types
gpus = client.gpu_cloud.list_instances(search="4090")

# Check pricing
pricing = client.gpu_cloud.pricing("RTX_4090", gpu_count=2, disk_gb=100)

# Deploy
deploy = client.gpu_cloud.deploy(
    gpu_name="RTX_4090",
    gpu_count=1,
    docker_image="pytorch/pytorch:latest",
    disk_gb=100,
)
```

### Burst

Multi-GPU burst deployments with fallback GPU support.

```python
# Create a burst order
order = client.burst.create_order(
    docker_image="pytorch/pytorch:latest",
    primary_gpu="RTX_4090",
    gpu_count=8,
    extra_gpus=[{"gpu_name": "RTX_3090", "max_price": 0.5}],
    disk_gb=200,
)

# Manage orders
orders = client.burst.list_orders()
client.burst.start_order(order_id=1)
client.burst.stop_order(order_id=1)

# View billing
txns = client.burst.transactions(order_id=1)
runs = client.burst.runs(order_id=1)
```

### LLM

Chat completions, token management, and chat sessions.

```python
# Simple chat
response = client.llm.chat("openai/gpt-oss-120b", "Explain transformers")

# Full chat completion with history
data = client.llm.chat_completion(
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ],
    model="openai/gpt-oss-120b",
    temperature=0.7,
    max_tokens=1000,
)

# Token balance
balance = client.llm.balance()

# Available models
models = client.llm.models()

# Chat sessions (persistent)
session = client.llm.create_chat_session(model="openai/gpt-oss-120b", title="My Chat")
reply = client.llm.send_message(chat_id=session["id"], message="Hello!")
sessions = client.llm.list_chat_sessions()
```

### Payments

Deposit funds and view spending history.

```python
# Create deposit
deposit = client.payments.deposit(amount=1000, payment_system="yookassa")
print(deposit["confirmation_url"])

# View history
history = client.payments.history()
spending = client.payments.spending_history()
```

### Settings

SSH key management and Telegram notifications.

```python
# SSH keys
keys = client.settings.list_ssh_keys()
new_key = client.settings.create_ssh_key(
    key_name="my-laptop",
    public_key="ssh-rsa AAAA...",
)
client.settings.delete_ssh_key(key_id=1)

# Telegram
client.settings.link_telegram(telegram_username="myuser")
status = client.settings.telegram_status()
```

## Error Handling

```python
from gpuniq import GPUniq, GPUniqError, AuthenticationError, RateLimitError, NotFoundError

client = GPUniq(api_key="gpuniq_your_key")

try:
    instances = client.instances.list()
except AuthenticationError:
    print("Invalid API key")
except RateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
except NotFoundError:
    print("Resource not found")
except GPUniqError as e:
    print(f"API error: {e.message} (code={e.error_code}, status={e.http_status})")
```

## Configuration

```python
client = GPUniq(
    api_key="gpuniq_your_key",
    base_url="https://api.gpuniq.com/v1",  # default
    timeout=120,  # request timeout in seconds (default: 60)
)
```

## Backward Compatibility

v1.x code continues to work:

```python
import gpuniq

client = gpuniq.init("gpuniq_your_key")
response = client.request("openai/gpt-oss-120b", "Hello!")
```

## License

MIT
