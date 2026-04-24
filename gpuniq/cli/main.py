import argparse
import glob
import os
import sys
import time
from datetime import datetime
from getpass import getpass
from typing import List, Optional

from gpuniq.cli.api import CheckpointAPI
from gpuniq.cli.client_api import ClientAPI
from gpuniq.cli.client_config import ClientConfig, DEFAULT_API_URL as CLIENT_DEFAULT_API_URL
from gpuniq.cli.config import DEFAULT_API_URL, DEFAULT_GG_DIR, GGConfig
from gpuniq.cli.runner import CommandRunner
from gpuniq.cli.services import ServiceStore
from gpuniq.cli.store import CommandStore


def _try_auto_init(gg_dir: str) -> bool:
    """Auto-initialize from GG_TOKEN env var if config doesn't exist."""
    token = os.environ.get("GG_TOKEN")
    if not token:
        return False

    api_url = os.environ.get("GG_API_URL", DEFAULT_API_URL)
    api = CheckpointAPI(api_url, token)
    result = api.verify_token()
    if not result:
        print("[gg] Warning: GG_TOKEN is set but token verification failed.", file=sys.stderr)
        return False

    cfg = GGConfig(gg_dir)
    cfg.save(
        token=token,
        api_base_url=api_url,
        task_id=result["task_id"],
        instance_name=result.get("instance_name"),
    )
    print(f"[gg] Auto-initialized for task {result['task_id']}", file=sys.stderr)
    return True


def _get_config(gg_dir: str) -> GGConfig:
    cfg = GGConfig(gg_dir)
    if not cfg.exists():
        if _try_auto_init(gg_dir):
            return cfg
        print(
            f"Error: gg not initialized.\n"
            f"Run: gg init <token>",
            file=sys.stderr,
        )
        sys.exit(1)
    return cfg


def _get_store(cfg: GGConfig) -> CommandStore:
    return CommandStore(cfg.manifest_path, cfg.logs_dir)


def _get_services(cfg: GGConfig) -> ServiceStore:
    return ServiceStore(cfg.services_path)


def _get_api(cfg: GGConfig) -> CheckpointAPI:
    data = cfg.load()
    return CheckpointAPI(data["api_base_url"], data["token"])


# ─── Commands ────────────────────────────────────────────────────────────────


def cmd_init(args):
    token = args.token
    api_url = args.api_url or DEFAULT_API_URL
    gg_dir = args.gg_dir or DEFAULT_GG_DIR

    # Verify token with backend
    api = CheckpointAPI(api_url, token)
    result = api.verify_token()
    if not result:
        print("Error: invalid token or backend unreachable.", file=sys.stderr)
        sys.exit(1)

    task_id = result["task_id"]

    cfg = GGConfig(gg_dir)
    cfg.save(
        token=token,
        api_base_url=api_url,
        task_id=task_id,
        instance_name=result.get("instance_name"),
    )

    print(f"Initialized gg for task {task_id}")
    print(f"Config: {cfg.config_path}")


