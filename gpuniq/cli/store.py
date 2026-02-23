import json
import os
from typing import List, Optional


class CommandStore:
    """Local checkpoint persistence on the volume."""

    def __init__(self, manifest_path: str, logs_dir: str):
        self.manifest_path = manifest_path
        self.logs_dir = logs_dir

    def load_manifest(self) -> dict:
        if not os.path.isfile(self.manifest_path):
            return {"version": 1, "checkpoints": []}
        with open(self.manifest_path, "r") as f:
            return json.load(f)

    def _save_manifest(self, data: dict) -> None:
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, self.manifest_path)

    def add_checkpoint(self, checkpoint: dict) -> None:
        manifest = self.load_manifest()
        manifest["checkpoints"].append(checkpoint)
        self._save_manifest(manifest)

    def update_checkpoint(self, checkpoint_id: str, updates: dict) -> None:
        manifest = self.load_manifest()
        for cp in manifest["checkpoints"]:
            if cp["checkpoint_id"] == checkpoint_id:
                cp.update(updates)
                break
        self._save_manifest(manifest)

    def get_checkpoints(self) -> List[dict]:
        return self.load_manifest().get("checkpoints", [])

    def log_path(self, checkpoint_id: str) -> str:
        return os.path.join(self.logs_dir, f"{checkpoint_id}.log")

    def total_log_size(self) -> int:
        total = 0
        if os.path.isdir(self.logs_dir):
            for name in os.listdir(self.logs_dir):
                path = os.path.join(self.logs_dir, name)
                if os.path.isfile(path):
                    total += os.path.getsize(path)
        return total
