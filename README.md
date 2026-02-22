# GPUniq

![PyPI Version](https://img.shields.io/pypi/v/GPUniq) ![License](https://img.shields.io/badge/license-MIT-blue)

**GPUniq** is a Python SDK for the [GPUniq](https://gpuniq.com) GPU Meta-Cloud platform.

GPUniq aggregates GPU capacity from multiple providers into a single platform with automatic provider selection, failover mechanisms, and a snapshot system. Access thousands of GPUs through three deployment modes and a built-in LLM API.

## Installation

```bash
pip install GPUniq
```

## Quick Start

```python
from gpuniq import GPUniq

client = GPUniq(api_key="gpuniq_your_key_here")

# Browse 5000+ GPUs on the marketplace
gpus = client.marketplace.list(sort_by="price-low")

# Deploy a GPU instance in one call
deploy = client.gpu_cloud.deploy(gpu_name="RTX_4090", docker_image="pytorch/pytorch:latest")

# Scale to 8 GPUs with automatic fallback
order = client.burst.create_order(
    docker_image="pytorch/pytorch:latest",
    primary_gpu="RTX_4090",
    gpu_count=8,
)
```

---

## GPU Products

GPUniq offers three ways to rent GPU compute, each suited for different use cases.

### GPU Marketplace

**Full control over individual machines.** Browse 5000+ GPU servers from multiple providers, compare specs and pricing, and rent specific machines. Best for long-running training jobs where you need a particular hardware configuration.

Each server (agent) on the marketplace has detailed specs: GPU model, VRAM, RAM, disk, internet speed, location, reliability score, and verification status. You pick the exact machine and pricing plan.

**Pricing types:** `hour`, `day`, `week`, `month` — longer commitments get lower rates.

```python
# Browse with filters
gpus = client.marketplace.list(
    gpu_model=["RTX 4090", "A100"],
    min_vram_gb=24,
    min_inet_speed_mbps=500,
    verified_only=True,
    sort_by="price-low",    # price-low, price-high, vram, reliability
    page=1,
    page_size=20,
)

print(f"Found {gpus['total_count']} GPUs")
for agent in gpus["agents"]:
    print(f"  {agent['gpu_model']} x{agent['gpu_count']} — ${agent['price_per_hour']}/hr")

# Get marketplace-wide statistics
stats = client.marketplace.statistics(gpu_model=["RTX 4090"])
print(f"Online: {stats['online']}, Min price: ${stats['min_price']}/hr")

# Inspect a specific machine
agent = client.marketplace.get_agent(agent_id=29279811)

# Check availability before ordering
avail = client.marketplace.check_availability(agent_id=29279811)

# Create an order
order = client.marketplace.create_order(
    agent_id=29279811,
    pricing_type="hour",
    docker_image="pytorch/pytorch:latest",
    ssh_key_ids=[1, 2],
    disk_gb=100,
    volume_id=9,            # attach persistent storage
)

# Or create async (non-blocking) and poll status
job = client.marketplace.create_order_async(agent_id=29279811, pricing_type="hour")
status = client.marketplace.get_order_status(job["job_id"])
```

### GPU Dex-Cloud

**Deploy by GPU type, not by machine.** Tell GPUniq which GPU you want and how many — the platform automatically finds the best available machine, provisions it, and returns a ready instance. Best for quick deployments when you don't need to pick a specific server.

Think of it like a traditional cloud provider: select GPU type, click deploy, get an instance.

```python
# See what GPU types are available
gpus = client.gpu_cloud.list_instances(search="4090")

for gpu in gpus["featured"]:
    print(f"{gpu['gpu_name']}: {gpu['available_count']} available, ${gpu['gpu_price_per_gpu_hour_usd']}/hr")

# Check pricing for a specific configuration
pricing = client.gpu_cloud.pricing(
    "RTX_4090",
    gpu_count=2,
    disk_gb=100,
    secure_cloud=False,
)

# Deploy — GPUniq finds the best machine automatically
deploy = client.gpu_cloud.deploy(
    gpu_name="RTX_4090",
    gpu_count=1,
    docker_image="pytorch/pytorch:latest",
    disk_gb=100,
    volume_id=9,            # attach persistent storage
    secure_cloud=False,
)

# Track deployment status
status = client.marketplace.get_order_status(deploy["job_id"])
```

### GPU Burst

**Scale to many GPUs with automatic failback.** Burst mode provisions multiple GPUs across multiple machines simultaneously. If your primary GPU type isn't available, the system automatically falls back to alternative GPU types you specify. Best for distributed training, batch inference, and workloads that need to scale fast.

Key features:
- Request up to 100 GPUs in a single order
- Define fallback GPU types with price caps
- Automatic provisioning across multiple providers
- Per-order billing and run tracking

```python
# Estimate cost before deploying
estimate = client.burst.estimate(
    docker_image="pytorch/pytorch:latest",
    primary_gpu="RTX_4090",
    gpu_count=8,
)

# Check Docker image size
size = client.burst.check_image_size("pytorch/pytorch:latest")

# Create a burst order with fallback GPUs
order = client.burst.create_order(
    docker_image="pytorch/pytorch:latest",
    primary_gpu="RTX_4090",
    gpu_count=8,
    extra_gpus=[
        {"gpu_name": "RTX_3090", "max_price": 0.5},
        {"gpu_name": "A100",     "max_price": 1.2},
    ],
    volume_id=9,
    disk_gb=200,
)

# Manage orders
orders = client.burst.list_orders()
details = client.burst.get_order(order_id=1)
client.burst.start_order(order_id=1)
client.burst.stop_order(order_id=1)
client.burst.delete_order(order_id=1)

# View billing and run history
txns = client.burst.transactions(order_id=1)
runs = client.burst.runs(order_id=1)
```

### Comparison

| | Marketplace | Dex-Cloud | Burst |
|---|---|---|---|
| **Use case** | Pick a specific machine | Quick deploy by GPU type | Scale to many GPUs |
| **Control** | Full (choose exact server) | Medium (choose GPU type) | Low (auto-provisioned) |
| **GPU count** | 1 server | 1-8 GPUs | 1-100 GPUs |
| **Fallback GPUs** | No | No | Yes |
| **Best for** | Long training runs | Quick experiments | Distributed training |

---

## Instance Management

All deployment modes create instances. Once created, manage them the same way:

```python
# List your instances
instances = client.instances.list(page=1, page_size=20)
archived = client.instances.list_archived()

# Instance details
details = client.instances.get(task_id=456)

# Lifecycle
client.instances.start(task_id=456)
client.instances.stop(task_id=456)
client.instances.delete(task_id=456)

# Rename
client.instances.rename(task_id=456, name="my-training-run")

# Container logs
logs = client.instances.logs(task_id=456)

# SLA / uptime monitoring
sla = client.instances.sla(task_id=456)

# SSH keys per instance
keys = client.instances.ssh_keys(task_id=456)
client.instances.attach_ssh_key(task_id=456, ssh_key_id=1)
client.instances.detach_ssh_key(task_id=456, key_id=1)

# Pending deployment jobs
jobs = client.instances.list_pending_jobs()
client.instances.cancel_pending_job(job_id="abc-123")
```

---

## Volumes

Persistent storage that survives instance restarts and can be attached to any instance.

```python
# Pricing
pricing = client.volumes.pricing()

# Create
vol = client.volumes.create(name="my-dataset", size_limit_gb=50, description="Training data")

# List
volumes = client.volumes.list()
archived = client.volumes.list_archived()

# Upload files
client.volumes.upload(volume_id=1, file_path="/local/data.tar.gz", subpath="datasets/")

# Browse files
files = client.volumes.list_files(volume_id=1, subpath="datasets/")

# Download
content = client.volumes.download(volume_id=1, path="datasets/data.tar.gz")
client.volumes.download_to(volume_id=1, remote_path="datasets/data.tar.gz", local_path="./data.tar.gz")

# Delete a file
client.volumes.delete_file(volume_id=1, path="datasets/old.tar.gz")

# Update / delete volume
client.volumes.update(volume_id=1, size_limit_gb=100)
client.volumes.delete(volume_id=1)

# Sync logs
logs = client.volumes.sync_logs(volume_id=1)
client.volumes.cancel_sync(log_id=5)
```

---

## LLM API

Access multiple LLM models (OpenAI, Qwen, DeepSeek, GLM, Llama, and more) through a unified API.

```python
# Simple request
response = client.llm.chat("openai/gpt-oss-120b", "Explain transformers")
print(response)  # string

# Full chat completion with message history
data = client.llm.chat_completion(
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ],
    model="openai/gpt-oss-120b",
    temperature=0.7,
    max_tokens=1000,
)

# Available models
models = client.llm.models()

# Token balance and packages
balance = client.llm.balance()
packages = client.llm.packages()
client.llm.purchase_tokens(package_type="medium")
client.llm.convert_rubles_to_tokens(ruble_amount=100, tokens_to_add=50000)

# Usage history
history = client.llm.usage_history(limit=50)

# Persistent chat sessions
session = client.llm.create_chat_session(model="openai/gpt-oss-120b", title="My Chat")
reply = client.llm.send_message(chat_id=session["id"], message="Hello!")
sessions = client.llm.list_chat_sessions()
client.llm.delete_chat_session(chat_id=session["id"])

# Generate terminal commands from natural language
cmds = client.llm.generate_commands("find all Python files larger than 1MB")
```

---

## Payments

```python
# Deposit via YooKassa
deposit = client.payments.deposit(amount=1000, payment_system="yookassa")
print(deposit["confirmation_url"])  # redirect user here

# Deposit via Stripe
intent = client.payments.create_stripe_intent(amount=1000)
client.payments.check_stripe_payment(payment_id="pi_xxx")

# History
history = client.payments.history()
spending = client.payments.spending_history()
```

## Settings

```python
# SSH keys
keys = client.settings.list_ssh_keys()
new_key = client.settings.create_ssh_key(key_name="my-laptop", public_key="ssh-rsa AAAA...")
client.settings.update_ssh_key(key_id=1, key_name="work-laptop")
client.settings.toggle_ssh_key(key_id=1, is_active=False)
client.settings.delete_ssh_key(key_id=1)

# Telegram notifications
client.settings.link_telegram(telegram_username="myuser")
status = client.settings.telegram_status()
```

---

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

Rate limit: **120 requests/minute** per API key. The SDK automatically retries on 429 (up to 3 times with `Retry-After` backoff).

## Configuration

```python
client = GPUniq(
    api_key="gpuniq_your_key",
    base_url="https://api.gpuniq.com/v1",  # default
    timeout=120,                            # seconds (default: 60)
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

[gpuniq.com](https://gpuniq.com) | [PyPI](https://pypi.org/project/GPUniq/) | [GitHub](https://github.com/GPUniq/GPUniq)
