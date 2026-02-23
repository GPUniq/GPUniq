import json
import os
from datetime import datetime, timezone
from typing import Optional


DEFAULT_GG_DIR = "/workspace/volume/.gg"
DEFAULT_API_URL = "https://api.gpuniq.com/v1"

CONFIG_FILENAME = "config.json"
MANIFEST_FILENAME = "checkpoints.json"
LOGS_DIR = "logs"


class GGConfig:
    """Manages gg CLI configuration stored in the volume."""

    def __init__(self, gg_dir: str = DEFAULT_GG_DIR):
        self.gg_dir = gg_dir
        self.config_path = os.path.join(gg_dir, CONFIG_FILENAME)
        self.manifest_path = os.path.join(gg_dir, MANIFEST_FILENAME)
        self.logs_dir = os.path.join(gg_dir, LOGS_DIR)

    def exists(self) -> bool:
        return os.path.isfile(self.config_path)

    def ensure_dirs(self) -> None:
        os.makedirs(self.logs_dir, exist_ok=True)

    def save(
        self,
        token: str,
        api_base_url: str,
        task_id: int,
        instance_name: Optional[str] = None,
    ) -> None:
        self.ensure_dirs()
        data = {
            "version": 1,
            "token": token,
            "api_base_url": api_base_url,
            "task_id": task_id,
            "instance_name": instance_name,
            "initialized_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self.config_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.config_path)

        # Initialize empty manifest if it doesn't exist
        if not os.path.isfile(self.manifest_path):
            tmp_m = self.manifest_path + ".tmp"
            with open(tmp_m, "w") as f:
                json.dump({"version": 1, "checkpoints": []}, f, indent=2)
            os.replace(tmp_m, self.manifest_path)

    def load(self) -> dict:
        if not self.exists():
            raise FileNotFoundError(
                f"gg not initialized. Run: gg init <token>\n"
                f"Expected config at: {self.config_path}"
            )
        with open(self.config_path, "r") as f:
            return json.load(f)

    @property
    def token(self) -> str:
        return self.load()["token"]

    @property
    def api_base_url(self) -> str:
        return self.load()["api_base_url"]

    @property
    def task_id(self) -> int:
        return self.load()["task_id"]
