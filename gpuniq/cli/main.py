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

    # Connect via SSH
    ssh_user = target["ssh_username"]
    ssh_host = target["ssh_host"]
    ssh_port = str(target["ssh_port"])

    ssh_args = ["ssh", f"{ssh_user}@{ssh_host}", "-p", ssh_port]
    print(f"[gg] {' '.join(ssh_args)}\n")

    # Replace current process with SSH
    os.execvp("ssh", ssh_args)


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


def _pick_pricing_type(default: str = "hour") -> str:
    try:
        from InquirerPy import inquirer
        return inquirer.select(
            message="Billing plan:",
            choices=[
                {"name": "Per minute (most flexible)", "value": "minute"},
                {"name": "Per hour",                   "value": "hour"},
                {"name": "Per day",                    "value": "day"},
                {"name": "Per week  (cheaper)",        "value": "week"},
                {"name": "Per month (cheapest)",       "value": "month"},
            ],
            default=default,
        ).execute()
    except ImportError:
        ans = input(f"Billing plan [minute/hour/day/week/month] (default {default}): ").strip().lower()
        return ans if ans in ("minute", "hour", "day", "week", "month") else default


def cmd_rent(args):
    """Interactive: browse marketplace and rent a GPU."""
    from gpuniq.cli.rent_ui import RentFlow, banner

    cfg = _get_client_config()
    api = _get_client_api(cfg)

    print(banner("gg rent — GPU marketplace"))

    target = RentFlow(api).run(
        gpu_model=args.gpu,
        min_count=args.count,
        max_price=args.max_price,
        verified_only=bool(args.verified),
        sort_by=args.sort,
    )
    if not target:
        print("[gg] Cancelled.")
        return

    agent_id = target.get("id")
    gpu_label = f"{target.get('gpu_model','?')} x{target.get('gpu_count',1)}"
    price = _fmt_price_hr(target.get("price_per_hour"))

    print()
    print(f"  Selected: #{agent_id}  {gpu_label}  {price}  · {target.get('location','—')}")

    pricing_type = args.pricing or _pick_pricing_type()

    volume_id = None
    if args.no_volume:
        pass
    elif args.volume_id:
        volume_id = int(args.volume_id)
    else:
        volume_id = _select_or_create_volume(api)

    print()
    print("  Order summary")
    print(f"    GPU:        {gpu_label}")
    print(f"    Price:      {price} ({pricing_type})")
    print(f"    Volume:     {'#' + str(volume_id) if volume_id else '— none —'}")

    if not _confirm("Place order?", default=True):
        print("[gg] Cancelled.")
        return

    print("[gg] Sending order…")
    result = api.create_order(
        agent_id=agent_id,
        pricing_type=pricing_type,
        gpu_required=args.count or 0,
        volume_id=volume_id,
    )
    if not result:
        sys.exit(1)

    order_id = result.get("order_id") or result.get("task_id")
    msg = result.get("message", "")
    final_cost = result.get("final_cost")
    print(f"[gg] Order placed: #{order_id}")
    if final_cost is not None:
        print(f"[gg] Charged: ${float(final_cost):.4f}")
    if msg:
        print(f"[gg] {msg}")
    print(f"[gg] Track it: gg orders   ·   SSH: gg open {order_id}")


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
    from gpuniq.cli.rent_ui import RentFlow, banner

    cfg = _get_client_config()
    api = _get_client_api(cfg)

    target_inst = _pick_running_instance(api, args.instance_id)
    if not target_inst:
        sys.exit(1)

    info = _extract_instance_info(target_inst)
    billing = target_inst.get("billing") or {}
    old_pricing = billing.get("pricing_type") or "hour"
    old_volume_id = target_inst.get("volume_id")

    print(banner(f"gg replace — swap GPU on #{info['id']}"))
    print(f"  Current: {info['gpu_label']}  ({info['status']})  ·  plan: {old_pricing}")
    print(f"  Volume:  {'#' + str(old_volume_id) if old_volume_id else '— none —'}")

    new_target = RentFlow(api).run(
        gpu_model=args.gpu,
        min_count=args.count,
        max_price=args.max_price,
        verified_only=bool(args.verified),
        sort_by=args.sort,
    )
    if not new_target:
        print("[gg] Cancelled.")
        return

    new_gpu_label = f"{new_target.get('gpu_model','?')} x{new_target.get('gpu_count',1)}"
    new_price = _fmt_price_hr(new_target.get("price_per_hour"))

    print()
    print("  Replacement summary")
    print(f"    Old:    #{info['id']}  {info['gpu_label']}  ({_fmt_price_hr(info['price_per_hour'])})")
    print(f"    New:    {new_gpu_label}  ({new_price})  · {new_target.get('location','—')}")
    print(f"    Plan:   {old_pricing}")
    print(f"    Volume: {'#' + str(old_volume_id) if old_volume_id else '— none — (data on the old instance will be lost)'}")
    print()

    if not _confirm(
        f"Stop #{info['id']} and start the new GPU? This terminates the current machine.",
        default=False,
    ):
        print("[gg] Cancelled.")
        return

    print(f"[gg] Stopping #{info['id']}…")
    if not api.stop_instance(info["id"]):
        print("[gg] Could not stop old instance — aborting before placing new order.", file=sys.stderr)
        sys.exit(1)

    print("[gg] Provisioning replacement…")
    result = api.create_order(
        agent_id=new_target.get("id"),
        pricing_type=old_pricing,
        gpu_required=args.count or 0,
        volume_id=old_volume_id,
    )
    if not result:
        print("[gg] Replacement order failed. Old instance is still stopped — rent manually with: gg rent",
              file=sys.stderr)
        sys.exit(1)

    new_id = result.get("order_id") or result.get("task_id")
    print(f"[gg] Replacement placed: #{new_id} ({new_gpu_label})")
    print(f"[gg] Track it: gg orders   ·   SSH: gg open {new_id}")


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
        usage="gg [-h] {init,list,logs,status,login,orders,open,rent,replace,stop,balance,ssh-keys,volumes} ... | gg <command>",
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
                             choices=["minute", "hour", "day", "week", "month"],
                             help="Billing plan (skip interactive prompt)")
    rent_parser.add_argument("--volume-id", default=None, dest="volume_id",
                             help="Attach this existing volume (skip prompt)")
    rent_parser.add_argument("--no-volume", action="store_true", dest="no_volume",
                             help="Skip the volume prompt entirely")
    rent_parser.add_argument("--verified", action="store_true",
                             help="Show only verified providers")

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
        "rent", "replace",
        "-h", "--help", "--gg-dir",
    }

    if len(sys.argv) > 1 and sys.argv[1] not in known_subcommands:
        # Build a namespace manually for the run command
        # Find and extract --gg-dir if present
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
