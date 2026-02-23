import errno
import os
import pty
import select
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

LOG_MAX_BYTES = 100 * 1024 * 1024  # 100 MB


class CommandRunner:
    """Executes commands with PTY emulation and output tee to log file."""

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir

    def run(self, command: str, working_dir: Optional[str] = None) -> dict:
        checkpoint_id = str(uuid.uuid4())
        log_path = os.path.join(self.logs_dir, f"{checkpoint_id}.log")
        cwd = working_dir or os.getcwd()
        started_at = datetime.now(timezone.utc)

        # Create PTY pair — child sees a real terminal (colors, progress bars)
        master_fd, slave_fd = pty.openpty()

        # Inherit terminal size from the real terminal
        try:
            import struct
            import fcntl
            import termios
            winsize = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
        except (OSError, ImportError):
            pass

        process = subprocess.Popen(
            command,
            shell=True,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            close_fds=True,
        )

        # Close slave in parent — only child uses it
        os.close(slave_fd)

        # Forward signals to child
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        killed = False

        def _handle_signal(signum, frame):
            nonlocal killed
            killed = True
            if process.poll() is None:
                process.send_signal(signum)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        bytes_written = 0
        try:
            with open(log_path, "wb") as log_file:
                while True:
                    # Wait for data from master PTY
                    try:
                        ready, _, _ = select.select([master_fd], [], [], 0.1)
                    except (select.error, ValueError):
                        break

                    if ready:
                        try:
                            chunk = os.read(master_fd, 8192)
                        except OSError as e:
                            if e.errno == errno.EIO:
                                # Child closed PTY — normal exit
                                break
                            raise
                        if not chunk:
                            break

                        # Write to terminal (preserves colors, ANSI codes)
                        try:
                            os.write(sys.stdout.fileno(), chunk)
                        except OSError:
                            pass

                        # Write to log file (up to limit)
                        if bytes_written < LOG_MAX_BYTES:
                            remaining = LOG_MAX_BYTES - bytes_written
                            log_file.write(chunk[:remaining])
                            bytes_written += min(len(chunk), remaining)

                    # Check if process has exited
                    if process.poll() is not None:
                        # Drain remaining output
                        while True:
                            try:
                                ready, _, _ = select.select([master_fd], [], [], 0.05)
                            except (select.error, ValueError):
                                break
                            if not ready:
                                break
                            try:
                                chunk = os.read(master_fd, 8192)
                            except OSError:
                                break
                            if not chunk:
                                break
                            try:
                                os.write(sys.stdout.fileno(), chunk)
                            except OSError:
                                pass
                            if bytes_written < LOG_MAX_BYTES:
                                remaining = LOG_MAX_BYTES - bytes_written
                                log_file.write(chunk[:remaining])
                                bytes_written += min(len(chunk), remaining)
                        break

            exit_code = process.wait()
        finally:
            os.close(master_fd)
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        if killed:
            status = "killed"
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"

        return {
            "checkpoint_id": checkpoint_id,
            "command": command,
            "exit_code": exit_code,
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round(duration, 2),
            "log_size_bytes": min(bytes_written, LOG_MAX_BYTES),
            "working_dir": cwd,
        }
