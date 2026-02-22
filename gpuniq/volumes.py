"""Volumes — persistent storage management."""

import os
from typing import Any, Dict, Optional


class Volumes:
    """Manage persistent volumes: create, upload, download, list files."""

    def __init__(self, client):
        self._c = client

    # ── CRUD ─────────────────────────────────────────────────────────

    def list(self) -> Any:
        """List all your volumes."""
        return self._c.get("/volumes/")

    def get(self, volume_id: int) -> Dict[str, Any]:
        """Get volume details."""
        return self._c.get(f"/volumes/{volume_id}")

    def create(
        self,
        name: str,
        *,
        description: Optional[str] = None,
        size_limit_gb: float = 10.0,
        agent_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a new volume.

        Args:
            name: Volume name (alphanumeric, hyphens, underscores, 1-64 chars).
            description: Optional description (max 256 chars).
            size_limit_gb: Size limit in GB (1-100, default 10).
            agent_id: Optional agent to host the volume on.
        """
        body: Dict[str, Any] = {"name": name, "size_limit_gb": size_limit_gb}
        if description is not None:
            body["description"] = description
        if agent_id is not None:
            body["agent_id"] = agent_id
        return self._c.post("/volumes/", json=body)

    def update(
        self,
        volume_id: int,
        *,
        description: Optional[str] = None,
        size_limit_gb: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update volume settings."""
        body: Dict[str, Any] = {}
        if description is not None:
            body["description"] = description
        if size_limit_gb is not None:
            body["size_limit_gb"] = size_limit_gb
        return self._c.patch(f"/volumes/{volume_id}", json=body)

    def delete(self, volume_id: int) -> Any:
        """Delete a volume permanently."""
        return self._c.delete(f"/volumes/{volume_id}")

    # ── Archived ─────────────────────────────────────────────────────

    def list_archived(self, *, page: int = 1, page_size: int = 20) -> Any:
        """List archived volumes."""
        return self._c.get("/volumes/archived", params={"page": page, "page_size": page_size})

    # ── Files ────────────────────────────────────────────────────────

    def list_files(self, volume_id: int, *, subpath: str = "") -> Any:
        """List files in a volume directory."""
        return self._c.get(f"/volumes/{volume_id}/files", params={"subpath": subpath})

    def upload(
        self,
        volume_id: int,
        file_path: str,
        *,
        subpath: str = "",
    ) -> Dict[str, Any]:
        """Upload a local file to a volume.

        Args:
            volume_id: Target volume ID.
            file_path: Local path to the file to upload.
            subpath: Remote subdirectory (default: root).
        """
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            return self._c.post(
                f"/volumes/{volume_id}/upload",
                params={"subpath": subpath},
                files={"file": (filename, f)},
            )

    def download(self, volume_id: int, path: str) -> bytes:
        """Download a file from a volume. Returns file content as bytes."""
        resp = self._c.request(
            "GET",
            f"/volumes/{volume_id}/files/{path}/download",
            raw_response=True,
        )
        return resp.content

    def download_to(self, volume_id: int, remote_path: str, local_path: str) -> str:
        """Download a file from a volume and save to local path.

        Returns:
            The local file path.
        """
        content = self.download(volume_id, remote_path)
        with open(local_path, "wb") as f:
            f.write(content)
        return local_path

    def delete_file(self, volume_id: int, path: str) -> Any:
        """Delete a file from a volume."""
        return self._c.delete(f"/volumes/{volume_id}/files/{path}")

    # ── Sync logs ────────────────────────────────────────────────────

    def sync_logs(
        self,
        *,
        volume_id: Optional[int] = None,
        limit: int = 50,
    ) -> Any:
        """Get volume sync logs."""
        params: Dict[str, Any] = {"limit": limit}
        if volume_id is not None:
            params["volume_id"] = volume_id
        return self._c.get("/volumes/sync-logs", params=params)

    def cancel_sync(self, log_id: int) -> Any:
        """Cancel a pending sync operation."""
        return self._c.post(f"/volumes/sync-logs/{log_id}/cancel")

    # ── Pricing ──────────────────────────────────────────────────────

    def pricing(self) -> Any:
        """Get volume pricing info."""
        return self._c.get("/volumes/pricing")
