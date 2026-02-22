"""Instances — manage rented GPU instances."""

from typing import Any, Dict, Optional


class Instances:
    """Manage rented GPU instances: list, start, stop, delete, logs, SLA."""

    def __init__(self, client):
        self._c = client

    # ── List ─────────────────────────────────────────────────────────

    def list(self, *, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """List your active instances."""
        return self._c.get("/instances/my", params={"page": page, "page_size": page_size})

    def list_archived(self, *, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """List archived (deleted) instances."""
        return self._c.get("/instances/archived", params={"page": page, "page_size": page_size})

    def list_pending_jobs(self) -> Any:
        """List pending deployment jobs."""
        return self._c.get("/instances/pending/jobs")

    def cancel_pending_job(self, job_id: str) -> Any:
        """Cancel a pending deployment job."""
        return self._c.delete(f"/instances/pending/jobs/{job_id}")

    # ── Single instance ──────────────────────────────────────────────

    def get(self, task_id: int) -> Dict[str, Any]:
        """Get detailed info about an instance."""
        return self._c.get(f"/instances/{task_id}")

    def rename(self, task_id: int, name: str) -> Dict[str, Any]:
        """Rename an instance."""
        return self._c.patch(f"/instances/{task_id}/name", json={"name": name})

    # ── Actions ──────────────────────────────────────────────────────

    def start(self, task_id: int) -> Dict[str, Any]:
        """Start a stopped instance."""
        return self._c.post(f"/instances/{task_id}/start")

    def stop(self, task_id: int) -> Dict[str, Any]:
        """Stop a running instance."""
        return self._c.post(f"/instances/{task_id}/stop")

    def delete(self, task_id: int) -> Dict[str, Any]:
        """Delete an instance permanently."""
        return self._c.delete(f"/instances/{task_id}")

    # ── Logs & SLA ───────────────────────────────────────────────────

    def logs(self, task_id: int) -> Any:
        """Get container logs for an instance."""
        return self._c.get(f"/instances/{task_id}/logs")

    def sla(self, task_id: int) -> Dict[str, Any]:
        """Get SLA uptime data for an instance."""
        return self._c.get(f"/instances/{task_id}/sla")

    # ── SSH Keys ─────────────────────────────────────────────────────

    def ssh_keys(self, task_id: int) -> Any:
        """List SSH keys attached to an instance."""
        return self._c.get(f"/instances/{task_id}/ssh-keys")

    def attach_ssh_key(self, task_id: int, ssh_key_id: int) -> Any:
        """Attach an SSH key to an instance."""
        return self._c.post(f"/instances/{task_id}/ssh-keys", json={"ssh_key_id": ssh_key_id})

    def detach_ssh_key(self, task_id: int, key_id: int) -> Any:
        """Detach an SSH key from an instance."""
        return self._c.delete(f"/instances/{task_id}/ssh-keys/{key_id}")
