import json
import os
from typing import Optional


DEFAULT_CLIENT_DIR = os.path.join(os.path.expanduser("~"), ".gpuniq")
DEFAULT_API_URL = "https://api.gpuniq.com/v1"

CONFIG_FILENAME = "config.json"


class ClientConfig:
    """Manages gg CLI client configuration stored in ~/.gpuniq/."""

    def __init__(self, config_dir: str = DEFAULT_CLIENT_DIR):
        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, CONFIG_FILENAME)

    def exists(self) -> bool:
        return os.path.isfile(self.config_path)

    def save(self, api_key: str, api_base_url: str = DEFAULT_API_URL, username: Optional[str] = None) -> None:
        os.makedirs(self.config_dir, exist_ok=True)
        data = {
            "version": 1,
            "api_key": api_key,
            "api_base_url": api_base_url,
            "username": username,
        }
        tmp = self.config_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.config_path)

    def load(self) -> dict:
        if not self.exists():
            raise FileNotFoundError(
                "Not logged in. Run: gg login"
            )
        with open(self.config_path, "r") as f:
            return json.load(f)

    @property
    def api_key(self) -> str:
        return self.load()["api_key"]

    @property
    def api_base_url(self) -> str:
        return self.load().get("api_base_url", DEFAULT_API_URL)