def cmd_run(args):
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    store = _get_store(cfg)
    services = _get_services(cfg)
    api = _get_api(cfg)
    runner = CommandRunner(cfg.logs_dir)

    command = " ".join(args.command)
    if not command.strip():
        print("Error: no command specified.", file=sys.stderr)
        sys.exit(1)

    # Register as persistent service (auto-restart on GPU replacement)
    cwd = os.getcwd()
    svc = services.add(command, cwd)
    print(f"[gg] Registered service {svc['id']}: {command} (dir: {cwd})")

    # Prepare env snapshot (selected vars)
    env_keys = ["PATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "HOME", "USER"]
    env_snapshot = {k: os.environ.get(k, "") for k in env_keys if k in os.environ}

    # Run the command
    result = runner.run(command)

    # Build checkpoint data
    checkpoint = {
        **result,
        "env_snapshot": env_snapshot,
        "synced": False,
    }

    # Save locally
    store.add_checkpoint(checkpoint)

    # Sync to backend
    create_data = {
        "checkpoint_id": result["checkpoint_id"],
        "command": result["command"],
        "status": "running",
        "started_at": result["started_at"],
        "working_dir": result["working_dir"],
        "env_snapshot": env_snapshot,
    }
    api.create_checkpoint(create_data)

    update_data = {
        "status": result["status"],
        "exit_code": result["exit_code"],
        "finished_at": result["finished_at"],
        "duration_seconds": result["duration_seconds"],
        "log_size_bytes": result["log_size_bytes"],
    }
    api.update_checkpoint(result["checkpoint_id"], update_data)

    # Mark as synced
    store.update_checkpoint(result["checkpoint_id"], {"synced": True})

    # Print summary
    print(f"\n[gg] {result['status']} (exit {result['exit_code']}) in {result['duration_seconds']}s")
    print(f"[gg] checkpoint: {result['checkpoint_id']}")

    sys.exit(result["exit_code"])


def cmd_list(args):
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    store = _get_store(cfg)
    checkpoints = store.get_checkpoints()

    if not checkpoints:
        print("No checkpoints yet. Run a command with: gg <command>")
        return

    # Print table
    header = f"{'ID':<12} {'STATUS':<12} {'EXIT':<6} {'DURATION':<12} {'COMMAND'}"
    print(header)
    print("-" * len(header))

    for cp in checkpoints:
        cp_id = cp["checkpoint_id"][:8] + "..."
        status = cp.get("status", "?")
        exit_code = cp.get("exit_code", "?")
        duration = cp.get("duration_seconds")
        if duration is not None:
            if duration >= 3600:
                dur_str = f"{duration / 3600:.1f}h"
            elif duration >= 60:
                dur_str = f"{duration / 60:.0f}m {duration % 60:.0f}s"
            else:
                dur_str = f"{duration:.1f}s"
        else:
            dur_str = "running"
        command = cp.get("command", "")
        if len(command) > 60:
            command = command[:57] + "..."
        print(f"{cp_id:<12} {status:<12} {str(exit_code):<6} {dur_str:<12} {command}")


def cmd_logs(args):
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    store = _get_store(cfg)

    # Resolve checkpoint_id (support short prefix)
    target = args.checkpoint_id
    checkpoints = store.get_checkpoints()
    matched = [cp for cp in checkpoints if cp["checkpoint_id"].startswith(target)]

    if not matched:
        print(f"Error: no checkpoint matching '{target}'", file=sys.stderr)
        sys.exit(1)
    if len(matched) > 1:
        print(f"Error: ambiguous prefix '{target}', matches {len(matched)} checkpoints", file=sys.stderr)
        sys.exit(1)

    log_path = store.log_path(matched[0]["checkpoint_id"])
    if not os.path.isfile(log_path):
        print(f"Error: log file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    tail_n = args.tail

    if tail_n:
        # Read last N lines
        with open(log_path, "rb") as f:
            lines = f.readlines()
            for line in lines[-tail_n:]:
                sys.stdout.buffer.write(line)
    else:
        # Full output
        with open(log_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)


def cmd_replay(args):
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    store = _get_store(cfg)
    checkpoints = store.get_checkpoints()

    # Find unfinished commands (were running when VPS died)
    replayable = [
        cp for cp in checkpoints
        if cp.get("status") in ("running", "killed")
    ]

    if not replayable:
        print("[gg] No commands to replay.")
        return

    print(f"[gg] Found {len(replayable)} command(s) to replay:")
    for cp in replayable:
        print(f"  {cp['checkpoint_id'][:8]}... {cp['command']}")

    replayed = 0
    for cp in replayable:
        command = cp["command"]
        cwd = cp.get("working_dir", "/workspace")

        # Mark old checkpoint as "replayed" so it won't be picked up again
        store.update_checkpoint(cp["checkpoint_id"], {"status": "replayed"})

        # Spawn detached gg process — it handles its own log capture via PTY
        import subprocess
        subprocess.Popen(
            f"gg {command}",
            shell=True,
            cwd=cwd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        replayed += 1
        print(f"[gg] Replayed: {command}")

    print(f"[gg] {replayed} command(s) replayed in background.")


def cmd_status(args):
    """Show CLI status: client login (gg login) and/or GPU-side init (gg init)."""
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    client_cfg = ClientConfig()
    server_cfg = GGConfig(gg_dir)

    if not client_cfg.exists() and not server_cfg.exists():
        print("Not logged in. Run: gg login")
        print("Or initialize on a GPU: gg init <token>")
        sys.exit(1)

    if client_cfg.exists():
        try:
            data = client_cfg.load()
        except Exception as e:
            print(f"Error: could not read client config: {e}", file=sys.stderr)
            sys.exit(1)

        api_url = data.get("api_base_url", "?")
        api_key = data.get("api_key", "")
        masked = (api_key[:6] + "…" + api_key[-4:]) if len(api_key) > 14 else "set"

        # Probe the API to verify the key is still valid
        api = ClientAPI(api_url, api_key)
        verify = api.verify_key()
        connected = verify is not None

        print("CLI Login (gg login)")
        print(f"  Status:     {'connected' if connected else 'unreachable / invalid key'}")
        print(f"  API URL:    {api_url}")
        print(f"  API key:    {masked}")
        if connected:
            payload = (verify or {}).get("data", {}) or {}
            total = payload.get("total_count", len(payload.get("instances", []) or []))
            running = sum(
                1 for i in (payload.get("instances", []) or []) if i.get("status") == "running"
            )
            running_label = f" ({running} running on this page)" if running else ""
            print(f"  Instances:  {total} total{running_label}")

    if server_cfg.exists():
        store = _get_store(server_cfg)
        data = server_cfg.load()
        checkpoints = store.get_checkpoints()
        total_size = store.total_log_size()
        size_mb = total_size / (1024 * 1024)

        if client_cfg.exists():
            print()
        print("GPU-side init (gg init)")
        print(f"  Task ID:      {data.get('task_id', '?')}")
        print(f"  Instance:     {data.get('instance_name', '-')}")
        print(f"  API URL:      {data.get('api_base_url', '?')}")
        print(f"  Initialized:  {data.get('initialized_at', '?')}")
        print(f"  Checkpoints:  {len(checkpoints)}")
        print(f"  Total logs:   {size_mb:.1f} MB")


def cmd_services(args):
    """List or remove persistent services."""
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    services = _get_services(cfg)

    action = getattr(args, "services_action", None)

    if action == "rm":
        if services.remove(args.service_id):
            print(f"[gg] Removed service {args.service_id}")
        else:
            print(f"Error: no service matching '{args.service_id}'", file=sys.stderr)
            sys.exit(1)
        return

    if action == "clear":
        count = services.clear()
        print(f"[gg] Cleared {count} service(s)")
        return

    # Default: list
    entries = services.get_all()
    if not entries:
        print("No persistent services registered. Run a command with: gg <command>")
        return

    header = f"{'ID':<10} {'DIR':<30} {'COMMAND'}"
    print(header)
    print("-" * len(header))
    for svc in entries:
        cmd = svc["command"]
        if len(cmd) > 50:
            cmd = cmd[:47] + "..."
        d = svc["working_dir"]
        if len(d) > 28:
            d = "..." + d[-25:]
        print(f"{svc['id']:<10} {d:<30} {cmd}")


def cmd_restart(args):
    """Restart all registered persistent services in background."""
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    services = _get_services(cfg)
    store = _get_store(cfg)
    entries = services.get_all()

    if not entries:
        print("[gg] No services to restart.")
        return

    # Mark any running/killed checkpoints as "replayed" to prevent
    # gg replay from starting them again (restart is the superset)
    checkpoints = store.get_checkpoints()
    for cp in checkpoints:
        if cp.get("status") in ("running", "killed"):
            store.update_checkpoint(cp["checkpoint_id"], {"status": "replayed"})

    print(f"[gg] Restarting {len(entries)} service(s):")
    import subprocess

    started = 0
    for svc in entries:
        command = svc["command"]
        cwd = svc.get("working_dir", "/workspace")

        print(f"  [{svc['id']}] {command} (dir: {cwd})")
        subprocess.Popen(
            f"gg {command}",
            shell=True,
            cwd=cwd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started += 1

    print(f"[gg] {started} service(s) restarted in background.")


# ─── Client-side commands (run on user's machine) ────────────────────────────


def _get_client_config() -> ClientConfig:
    cfg = ClientConfig()
    if not cfg.exists():
        print("Error: not logged in. Run: gg login", file=sys.stderr)
        sys.exit(1)
    return cfg


def _get_client_api(cfg: ClientConfig) -> ClientAPI:
    data = cfg.load()
    api = ClientAPI(data["api_base_url"], data["api_key"])
    api.send_heartbeat()
    return api


def _find_local_ssh_pubkeys() -> list:
    """Find SSH public keys on the local machine."""
    ssh_dir = os.path.expanduser("~/.ssh")
    keys = []
    for pattern in ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub"]:
        matches = glob.glob(os.path.join(ssh_dir, pattern))
        keys.extend(matches)
    return keys


def _extract_instance_info(inst: dict) -> dict:
    """Extract relevant fields from an instance response."""
    container = inst.get("container", {}) or {}
    agent = inst.get("agent", {}) or {}
    gpu = agent.get("gpu", {}) or {}
    billing = inst.get("billing", {}) or {}

    gpu_name = gpu.get("model", "Unknown GPU")
    gpu_count = gpu.get("count", 1)
    gpu_label = f"{gpu_name} x{gpu_count}" if gpu_count > 1 else gpu_name

    return {
        "id": inst.get("id"),
        "name": inst.get("name", ""),
        "status": inst.get("status", "unknown"),
        "gpu_label": gpu_label,
        "ssh_host": container.get("ssh_host"),
        "ssh_port": container.get("ssh_port"),
        "ssh_username": container.get("ssh_username", "root"),
        "ssh_command": container.get("ssh_command", ""),
        "price_per_hour": billing.get("price_per_hour_display") or billing.get("price_per_hour"),
        "volume_syncing": inst.get("volume_syncing", False),
    }


def cmd_login(args):
    api_key = args.api_key
    api_url = args.api_url or CLIENT_DEFAULT_API_URL

    if not api_key:
        api_key = getpass("Enter your GPUniq API key: ")

    if not api_key or not api_key.strip():
        print("Error: API key cannot be empty.", file=sys.stderr)
        sys.exit(1)

    api_key = api_key.strip()

    # Verify key
    api = ClientAPI(api_url, api_key)
    result = api.verify_key()
    if not result:
        print("Error: invalid API key or server unreachable.", file=sys.stderr)
        sys.exit(1)

    cfg = ClientConfig()
    cfg.save(api_key=api_key, api_base_url=api_url)

    print("Logged in successfully!")
    print(f"Config saved to: {cfg.config_path}")


def cmd_orders(args):
    cfg = _get_client_config()
    api = _get_client_api(cfg)
    data = api.get_instances()

    if not data:
        print("Error: could not fetch instances.", file=sys.stderr)
        sys.exit(1)

    instances = data.get("instances", [])
    if not instances:
        print("No active instances. Rent a GPU at https://gpuniq.com")
        return

    # Filter to running/active only for display
    active = [i for i in instances if i.get("status") in ("running", "starting", "provisioning")]
    if not active:
        print("No running instances found.")
        return

    # Print table
    header = f"{'ID':<8} {'GPU':<25} {'STATUS':<14} {'PRICE/HR':<12} {'SSH COMMAND'}"
    print(header)
    print("-" * len(header))

    for inst in active:
        info = _extract_instance_info(inst)
        inst_id = str(info["id"])
        gpu = info["gpu_label"]
        if len(gpu) > 23:
            gpu = gpu[:20] + "..."
        status = info["status"]
        price = ""
        if info["price_per_hour"] is not None:
            price = f"${float(info['price_per_hour']):.2f}"

        ssh_cmd = ""
        if info["volume_syncing"]:
            ssh_cmd = "(syncing volume...)"
        elif info["ssh_host"] and info["ssh_port"]:
            ssh_cmd = f"ssh {info['ssh_username']}@{info['ssh_host']} -p {info['ssh_port']}"

        print(f"{inst_id:<8} {gpu:<25} {status:<14} {price:<12} {ssh_cmd}")


def cmd_open(args):
    cfg = _get_client_config()
    api = _get_client_api(cfg)
    data = api.get_instances()

    if not data:
        print("Error: could not fetch instances.", file=sys.stderr)
        sys.exit(1)

    instances = data.get("instances", [])
    # Filter to running instances with SSH available
    running = []
    for inst in instances:
        if inst.get("status") != "running":
            continue
        info = _extract_instance_info(inst)
        if info["ssh_host"] and info["ssh_port"] and not info["volume_syncing"]:
            running.append(info)

    if not running:
        print("No running instances with SSH available.", file=sys.stderr)
        print("Check your instances: gg orders")
        sys.exit(1)

    target = None

    # If instance ID provided as argument
    if args.instance_id:
        target_id = args.instance_id
        matched = [i for i in running if str(i["id"]) == str(target_id)]
        if not matched:
            print(f"Error: no running instance with ID {target_id}", file=sys.stderr)
            sys.exit(1)
        target = matched[0]
    elif len(running) == 1:
        # Single instance — connect directly
        target = running[0]
    else:
        # Multiple instances — interactive selection
        try:
            from InquirerPy import inquirer
        except ImportError:
            print("Error: InquirerPy is required for interactive selection.", file=sys.stderr)
            print("Install it: pip install InquirerPy", file=sys.stderr)
            # Fallback: show list and ask for ID
            print("\nMultiple instances available:")
            for info in running:
                price_str = f"${float(info['price_per_hour']):.2f}/hr" if info["price_per_hour"] else ""
                print(f"  #{info['id']}  {info['gpu_label']}  ({info['status']})  {price_str}")
            print("\nRun: gg open <instance_id>")
            sys.exit(1)

        choices = []
        for info in running:
            price_str = f"${float(info['price_per_hour']):.2f}/hr" if info["price_per_hour"] else ""
            label = f"#{info['id']}  {info['gpu_label']}  ({info['status']})  {price_str}"
            choices.append({"name": label, "value": info})

        target = inquirer.select(
            message="Select instance:",
            choices=choices,
        ).execute()

    if not target:
        sys.exit(1)

    print(f"[gg] Connecting to #{target['id']} ({target['gpu_label']})...")

    # Check for local SSH keys and offer to attach
    _maybe_attach_ssh_key(api, target)

    # Prefer ssh.gpuniq.com proxy over the direct provider IP. For instances
    # whose proxy allocation failed at order time, ask the backend to allocate
    # one now; fall back to the stored host on error.
    proxy = _ensure_proxy_host(api, target)
    ssh_user = proxy.get("ssh_username") or target["ssh_username"]
    ssh_host = proxy.get("ssh_host") or target["ssh_host"]
    ssh_port = str(proxy.get("ssh_port") or target["ssh_port"])

    ssh_args = ["ssh", f"{ssh_user}@{ssh_host}", "-p", ssh_port]
    print(f"[gg] {' '.join(ssh_args)}\n")

    # Replace current process with SSH
    os.execvp("ssh", ssh_args)


def _ensure_proxy_host(api: ClientAPI, target: dict) -> dict:
    """If the instance's ssh_host looks like a direct IP, ask the backend to
    allocate an ssh.gpuniq.com proxy port for it. Returns a dict with ssh_host /
    ssh_port / ssh_username (possibly empty — caller falls back to direct)."""
    host = (target.get("ssh_host") or "").strip()
    if host.endswith("gpuniq.com"):
        return {}
    result = api.ensure_ssh_proxy(target["id"])
    if result:
        return result
    return {}


def _maybe_attach_ssh_key(api: ClientAPI, target: dict):
    """Check for local SSH keys and offer to attach them to the instance."""
    local_keys = _find_local_ssh_pubkeys()
    if not local_keys:
        return

    # Get existing SSH keys on this instance
    instance_keys = api.get_instance_ssh_keys(target["id"])
    if instance_keys is None:
        return  # Could not fetch, skip silently

    # Read local public key content
    key_path = local_keys[0]  # Prefer first found (ed25519 > rsa > ecdsa)
    try:
        with open(key_path, "r") as f:
            local_pubkey = f.read().strip()
    except Exception:
        return

    # Check if already attached
    for k in instance_keys:
        if k.get("is_attached"):
            pub = k.get("public_key", "")
            if pub and local_pubkey.startswith(pub[:40]):
                return  # Already attached

    # Check if the key exists in user's keys (not attached to this instance)
    unattached = [k for k in instance_keys if not k.get("is_attached")]
    matching_key = None
    for k in unattached:
        pub = k.get("public_key", "")
        if pub and local_pubkey.startswith(pub[:40]):
            matching_key = k
            break

    if not matching_key:
        return  # Key not in user's account, can't attach

    key_name = os.path.basename(key_path)
    print(f"[gg] Found local SSH key: {key_name}")

    try:
        from InquirerPy import inquirer
        attach = inquirer.confirm(
            message=f"Attach {key_name} to instance #{target['id']}?",
            default=True,
        ).execute()
    except ImportError:
        # Fallback to simple input
        answer = input(f"Attach {key_name} to instance #{target['id']}? [Y/n] ").strip().lower()
        attach = answer in ("", "y", "yes")

    if attach:
        if api.attach_ssh_key(target["id"], matching_key["id"]):
            print("[gg] SSH key attached successfully.")
        else:
            print("[gg] Could not attach SSH key. Continuing with password auth...")


def cmd_balance(args):
    cfg = _get_client_config()
    api = _get_client_api(cfg)
    data = api.get_instances(page=1, page_size=1)

    if not data:
        print("Error: could not fetch account info.", file=sys.stderr)
        sys.exit(1)

    instances = data.get("instances", [])
    if instances:
        billing = instances[0].get("billing", {})
        balance = billing.get("user_balance_display") or billing.get("user_balance")
        currency = billing.get("currency", "USD")
        symbol = "$" if currency != "RUB" else "₽"
        if balance is not None:
            print(f"{symbol}{float(balance):.2f}")
        else:
            print("Balance: unavailable")
    else:
        print("No instances found. Check your balance at https://gpuniq.com")


def cmd_stop(args):
    cfg = _get_client_config()
    api = _get_client_api(cfg)
    data = api.get_instances()

    if not data:
        print("Error: could not fetch instances.", file=sys.stderr)
        sys.exit(1)

    instances = data.get("instances", [])
    running = [i for i in instances if i.get("status") in ("running", "starting")]

    if not running:
        print("No running instances to stop.")
        return

    target = None

    if args.instance_id:
        matched = [i for i in running if str(i.get("id")) == str(args.instance_id)]
        if not matched:
            print(f"Error: no running instance with ID {args.instance_id}", file=sys.stderr)
            sys.exit(1)
        target = matched[0]
    elif len(running) == 1:
        target = running[0]
    else:
        try:
            from InquirerPy import inquirer
        except ImportError:
            print("Multiple running instances. Specify ID: gg stop <instance_id>")
            for i in running:
                info = _extract_instance_info(i)
                print(f"  #{info['id']}  {info['gpu_label']}  ({info['status']})")
            sys.exit(1)

        choices = []
        for i in running:
            info = _extract_instance_info(i)
            price_str = f"${float(info['price_per_hour']):.2f}/hr" if info["price_per_hour"] else ""
            label = f"#{info['id']}  {info['gpu_label']}  ({info['status']})  {price_str}"
            choices.append({"name": label, "value": i})

        target = inquirer.select(
            message="Select instance to stop:",
            choices=choices,
        ).execute()

    if not target:
        sys.exit(1)

    info = _extract_instance_info(target)
    print(f"Stopping #{info['id']} ({info['gpu_label']})...")

    # Confirm
    try:
        from InquirerPy import inquirer
        confirm = inquirer.confirm(
            message=f"Stop instance #{info['id']}? This will terminate the machine.",
            default=False,
        ).execute()
    except ImportError:
        answer = input(f"Stop instance #{info['id']}? [y/N] ").strip().lower()
        confirm = answer in ("y", "yes")

    if not confirm:
        print("Cancelled.")
        return

    result = api.stop_instance(info["id"])
    if result:
        print(f"[gg] Instance #{info['id']} stop requested.")
    else:
        sys.exit(1)


def cmd_ssh_keys(args):
    cfg = _get_client_config()
    api = _get_client_api(cfg)

    action = getattr(args, "ssh_keys_action", None)

    if action == "add":
        _cmd_ssh_keys_add(api)
    elif action == "list" or action is None:
        _cmd_ssh_keys_list(api)
    else:
        print("Usage: gg ssh-keys [list|add]", file=sys.stderr)


def _cmd_ssh_keys_list(api: ClientAPI):
    keys = api.list_ssh_keys()
    if keys is None:
        sys.exit(1)
    if not keys:
        print("No SSH keys. Add one: gg ssh-keys add")
        return

    header = f"{'ID':<6} {'NAME':<25} {'FINGERPRINT':<50} {'ACTIVE'}"
    print(header)
    print("-" * len(header))
    for k in keys:
        kid = str(k.get("id", ""))
        name = k.get("key_name", "")
        if len(name) > 23:
            name = name[:20] + "..."
        fp = k.get("fingerprint", "")[:48]
        active = "yes" if k.get("is_active") else "no"
        print(f"{kid:<6} {name:<25} {fp:<50} {active}")


def _cmd_ssh_keys_add(api: ClientAPI):
    local_keys = _find_local_ssh_pubkeys()
    if not local_keys:
        print("No SSH public keys found in ~/.ssh/", file=sys.stderr)
        print("Generate one: ssh-keygen -t ed25519", file=sys.stderr)
        sys.exit(1)

    if len(local_keys) == 1:
        key_path = local_keys[0]
    else:
        try:
            from InquirerPy import inquirer
            choices = [{"name": os.path.basename(p), "value": p} for p in local_keys]
            key_path = inquirer.select(
                message="Select SSH key to add:",
                choices=choices,
            ).execute()
        except ImportError:
            print("Multiple keys found. Which one?")
            for i, p in enumerate(local_keys):
                print(f"  [{i + 1}] {os.path.basename(p)}")
            idx = input("Enter number: ").strip()
            try:
                key_path = local_keys[int(idx) - 1]
            except (ValueError, IndexError):
                print("Invalid selection.", file=sys.stderr)
                sys.exit(1)

    try:
        with open(key_path, "r") as f:
            pubkey = f.read().strip()
    except Exception as e:
        print(f"Error reading {key_path}: {e}", file=sys.stderr)
        sys.exit(1)

    key_name = os.path.basename(key_path).replace(".pub", "")
    print(f"Adding {os.path.basename(key_path)}...")

    result = api.add_ssh_key(key_name, pubkey)
    if result:
        print(f"[gg] SSH key '{key_name}' added to your account.")
    else:
        sys.exit(1)


def cmd_volumes(args):
    cfg = _get_client_config()
    api = _get_client_api(cfg)

    action = getattr(args, "volumes_action", None)

    if action == "create":
        _cmd_volumes_create(api, args)
    elif action == "delete":
        _cmd_volumes_delete(api, args)
    elif action == "list" or action is None:
        _cmd_volumes_list(api)
    else:
        print("Usage: gg volumes [list|create|delete]", file=sys.stderr)


def _cmd_volumes_list(api: ClientAPI):
    volumes = api.list_volumes()
    if volumes is None:
        sys.exit(1)
    if not volumes:
        print("No volumes. Create one: gg volumes create <name>")
        return

    header = f"{'ID':<6} {'NAME':<25} {'SIZE':<12} {'USED':<12} {'STATUS'}"
    print(header)
    print("-" * len(header))
    for v in volumes:
        vid = str(v.get("id", ""))
        name = v.get("name", "")
        if len(name) > 23:
            name = name[:20] + "..."
        size_limit = v.get("size_limit_gb", 0)
        size_str = f"{size_limit:.0f} GB"
        used = v.get("used_size_gb", 0) or 0
        used_str = f"{used:.1f} GB"
        status = v.get("status", "unknown")
        print(f"{vid:<6} {name:<25} {size_str:<12} {used_str:<12} {status}")


def _cmd_volumes_create(api: ClientAPI, args):
    name = args.volume_name
    size = args.size or 10.0
    desc = args.description

    print(f"Creating volume '{name}' ({size:.0f} GB)...")
    result = api.create_volume(name, size, desc)
    if result:
        vid = result.get("id", "?")
        print(f"[gg] Volume created: #{vid} '{name}' ({size:.0f} GB)")
    else:
        sys.exit(1)


def _fmt_price_hr(value) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):.2f}/hr"
    except (TypeError, ValueError):
        return "—"


def _select_or_create_volume(api: ClientAPI) -> Optional[int]:
    """Interactive volume selection: pick existing, create new, or skip.
    Returns volume_id or None if user skips / cancels."""
    try:
        from InquirerPy import inquirer
    except ImportError:
        # Without InquirerPy we can't really do an interactive picker — skip volume.
        return None

    volumes = api.list_volumes() or []

    choices = [{"name": "→ Skip (no volume)", "value": "__skip__"}]
    for v in volumes:
        size = v.get("size_limit_gb", 0)
        used = v.get("used_size_gb", 0) or 0
        name = v.get("name", "?")
        choices.append({
            "name": f"#{v.get('id')}  {name}  ({used:.1f}/{size:.0f} GB)",
            "value": v.get("id"),
        })
    choices.append({"name": "+ Create new volume", "value": "__new__"})

    pick = inquirer.select(
        message="Attach a volume? (persistent storage, survives instance restart)",
        choices=choices,
        default="__skip__",
    ).execute()

    if pick == "__skip__":
        return None

    if pick == "__new__":
        name = inquirer.text(message="Volume name:").execute()
        if not name or not name.strip():
            print("[gg] Cancelled — no name given.")
            return None
        size_str = inquirer.text(
            message="Size limit (GB, 20–200):",
            default="20",
        ).execute()
        try:
            size = float(size_str)
        except (ValueError, TypeError):
            print("[gg] Invalid size; skipping volume.")
            return None
        result = api.create_volume(name.strip(), size)
        if not result:
            return None
        new_id = result.get("id")
        print(f"[gg] Volume #{new_id} '{name}' created ({size:.0f} GB)")
        return new_id

    return pick


def _confirm(prompt: str, default: bool = False) -> bool:
    try:
        from InquirerPy import inquirer
        return inquirer.confirm(message=prompt, default=default).execute()
    except ImportError:
        suffix = " [Y/n] " if default else " [y/N] "
        ans = input(prompt + suffix).strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")


def _pick_pricing_type(default: str = "week") -> str:
    choices = [
        ("week",   "Weekly  (recommended — good discount)"),
        ("month",  "Monthly (best discount)"),
        ("minute", "Per-minute (flexible, no commitment)"),
    ]
    try:
        from InquirerPy import inquirer
        return inquirer.select(
            message="Billing plan:",
            choices=[{"name": label, "value": val} for val, label in choices],
            default=default,
        ).execute()
    except ImportError:
        allowed = [val for val, _ in choices]
        ans = input(f"Billing plan [{'/'.join(allowed)}] (default {default}): ").strip().lower()
        return ans if ans in allowed else default


def _place_order_with_retry(
    api: ClientAPI, flow, *,
    pricing_type, volume_id, gpu_required,
    docker_image, disk_gb,
):
    """Ask for a GPU pick, confirm, and place the order.  On 410 (offer gone)
    drop back into the picker so the user can choose a different one without
    re-answering plan/volume/image questions.  Returns the order dict or None."""
    from gpuniq.cli.client_api import OrderOfferGone

    while True:
        target = flow.run_next()
        if not target:
            return None

        agent_id = target.get("id")
        gpu_label = f"{target.get('gpu_model','?')} x{target.get('gpu_count',1)}"
        price = _fmt_price_hr(target.get("price_per_hour"))

        print()
        print(f"  Selected: #{agent_id}  {gpu_label}  {price}  · {target.get('location','—')}")
        print()
        print("  Order summary")
        print(f"    GPU:        {gpu_label}")
        print(f"    Image:      {docker_image}")
        print(f"    Price:      {price} ({pricing_type})")
        print(f"    Volume:     {'#' + str(volume_id) if volume_id else '— none —'}")
        if disk_gb:
            print(f"    Disk:       {disk_gb} GB")

        if not _confirm("Place order?", default=True):
            if _confirm("Pick another GPU?", default=True):
                continue
            return None

        print("[gg] Sending order…")
        try:
            result = api.create_order(
                agent_id=agent_id,
                pricing_type=pricing_type,
                gpu_required=gpu_required,
                volume_id=volume_id,
                docker_image=docker_image,
                disk_gb=disk_gb,
            )
        except OrderOfferGone as e:
            print(f"[gg] Offer #{agent_id} is gone — {e.message}")
            if _confirm("Pick another GPU with the same plan / volume?", default=True):
                continue
            return None

        if result is None:
            return None
        return result


def cmd_rent(args):
    """Interactive: browse marketplace and rent a GPU."""
    from gpuniq.cli.rent_ui import RentFlow, banner, pick_docker_image, DEFAULT_IMAGE

    cfg = _get_client_config()
    api = _get_client_api(cfg)

    print(banner("gg rent — GPU marketplace"))

    flow = RentFlow(api)
    flow.seed(
        gpu_model=args.gpu,
        min_count=args.count,
        max_price=args.max_price,
        verified_only=bool(args.verified),
        sort_by=args.sort,
    )

    pricing_type = args.pricing or _pick_pricing_type()

    if args.image:
        docker_image, disk_gb = args.image, None
    else:
        docker_image, disk_gb = pick_docker_image()
    if args.disk:
        disk_gb = args.disk

    if args.no_volume:
        volume_id = None
    elif args.volume_id:
        volume_id = int(args.volume_id)
    else:
        volume_id = _select_or_create_volume(api)

    result = _place_order_with_retry(
        api, flow,
        pricing_type=pricing_type,
        volume_id=volume_id,
        gpu_required=args.count or 0,
        docker_image=docker_image or DEFAULT_IMAGE,
        disk_gb=disk_gb,
    )
    if result is None:
        print("[gg] Cancelled.")
        return

    order_id = result.get("order_id") or result.get("task_id")
    msg = result.get("message", "")
    final_cost = result.get("final_cost")
    print(f"[gg] Order placed: #{order_id}")
    if final_cost is not None:
        print(f"[gg] Charged: ${float(final_cost):.4f}")
    if msg:
        print(f"[gg] {msg}")
    print(f"[gg] Track it: gg orders   ·   SSH: gg open {order_id}")


def _sdk_client(cfg):
    """Build a gpuniq.GPUniq client from the CLI's stored API key."""
    from gpuniq import GPUniq

    data = cfg.load()
    return GPUniq(api_key=data["api_key"], base_url=data["api_base_url"])


def cmd_llm(args):
    """Chat with a text model. Without a prompt, opens an interactive REPL."""
    cfg = _get_client_config()
    client = _sdk_client(cfg)

    if args.list_models:
        models = client.llm.models()
        default = client.llm.default_model()
        print("Available models:")
        for m in models:
            mark = "  (default)" if m == default else ""
            print(f"  {m}{mark}")
        return

    model = args.model
    if args.prompt:
        _llm_one_shot(client, args, model=model)
        return
    _llm_repl(client, args, model=model)


def _llm_one_shot(client, args, *, model):
    prompt = " ".join(args.prompt)
    try:
        data = client.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    except Exception as e:
        print(f"[gg] LLM request failed: {e}", file=sys.stderr)
        sys.exit(1)

    content = (data or {}).get("content", "")
    print(content)
    if not args.quiet:
        tokens = (data or {}).get("tokens_used")
        cost = (data or {}).get("cost_usd")
        bal = (data or {}).get("balance_usd")
        parts = []
        if tokens is not None:
            parts.append(f"{tokens} tokens")
        if cost is not None:
            parts.append(f"${float(cost):.4f}")
        if bal is not None:
            parts.append(f"balance ${float(bal):.2f}")
        if parts:
            print(f"\n[gg] {'  ·  '.join(parts)}", file=sys.stderr)


def _llm_repl(client, args, *, model):
    from gpuniq.cli.rent_ui import banner

    actual_model = model or client.llm.default_model() or "(default)"
    print(banner(f"gg llm — interactive chat · model: {actual_model}"))
    print("  Type your message and press Enter. /exit or Ctrl-D to quit, /clear to reset history.\n")

    history: List[Dict[str, str]] = []
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return
        if line == "/clear":
            history.clear()
            print("[gg] history cleared.")
            continue

        history.append({"role": "user", "content": line})
        try:
            data = client.llm.chat_completion(
                messages=history, model=model,
                max_tokens=args.max_tokens, temperature=args.temperature,
            )
        except Exception as e:
            print(f"[gg] LLM request failed: {e}", file=sys.stderr)
            history.pop()
            continue

        reply = (data or {}).get("content", "")
        print(f"\nllm> {reply}\n")
        history.append({"role": "assistant", "content": reply})


def cmd_image(args):
    """Generate images from a prompt."""
    cfg = _get_client_config()
    client = _sdk_client(cfg)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("Error: prompt is required. Example: gg image \"a red cat astronaut\"", file=sys.stderr)
        sys.exit(2)

    output = args.output or _default_image_filename(args.n)
    input_paths = args.input or []

    print(f"[gg] Generating {args.n} image(s) with {args.model}…")
    try:
        if args.async_job or args.model.startswith("nano-banana"):
            # Prefer async-poll path for Nano Banana (long-running).
            def _on_progress(status, _payload):
                print(f"[gg] job status: {status}", file=sys.stderr)

            result = client.llm.generate_image_async(
                prompt,
                model=args.model,
                size=args.size,
                quality=args.quality,
                input_images=input_paths or None,
                save_to=output,
                on_progress=_on_progress,
            )
        else:
            result = client.llm.generate_image(
                prompt,
                model=args.model,
                n=args.n,
                size=args.size,
                quality=args.quality,
                input_images=input_paths or None,
                save_to=output,
            )
    except Exception as e:
        print(f"[gg] Image generation failed: {e}", file=sys.stderr)
        sys.exit(1)

    paths = result.get("saved_paths") or []
    for p in paths:
        print(f"[gg] Saved: {p}")

    cost = result.get("cost_usd")
    bal = result.get("balance_usd")
    count = result.get("image_count", len(paths) or args.n)
    line = f"[gg] {count} image(s)"
    if cost is not None:
        line += f"  ·  cost ${float(cost):.4f}"
    if bal is not None:
        line += f"  ·  balance ${float(bal):.2f}"
    print(line)


def _default_image_filename(n: int) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"gpuniq-image-{ts}.png" if n == 1 else f"gpuniq-images-{ts}"


def _pick_running_instance(api: ClientAPI, preselected_id=None) -> Optional[dict]:
    """Return a running instance dict, or None if cancelled / not found."""
    data = api.get_instances()
    if not data:
        return None
    instances = data.get("instances", []) or []
    running = [i for i in instances if i.get("status") in ("running", "starting", "provisioning")]
    if not running:
        print("No running instances. Rent one with: gg rent")
        return None

    if preselected_id:
        matched = [i for i in running if str(i.get("id")) == str(preselected_id)]
        if not matched:
            print(f"Error: no running instance with ID {preselected_id}", file=sys.stderr)
            return None
        return matched[0]

    if len(running) == 1:
        return running[0]

    try:
        from InquirerPy import inquirer
    except ImportError:
        print("Multiple running instances. Specify ID: gg replace <instance_id>")
        for i in running:
            info = _extract_instance_info(i)
            print(f"  #{info['id']}  {info['gpu_label']}  ({info['status']})")
        return None

    choices = []
    for i in running:
        info = _extract_instance_info(i)
        price_str = _fmt_price_hr(info["price_per_hour"])
        label = f"#{info['id']}  {info['gpu_label']}  ({info['status']})  {price_str}"
        choices.append({"name": label, "value": i})

    return inquirer.select(message="Replace which instance?", choices=choices).execute()


def cmd_replace(args):
    """Stop a running instance and rent a new GPU, preserving volume + plan."""
    from gpuniq.cli.client_api import OrderOfferGone
    from gpuniq.cli.rent_ui import RentFlow, banner, pick_docker_image, DEFAULT_IMAGE

    cfg = _get_client_config()
    api = _get_client_api(cfg)

    target_inst = _pick_running_instance(api, args.instance_id)
    if not target_inst:
        sys.exit(1)

    info = _extract_instance_info(target_inst)
    billing = target_inst.get("billing") or {}
    old_pricing = billing.get("pricing_type") or "hour"
    old_volume_id = target_inst.get("volume_id")
    old_container = target_inst.get("container") or {}
    old_image = old_container.get("docker_image") or DEFAULT_IMAGE

    print(banner(f"gg replace — swap GPU on #{info['id']}"))
    print(f"  Current: {info['gpu_label']}  ({info['status']})  ·  plan: {old_pricing}")
    print(f"  Image:   {old_image}")
    print(f"  Volume:  {'#' + str(old_volume_id) if old_volume_id else '— none —'}")

    if args.image:
        new_image, new_disk = args.image, None
    else:
        new_image, new_disk = pick_docker_image(default_image=old_image)

    flow = RentFlow(api)
    flow.seed(
        gpu_model=args.gpu,
        min_count=args.count,
        max_price=args.max_price,
        verified_only=bool(args.verified),
        sort_by=args.sort,
    )

    # Find a new GPU that the user is ready to commit to (may retry on 410).
    while True:
        new_target = flow.run_next()
        if not new_target:
            print("[gg] Cancelled.")
            return

        new_gpu_label = f"{new_target.get('gpu_model','?')} x{new_target.get('gpu_count',1)}"
        new_price = _fmt_price_hr(new_target.get("price_per_hour"))

        print()
        print("  Replacement summary")
        print(f"    Old:    #{info['id']}  {info['gpu_label']}  ({_fmt_price_hr(info['price_per_hour'])})")
        print(f"    New:    {new_gpu_label}  ({new_price})  · {new_target.get('location','—')}")
        print(f"    Image:  {new_image}")
        print(f"    Plan:   {old_pricing}")
        print(f"    Volume: {'#' + str(old_volume_id) if old_volume_id else '— none — (data on the old instance will be lost)'}")
        print()

        if not _confirm(
            f"Destroy #{info['id']} and start the new GPU? "
            "This permanently removes the old instance.",
            default=False,
        ):
            if _confirm("Pick a different replacement GPU?", default=True):
                continue
            print("[gg] Cancelled.")
            return

        print(f"[gg] Destroying #{info['id']}…")
        if not api.delete_instance(info["id"]):
            print("[gg] Could not destroy old instance — aborting before placing new order.", file=sys.stderr)
            sys.exit(1)

        print("[gg] Provisioning replacement…")
        try:
            result = api.create_order(
                agent_id=new_target.get("id"),
                pricing_type=old_pricing,
                gpu_required=args.count or 0,
                volume_id=old_volume_id,
                docker_image=new_image,
                disk_gb=new_disk,
            )
        except OrderOfferGone as e:
            print(f"[gg] Offer gone — {e.message}")
            print("[gg] Old instance already destroyed. Renting a different GPU…")
            # Old instance is already stopped; we need to place SOMETHING or leave the user
            # without a GPU. Let them pick another offer with the same plan + volume.
            while True:
                retry = flow.run_next()
                if not retry:
                    print("[gg] No replacement placed. Run: gg rent", file=sys.stderr)
                    sys.exit(1)
                try:
                    result = api.create_order(
                        agent_id=retry.get("id"),
                        pricing_type=old_pricing,
                        gpu_required=args.count or 0,
                        volume_id=old_volume_id,
                        docker_image=new_image,
                        disk_gb=new_disk,
                    )
                    new_target = retry
                    new_gpu_label = f"{retry.get('gpu_model','?')} x{retry.get('gpu_count',1)}"
                    break
                except OrderOfferGone as ee:
                    print(f"[gg] #{retry.get('id')} also gone — {ee.message}. Picking again…")

        if not result:
            print(
                "[gg] Replacement order failed. Old instance is already destroyed — "
                "rent manually with: gg rent",
                file=sys.stderr,
            )
            sys.exit(1)

        new_id = result.get("order_id") or result.get("task_id")
        print(f"[gg] Replacement placed: #{new_id} ({new_gpu_label})")
        print(f"[gg] Track it: gg orders   ·   SSH: gg open {new_id}")
        return


def _cmd_volumes_delete(api: ClientAPI, args):
    volume_id = args.volume_id

    # Confirm
    try:
        from InquirerPy import inquirer
        confirm = inquirer.confirm(
            message=f"Delete volume #{volume_id}? This cannot be undone.",
            default=False,
        ).execute()
    except ImportError:
        answer = input(f"Delete volume #{volume_id}? [y/N] ").strip().lower()
        confirm = answer in ("y", "yes")

    if not confirm:
        print("Cancelled.")
        return

    if api.delete_volume(int(volume_id)):
        print(f"[gg] Volume #{volume_id} deleted.")
    else:
        sys.exit(1)


# ─── Main entry point ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="gg",
        description="GPUniq command checkpointing CLI",
        usage="gg [-h] {init,list,logs,status,login,orders,open,rent,replace,llm,image,stop,balance,ssh-keys,volumes} ... | gg <command>",
    )
    parser.add_argument(
        "--gg-dir",
        default=None,
        help=f"Override .gg directory (default: {DEFAULT_GG_DIR})",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # gg init
    init_parser = subparsers.add_parser("init", help="Initialize gg with a CLI token")
    init_parser.add_argument("token", help="CLI token from GPUniq dashboard")
    init_parser.add_argument("--api-url", default=None, help="Override API base URL")

    # gg list
    subparsers.add_parser("list", help="List saved checkpoints")

    # gg logs
    logs_parser = subparsers.add_parser("logs", help="View logs for a checkpoint")
    logs_parser.add_argument("checkpoint_id", help="Checkpoint ID (or prefix)")
    logs_parser.add_argument("--tail", type=int, default=None, help="Show last N lines")

    # gg replay
    subparsers.add_parser("replay", help="Re-run unfinished commands from previous session")

    # gg status
    subparsers.add_parser("status", help="Show gg status and config")

    # gg services [list|rm|clear]
    services_parser = subparsers.add_parser("services", help="Manage persistent services")
    services_sub = services_parser.add_subparsers(dest="services_action")
    services_sub.add_parser("list", help="List registered services (default)")
    rm_parser = services_sub.add_parser("rm", help="Remove a service by ID")
    rm_parser.add_argument("service_id", help="Service ID (or prefix)")
    services_sub.add_parser("clear", help="Remove all services")

    # gg restart
    subparsers.add_parser("restart", help="Restart all registered persistent services")

    # ── Client-side commands ──

    # gg login
    login_parser = subparsers.add_parser("login", help="Log in with your GPUniq API key")
    login_parser.add_argument("api_key", nargs="?", default=None, help="API key (or enter interactively)")
    login_parser.add_argument("--api-url", default=None, help="Override API base URL")

    # gg orders
    subparsers.add_parser("orders", help="List your rented GPU instances")

    # gg open
    open_parser = subparsers.add_parser("open", help="SSH into a rented GPU instance")
    open_parser.add_argument("instance_id", nargs="?", default=None, help="Instance ID (or select interactively)")

    # gg balance
    subparsers.add_parser("balance", help="Show your current balance")

    # gg stop
    stop_parser = subparsers.add_parser("stop", help="Stop a running GPU instance")
    stop_parser.add_argument("instance_id", nargs="?", default=None, help="Instance ID (or select interactively)")

    # gg ssh-keys [list|add]
    ssh_keys_parser = subparsers.add_parser("ssh-keys", help="Manage your SSH keys")
    ssh_keys_sub = ssh_keys_parser.add_subparsers(dest="ssh_keys_action")
    ssh_keys_sub.add_parser("list", help="List SSH keys in your account (default)")
    ssh_keys_sub.add_parser("add", help="Add a local SSH key to your account")

    # gg rent — interactive GPU rental
    rent_parser = subparsers.add_parser("rent", help="Interactively rent a GPU from the marketplace")
    rent_parser.add_argument("--gpu", default=None, help="GPU model filter, e.g. 'RTX 4090'")
    rent_parser.add_argument("--count", type=int, default=None, help="GPU count")
    rent_parser.add_argument("--max-price", type=float, default=None, dest="max_price",
                             help="Max price per hour (USD)")
    rent_parser.add_argument("--sort", default=None,
                             choices=["price-low", "price-high", "reliability", "vram", "performance"],
                             help="Sort order (default price-low)")
    rent_parser.add_argument("--pricing", default=None,
                             choices=["minute", "week", "month"],
                             help="Billing plan — default 'week' (skip interactive prompt)")
    rent_parser.add_argument("--volume-id", default=None, dest="volume_id",
                             help="Attach this existing volume (skip prompt)")
    rent_parser.add_argument("--no-volume", action="store_true", dest="no_volume",
                             help="Skip the volume prompt entirely")
    rent_parser.add_argument("--verified", action="store_true",
                             help="Show only verified providers")
    rent_parser.add_argument("--image", default=None,
                             help="Docker image to launch (skips preset prompt). "
                                  "e.g. vastai/pytorch:cuda-12.9.1-auto")
    rent_parser.add_argument("--disk", type=int, default=None,
                             help="Disk size in GB (20-2048)")

    # gg replace — swap GPU on a running instance
    replace_parser = subparsers.add_parser(
        "replace", help="Replace a running instance with a different GPU"
    )
    replace_parser.add_argument("instance_id", nargs="?", default=None,
                                help="Instance ID to replace (or pick interactively)")
    replace_parser.add_argument("--gpu", default=None, help="GPU model filter, e.g. 'A100'")
    replace_parser.add_argument("--count", type=int, default=None, help="GPU count")
    replace_parser.add_argument("--max-price", type=float, default=None, dest="max_price",
                                help="Max price per hour (USD)")
    replace_parser.add_argument("--sort", default=None,
                                choices=["price-low", "price-high", "reliability", "vram", "performance"],
                                help="Sort order")
    replace_parser.add_argument("--verified", action="store_true",
                                help="Show only verified providers")
    replace_parser.add_argument("--image", default=None,
                                help="Docker image for the replacement "
                                     "(default: keep the old instance's image)")
    replace_parser.add_argument("--disk", type=int, default=None,
                                help="Disk size in GB (20-2048)")

    # gg llm — chat with a text model (one-shot or REPL)
    llm_parser = subparsers.add_parser(
        "llm", help="Chat with an LLM (one-shot if prompt given, otherwise interactive REPL)"
    )
    llm_parser.add_argument("prompt", nargs="*",
                            help="One-shot prompt. Omit for interactive chat mode.")
    llm_parser.add_argument("-m", "--model", default=None,
                            help="Model slug (default: platform default)")
    llm_parser.add_argument("--max-tokens", type=int, default=None, dest="max_tokens",
                            help="Cap response length")
    llm_parser.add_argument("--temperature", type=float, default=None,
                            help="Sampling temperature 0.0–1.0")
    llm_parser.add_argument("--list-models", action="store_true", dest="list_models",
                            help="List available text models and exit")
    llm_parser.add_argument("-q", "--quiet", action="store_true",
                            help="Suppress the tokens/cost/balance summary")

    # gg image — generate images from a text prompt
    img_parser = subparsers.add_parser(
        "image", help="Generate image(s) from a prompt (Nano Banana, Nano Banana Pro, Grok 4 Image)"
    )
    img_parser.add_argument("prompt", nargs="+", help="Text prompt for the image")
    img_parser.add_argument("-o", "--output", default=None,
                            help="Output file (single) or directory (multi). "
                                 "Default: auto-named PNG in cwd.")
    img_parser.add_argument("-m", "--model", default="nano-banana",
                            help="Image model slug (default: nano-banana)")
    img_parser.add_argument("-n", "--n", type=int, default=1,
                            help="Number of images (1-4, default 1)")
    img_parser.add_argument("--size", default=None,
                            help="Size hint, e.g. 1024x1024, 2048x2048, 4096x4096")
    img_parser.add_argument("--quality", default=None,
                            help="Quality hint, e.g. standard / hd")
    img_parser.add_argument("--input", action="append", default=None,
                            help="Reference image path (repeat for multiple) — "
                                 "enables image-to-image / editing")
    img_parser.add_argument("--async", action="store_true", dest="async_job",
                            help="Force async job-based path (poll) instead of sync")

    # gg volumes [list|create|delete]
    vol_parser = subparsers.add_parser("volumes", help="Manage your storage volumes")
    vol_sub = vol_parser.add_subparsers(dest="volumes_action")
    vol_sub.add_parser("list", help="List volumes (default)")
    vol_create = vol_sub.add_parser("create", help="Create a new volume")
    vol_create.add_argument("volume_name", help="Volume name")
    vol_create.add_argument("--size", type=float, default=10.0, help="Size limit in GB (default: 10)")
    vol_create.add_argument("--description", default=None, help="Volume description")
    vol_delete = vol_sub.add_parser("delete", help="Delete a volume")
    vol_delete.add_argument("volume_id", help="Volume ID")

    # If first arg is not a known subcommand, treat everything as a command to run
    known_subcommands = {
        "init", "list", "logs", "status", "replay", "services", "restart",
        "login", "orders", "open", "balance", "stop", "ssh-keys", "volumes",
        "rent", "replace", "llm", "image",
        "-h", "--help", "help", "--gg-dir",
    }

    # "gg help" → same as "gg --help"
    if len(sys.argv) > 1 and sys.argv[1] == "help":
        parser.print_help()
        return

    # `gg <word>` where <word> isn't a known subcommand is ambiguous:
    #   • On a GPU where `gg init` was run, it means "run this shell command
    #     under checkpointing" — the original GG_TOKEN workflow.
    #   • On a client machine (only `gg login` done), it almost certainly
    #     means a typo or a feature that doesn't exist — and the existing
    #     fallback used to respond with the confusing
    #     "Error: gg not initialized. Run: gg init <token>".
    # Disambiguate by checking whether the .gg init config actually exists.
    if len(sys.argv) > 1 and sys.argv[1] not in known_subcommands:
        server_cfg = GGConfig(DEFAULT_GG_DIR)
        if not server_cfg.exists():
            # Client machine — treat as typo / unknown command.
            print(f"Error: unknown command '{sys.argv[1]}'.", file=sys.stderr)
            print(file=sys.stderr)
            parser.print_help(sys.stderr)
            sys.exit(2)

        # GPU-side: run as shell command under checkpointing.
        argv = sys.argv[1:]
        gg_dir = None
        filtered = []
        i = 0
        while i < len(argv):
            if argv[i] == "--gg-dir" and i + 1 < len(argv):
                gg_dir = argv[i + 1]
                i += 2
            else:
                filtered.append(argv[i])
                i += 1

        ns = argparse.Namespace(subcommand="run", command=filtered, gg_dir=gg_dir)
        cmd_run(ns)
        return

    args = parser.parse_args()

    if args.subcommand == "init":
        cmd_init(args)
    elif args.subcommand == "list":
        cmd_list(args)
    elif args.subcommand == "logs":
        cmd_logs(args)
    elif args.subcommand == "replay":
        cmd_replay(args)
    elif args.subcommand == "status":
        cmd_status(args)
    elif args.subcommand == "services":
        if not args.services_action or args.services_action == "list":
            args.services_action = None  # trigger default list
        cmd_services(args)
    elif args.subcommand == "restart":
        cmd_restart(args)
    elif args.subcommand == "login":
        cmd_login(args)
    elif args.subcommand == "orders":
        cmd_orders(args)
    elif args.subcommand == "open":
        cmd_open(args)
    elif args.subcommand == "balance":
        cmd_balance(args)
    elif args.subcommand == "stop":
        cmd_stop(args)
    elif args.subcommand == "ssh-keys":
        if not args.ssh_keys_action or args.ssh_keys_action == "list":
            args.ssh_keys_action = None
        cmd_ssh_keys(args)
    elif args.subcommand == "volumes":
        if not args.volumes_action or args.volumes_action == "list":
            args.volumes_action = None
        cmd_volumes(args)
    elif args.subcommand == "rent":
        cmd_rent(args)
    elif args.subcommand == "replace":
        cmd_replace(args)
    elif args.subcommand == "llm":
        cmd_llm(args)
    elif args.subcommand == "image":
        cmd_image(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
