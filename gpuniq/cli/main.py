import argparse
import os
import sys
import time
from datetime import datetime

from gpuniq.cli.api import CheckpointAPI
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
    gg_dir = args.gg_dir or DEFAULT_GG_DIR
    cfg = _get_config(gg_dir)
    store = _get_store(cfg)
    data = cfg.load()

    checkpoints = store.get_checkpoints()
    total_size = store.total_log_size()

    size_mb = total_size / (1024 * 1024)

    print(f"Task ID:      {data.get('task_id', '?')}")
    print(f"Instance:     {data.get('instance_name', '-')}")
    print(f"API URL:      {data.get('api_base_url', '?')}")
    print(f"Initialized:  {data.get('initialized_at', '?')}")
    print(f"Checkpoints:  {len(checkpoints)}")
    print(f"Total logs:   {size_mb:.1f} MB")


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


# ─── Main entry point ───────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="gg",
        description="GPUniq command checkpointing CLI",
        usage="gg [-h] {init,list,logs,status} ... | gg <command>",
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

    # If first arg is not a known subcommand, treat everything as a command to run
    known_subcommands = {
        "init", "list", "logs", "status", "replay", "services", "restart",
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
