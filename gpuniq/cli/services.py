"""Persistent services registry.

Stores commands that must be restarted when the GPU instance is recreated.
File: /workspace/volume/.gg/services.json — survives instance replacement
because it lives on the S3-synced volume.
"""

import json
import os
import uuid
from typing import List


class ServiceStore:
    """Read/write services.json — list of commands to auto-restart."""

    def __init__(self, services_path: str):
        self.services_path = services_path

    def _load(self) -> dict:
        if not os.path.isfile(self.services_path):
            return {"version": 1, "services": []}
        with open(self.services_path, "r") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        tmp = self.services_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, self.services_path)

    def add(self, command: str, working_dir: str) -> dict:
        """Register a persistent service. Returns the new entry."""
        data = self._load()

        # Deduplicate: same command + same dir = update existing
        for svc in data["services"]:
            if svc["command"] == command and svc["working_dir"] == working_dir:
                return svc

        entry = {
            "id": str(uuid.uuid4())[:8],
            "command": command,
            "working_dir": working_dir,
        }
        data["services"].append(entry)
        self._save(data)
        return entry

    def remove(self, service_id: str) -> bool:
        """Remove a service by ID (or prefix). Returns True if found."""
        data = self._load()
        before = len(data["services"])
        data["services"] = [
            s for s in data["services"]
            if not s["id"].startswith(service_id)
        ]
        if len(data["services"]) < before:
            self._save(data)
            return True
        return False

    def get_all(self) -> List[dict]:
        return self._load().get("services", [])

    def clear(self) -> int:
        data = self._load()
        count = len(data["services"])
        data["services"] = []
        self._save(data)
        return count
