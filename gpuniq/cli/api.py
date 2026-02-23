import sys
from typing import Optional

import requests


class CheckpointAPI:
    """Thin HTTP client for the checkpoints backend API."""

    def __init__(self, base_url: str, token: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["X-GG-Token"] = token
        self.session.headers["Content-Type"] = "application/json"
        self.timeout = timeout

    def verify_token(self) -> Optional[dict]:
        """Verify CLI token. Returns {task_id, user_id} or None."""
        try:
            resp = self.session.post(
                f"{self.base_url}/checkpoints/auth/verify",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data")
        except Exception as e:
            print(f"[gg] Warning: token verify failed: {e}", file=sys.stderr)
            return None

    def create_checkpoint(self, data: dict) -> Optional[dict]:
        """Report new checkpoint to backend. Fire-and-forget on failure."""
        try:
            resp = self.session.post(
                f"{self.base_url}/checkpoints/",
                json=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data")
        except Exception as e:
            print(f"[gg] Warning: could not sync checkpoint: {e}", file=sys.stderr)
            return None

    def update_checkpoint(self, checkpoint_id: str, data: dict) -> Optional[dict]:
        """Update checkpoint on backend. Fire-and-forget on failure."""
        try:
            resp = self.session.patch(
                f"{self.base_url}/checkpoints/{checkpoint_id}",
                json=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data")
        except Exception as e:
            print(f"[gg] Warning: could not update checkpoint: {e}", file=sys.stderr)
            return None
