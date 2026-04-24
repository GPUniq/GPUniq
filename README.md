# GPUniq

![PyPI Version](https://img.shields.io/pypi/v/GPUniq) ![License](https://img.shields.io/badge/license-MIT-blue)

**GPUniq** is a Python SDK and CLI for the [GPUniq](https://gpuniq.com) GPU Meta-Cloud platform.

One account gets you:

- **GPU compute** — browse 5000+ GPUs across multiple providers, deploy by type, or scale to dozens at once with automatic fallback.
- **LLM API** — Claude (Opus 4.7, Sonnet 4.6, Haiku 4.5), GPT-5 family, Gemini 3, Grok 4, plus 30+ open-source models through one key, billed in USD.
- **Image generation** — Nano Banana, Nano Banana Pro / 4K, and Grok 4 Image; text-to-image and image-to-image under the same API.
- **Persistent volumes** — S3-backed storage that survives instance swaps and failures.
- **`gg` CLI** — a single `pip install` gives you a full-featured terminal app for everything above, plus command checkpointing inside GPU instances.

All services share one **USD balance** on your account — no token pools, no separate top-ups.

## Installation

```bash
pip install -U gpuniq
```

Python 3.8+. The `gg` command is available in your terminal immediately after install.

## Quick Start — Python

```python
from gpuniq import GPUniq

client = GPUniq(api_key="gpuniq_your_key_here")

# Browse 5000+ GPUs on the marketplace
gpus = client.marketplace.list(sort_by="price-low")

# Deploy a GPU in one call
deploy = client.gpu_cloud.deploy(gpu_name="RTX_4090", docker_image="pytorch/pytorch:latest")

# Chat with an LLM (billed in USD from your balance)
print(client.llm.chat("claude-haiku-4-5", "Write me a haiku about GPUs"))

# Generate an image and save it locally
client.llm.generate_image(
    "a red cat astronaut on Mars",
    model="nano-banana",
    save_to="cat.png",
)
```

## Quick Start — CLI

```bash
pip install -U gpuniq

gg login                             # paste your API key
gg rent                              # interactive: pick GPU, plan, template, volume
gg open                              # SSH into the rented instance
gg llm "explain CUDA streams"        # one-shot chat
gg image "a red cat astronaut" -o cat.png
```

---

## GPU Products

GPUniq offers three ways to rent GPU compute, each suited to a different use case.

### 1. GPU Marketplace — pick a specific machine

Browse 5000+ GPU servers from multiple providers with detailed specs (VRAM, RAM, disk, network, location, reliability, verification) and rent the exact machine you want.

**Pricing plans:** `minute`, `week`, `month`. Longer commitments give deeper discounts. `hour` and `day` are no longer offered as defaults — use `week` unless you explicitly need per-minute flexibility.

```python
gpus = client.marketplace.list(
    gpu_model=["RTX 4090", "A100"],
    min_vram_gb=24,
    min_inet_speed_mbps=500,
    verified_only=True,
    sort_by="price-low",
    page=1, page_size=20,
)

for agent in gpus["agents"]:
    print(f"{agent['gpu_model']} x{agent['gpu_count']} — ${agent['price_per_hour']}/hr")

order = client.marketplace.create_order(
    agent_id=gpus["agents"][0]["id"],
    pricing_type="week",
    docker_image="vastai/pytorch:cuda-12.9.1-auto",
    ssh_key_ids=[1],
    disk_gb=100,
    volume_id=9,
)
```

### 2. GPU Dex-Cloud — deploy by GPU type

Say which GPU you want and how many — GPUniq picks the best available machine and provisions it automatically.

```python
deploy = client.gpu_cloud.deploy(
    gpu_name="RTX_4090",
    gpu_count=1,
    docker_image="pytorch/pytorch:latest",
    disk_gb=100,
    volume_id=9,
)
```

### 3. GPU Burst — scale to many GPUs with fallback

Request dozens of GPUs at once with fallback types and price caps. If your primary choice isn't available, the platform automatically substitutes.

```python
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
```

### Comparison

| | Marketplace | Dex-Cloud | Burst |
|---|---|---|---|
| **Use case** | Pick a specific machine | Quick deploy by GPU type | Scale to many GPUs |
| **Control** | Full (choose server) | Medium (choose GPU type) | Low (auto-provisioned) |
| **GPU count** | 1 server | 1-8 GPUs | 1-100 GPUs |
| **Fallback GPUs** | No | No | Yes |
| **Best for** | Long training runs | Quick experiments | Distributed training |

---

## Instance Management

```python
# List your instances
instances = client.instances.list(page=1, page_size=20)
archived = client.instances.list_archived()

# Details
details = client.instances.get(task_id=456)

# Lifecycle
client.instances.start(task_id=456)
client.instances.stop(task_id=456)
client.instances.delete(task_id=456)     # fully destroys the instance
client.instances.rename(task_id=456, name="my-training-run")

# Change billing plan mid-rental
client.instances.change_billing_plan(task_id=456, pricing_type="week")

# Container logs, SLA, SSH keys per-instance
logs = client.instances.logs(task_id=456)
sla = client.instances.sla(task_id=456)
client.instances.attach_ssh_key(task_id=456, ssh_key_id=1)
client.instances.detach_ssh_key(task_id=456, key_id=1)
```

---

## Volumes

Persistent S3-backed storage that syncs automatically between your GPU instance and the cloud. Survives instance restarts and replacements.

```python
vol = client.volumes.create(name="my-dataset", size_limit_gb=50)

# Attach at deploy time
client.gpu_cloud.deploy(
    gpu_name="RTX_4090",
    docker_image="pytorch/pytorch:latest",
    volume_id=vol["id"],
)

# Manage
client.volumes.list()
client.volumes.update(volume_id=vol["id"], size_limit_gb=100)
client.volumes.delete(volume_id=vol["id"])

# Sync logs
client.volumes.sync_logs(volume_id=vol["id"])
```

---

## LLM API

Access Claude, GPT-5, Gemini, Grok, and 30+ open-source models through one API, billed directly in USD from `user.balance`. No token packages, no pool conversions.

```python
# One-shot chat
reply = client.llm.chat("claude-haiku-4-5", "Explain transformers in one paragraph.")
print(reply)

# Full completion with message history and parameters
data = client.llm.chat_completion(
    messages=[
        {"role": "system", "content": "You are a terse assistant."},
        {"role": "user",   "content": "What is Gaussian splatting?"},
    ],
    model="claude-haiku-4-5",
    temperature=0.3,
    max_tokens=400,
)
print(data["content"])
print(f"Used {data['tokens_used']} tokens  ·  cost ${data['cost_usd']:.4f}  ·  balance ${data['balance_usd']:.2f}")

# What's available
models = client.llm.models()              # list of text-model slugs
default = client.llm.default_model()
catalog = client.llm.model_catalog()      # full catalog with pricing metadata

# Current USD balance
print(client.llm.balance())

# Persistent chat sessions (multi-turn history stored server-side)
session = client.llm.create_chat_session(model="claude-haiku-4-5", title="Research notes")
client.llm.send_message(chat_id=session["id"], message="Summarise this…")
client.llm.list_chat_sessions()
client.llm.delete_chat_session(chat_id=session["id"])

# Usage history
client.llm.usage_history(limit=50)
```

### OpenAI-compatible endpoint

For tools that expect the OpenAI protocol — Claude Code via LiteLLM, Cursor, Continue.dev, Aider, the official OpenAI SDKs — point them at `https://api.gpuniq.com/v1/openai` with your GPUniq key as the `Authorization: Bearer` token. Byte-identical SSE streaming, every field (tools, tool_choice, response_format, logprobs, seed) forwarded unchanged.

```python
from openai import OpenAI
oai = OpenAI(api_key="gpuniq_your_key", base_url="https://api.gpuniq.com/v1/openai")
oai.chat.completions.create(model="claude-haiku-4-5", messages=[{"role":"user","content":"hi"}])
```

---

## Image Generation

Text-to-image and image-to-image through Nano Banana, Nano Banana Pro / 4K, and Grok 4 Image. Flat per-image billing: you pay only for delivered images.

### Synchronous

Good for quick single images under a few seconds.

```python
result = client.llm.generate_image(
    "a red cat astronaut on Mars",
    model="nano-banana",
    n=1,
    size="1024x1024",
    save_to="cat.png",
)
print(result["saved_paths"])        # → ['cat.png']
print(f"cost ${result['cost_usd']:.4f}  ·  balance ${result['balance_usd']:.2f}")
```

### Async + poll (recommended for Nano Banana)

Higher-resolution / longer-running generations go through a job surface that isn't bound by the upstream proxy's ~100s read timeout. `generate_image_async` handles polling for you.

```python
result = client.llm.generate_image_async(
    "isometric cyberpunk city at dusk",
    model="nano-banana-pro",
    size="2048x2048",
    save_to="city.png",
    on_progress=lambda status, _payload: print("→", status),
)
```

### Image-to-image / editing

Pass reference images as local paths, `data:` URLs, `https://` URLs, raw bytes, or bare base64. The SDK detects local paths and inlines them as data URLs for you.

```python
client.llm.generate_image(
    "same cat but in Tokyo at night, neon reflections",
    model="nano-banana-pro",
    input_images=["cat.png", "reference/mood_board.jpg"],
    size="2048x2048",
    save_to="cat_tokyo.png",
)
```

### Low-level job control

If you want to do your own polling / cancellation UI:

```python
job = client.llm.start_image_job("abstract painting of a neural network", model="nano-banana")
while True:
    status = client.llm.get_image_job(job["job_id"])
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(3)
```

### Image model slugs

| Model | Slug | Price / image | Notes |
|-------|------|---------------|-------|
| Nano Banana | `nano-banana` | $0.0312 | Fast text-to-image & image-to-image, ~1K |
| Nano Banana 2 | `nano-banana-2` | $0.0500 | Quality-value generation up to 2K |
| Nano Banana Pro | `nano-banana-pro` | $0.1072 | Higher quality, ~1K |
| Nano Banana Pro 4K | `nano-banana-pro-4k` | $0.192 | 4K resolution |
| Grok 4 Image | `grok-4-image` | $0.0352 | xAI image generator |

Prices are displayed on `client.llm.model_catalog()` and may change.

---

## CLI — `gg`

The `gg` CLI has two modes:

1. **Client mode** — runs on your local laptop / dev machine. Browse and rent GPUs, SSH into them, chat with LLMs, generate images, manage volumes and SSH keys.
2. **GPU mode** — runs on the GPU instance itself. Command checkpointing, persistent services, and auto-recovery after hardware swaps.

### Client commands (your machine)

```bash
gg login                 # paste your API key (stored in ~/.gpuniq/config.json)
gg status                # show login status and instance summary
gg balance               # current USD balance
gg help                  # same as gg --help
```

#### Rent a GPU

```bash
gg rent
```

Opens a full-width interactive flow:

1. **Filter wizard** — GPU model (2D picker by generation: Datacenter / 50XX / 40XX / 30XX / 20XX / 1660), min GPU count, max price / hr, verified only, sort.
2. **Marketplace table** — paginated, resizes columns to your terminal. On wide terminals you see GPU, CNT, VRAM, RAM, DISK, CPU, NET ↓/↑, LOCATION, RELIA, AVAIL, HOSTING, PRICE, VER.
3. **Billing plan** — week (default) / month / minute.
4. **Template** — PyTorch, ComfyUI, vLLM, Ubuntu VM, or custom image.
5. **Volume** — pick existing, create new, or skip.
6. Confirm. If the offer was taken by someone else between listing and order (410), the picker loops back so you don't lose your plan/volume choices.

Flags (skip any prompt):
```bash
gg rent --gpu "RTX 4090" --count 1 --pricing week \
        --image vastai/pytorch:cuda-12.9.1-auto \
        --disk 100 --max-price 1.50 --verified
```

#### Swap the GPU on a running instance

```bash
gg replace               # pick interactively
gg replace 142           # replace this instance
```

Destroys the old instance (DELETE, not just stop — the provider machine and SSH proxy port are released) and rents a new GPU preserving the original billing plan and volume. Docker image defaults to whatever the old instance was running; you can change it in the same flow.

#### SSH into an instance

```bash
gg open                  # auto-select if only one instance, else arrow-key menu
gg open 142              # connect to a specific instance
```

The CLI scans `~/.ssh/*.pub` and offers to attach a matching key before connecting. It also calls `/v1/instances/{id}/ssh-proxy/ensure` so you always get routed through `ssh.gpuniq.com` — never a bare provider IP — even on older orders whose proxy allocation failed at order time.

#### LLM chat

```bash
gg llm "Write a haiku about CUDA streams"
gg llm                   # interactive REPL: /exit, /clear
gg llm --list-models
gg llm -m claude-haiku-4-5 --temperature 0.3 "..."
```

#### Image generation

```bash
gg image "a red cat astronaut"                  # auto-named PNG in cwd
gg image "variations" -n 4 -o ./renders/        # directory target
gg image "edit" --input cat.png --model nano-banana-pro --size 2048x2048 -o cat_v2.png
```

For Nano Banana slugs, `gg image` automatically uses the async-poll path so you never hit the 100s proxy timeout.

#### Instance list / stop / delete

```bash
gg orders                # list active instances
gg stop                  # interactive or: gg stop 142
```

Use `gg replace` to swap GPUs; use `gg stop` for temporary pause.

#### SSH keys

```bash
gg ssh-keys list
gg ssh-keys add          # uploads ~/.ssh/id_*.pub (interactive pick if multiple)
```

#### Volumes

```bash
gg volumes               # list
gg volumes create my-data --size 50 --description "training set"
gg volumes delete 7
```

### GPU-mode commands (on the instance)

```bash
gg init <token>          # one-time, usually done automatically on deploy
gg python train.py       # run under checkpointing — logs, exit code, duration persisted
gg bash run_pipeline.sh
gg list                  # list checkpoints
gg logs <checkpoint_id> --tail 200
gg services              # list persistent services; gg services rm <id> / clear
gg restart               # re-run all registered services (used during auto-recovery)
gg replay                # re-run commands interrupted by the last instance death
```

When the platform replaces your GPU instance (hardware failure, auto-recovery, `gg replace`), the volume is synced to the new machine and `gg restart` resumes every registered service automatically.

---

## Error handling

```python
from gpuniq import GPUniq, GPUniqError, AuthenticationError, RateLimitError, NotFoundError, ValidationError

client = GPUniq(api_key="gpuniq_your_key")

try:
    instances = client.instances.list()
except AuthenticationError:
    print("Invalid API key")
except RateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
except NotFoundError:
    print("Resource not found")
except ValidationError as e:
    print(f"Bad request: {e}")
except GPUniqError as e:
    print(f"API error: {e.message} (code={e.error_code}, status={e.http_status})")
```

Rate limit: **120 requests/minute** per API key. The SDK automatically retries on 429 (up to 3 times with `Retry-After` backoff).

## Configuration

```python
client = GPUniq(
    api_key="gpuniq_your_key",
    base_url="https://api.gpuniq.com/v1",  # default
    timeout=120,                            # seconds (default 60)
)
```

CLI config lives at `~/.gpuniq/config.json`:

```json
{
  "version": 1,
  "api_key": "gpuniq_...",
  "api_base_url": "https://api.gpuniq.com/v1"
}
```

To point the CLI at a staging environment:

```bash
gg login --api-url https://dev-api.gpuniq.com/v1
```

## Backward compatibility

v1.x code continues to work:

```python
import gpuniq

client = gpuniq.init("gpuniq_your_key")
response = client.request("claude-haiku-4-5", "Hello!")
```

## License

MIT

[gpuniq.com](https://gpuniq.com) | [PyPI](https://pypi.org/project/GPUniq/) | [GitHub](https://github.com/GPUniq/GPUniq)
