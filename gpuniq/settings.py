"""Settings — SSH keys and Telegram integration."""

from typing import Any, Dict, Optional


class Settings:
    """User settings: SSH key management and Telegram linking."""

    def __init__(self, client):
        self._c = client

    # ── SSH Keys ─────────────────────────────────────────────────────

    def list_ssh_keys(self) -> Any:
        """List all SSH keys."""
        return self._c.get("/settings/ssh-keys")

    def get_ssh_key(self, key_id: int) -> Dict[str, Any]:
        """Get SSH key details."""
        return self._c.get(f"/settings/ssh-keys/{key_id}")

    def create_ssh_key(self, key_name: str, public_key: str) -> Dict[str, Any]:
        """Add a new SSH key.

        Args:
            key_name: Friendly name for the key.
            public_key: SSH public key content (e.g. "ssh-rsa AAAA...").
        """
        return self._c.post("/settings/ssh-keys", json={
            "key_name": key_name,
            "public_key": public_key,
        })

    def update_ssh_key(self, key_id: int, *, key_name: Optional[str] = None) -> Dict[str, Any]:
        """Update SSH key name."""
        body: Dict[str, Any] = {}
        if key_name is not None:
            body["key_name"] = key_name
        return self._c.put(f"/settings/ssh-keys/{key_id}", json=body)

    def delete_ssh_key(self, key_id: int) -> Any:
        """Delete an SSH key."""
        return self._c.delete(f"/settings/ssh-keys/{key_id}")

    def toggle_ssh_key(self, key_id: int, is_active: bool) -> Dict[str, Any]:
        """Enable or disable an SSH key."""
        return self._c.patch(
            f"/settings/ssh-keys/{key_id}/toggle",
            params={"is_active": is_active},
        )

    def sync_ssh_key(self, key_id: int) -> Dict[str, Any]:
        """Sync SSH key to Vast.ai."""
        return self._c.post(f"/settings/ssh-keys/{key_id}/sync")

    def test_ssh_key(self, key_id: int) -> Any:
        """Test SSH key with Vast.ai."""
        return self._c.post(f"/settings/ssh-keys/{key_id}/test")

    # ── Telegram ─────────────────────────────────────────────────────

    def link_telegram(self, telegram_username: str) -> Dict[str, Any]:
        """Link a Telegram account for notifications."""
        return self._c.post("/settings/telegram/link", json={
            "telegram_username": telegram_username,
        })

    def telegram_status(self) -> Dict[str, Any]:
        """Get Telegram linking status."""
        return self._c.get("/settings/telegram/status")
