"""GPUniq — Python SDK for GPUniq GPU Meta-Cloud platform.

Usage::

    from gpuniq import GPUniq

    client = GPUniq(api_key="gpuniq_your_key_here")

    # GPU Marketplace
    gpus = client.marketplace.list(sort_by="price-low")
    order = client.marketplace.create_order(agent_id=123, pricing_type="hour")

    # Instances
    instances = client.instances.list()
    client.instances.start(task_id=456)

    # Volumes
    volumes = client.volumes.list()
    client.volumes.create(name="my-data", size_limit_gb=20)

    # LLM Chat
    response = client.llm.chat("openai/gpt-oss-120b", "Hello!")

    # GPU Cloud
    client.gpu_cloud.deploy(gpu_name="RTX_4090")
"""

from ._client import DEFAULT_BASE_URL, HTTPClient
from ._exceptions import (
    AuthenticationError,
    GPUniqError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from .burst import Burst
from .gpu_cloud import GPUCloud
from .instances import Instances
from .llm import LLM
from .marketplace import Marketplace
from .payments import Payments
from .settings import Settings
from .volumes import Volumes

__version__ = "2.0.1"
__all__ = [
    "GPUniq",
    "GPUniqError",
    "AuthenticationError",
    "RateLimitError",
    "NotFoundError",
    "ValidationError",
    "init",
]


class GPUniq:
    """GPUniq SDK client.

    Provides access to all GPUniq platform APIs through resource attributes.

    Args:
        api_key: Your GPUniq API key (starts with "gpuniq_").
        base_url: API base URL (default: https://api.gpuniq.com/v1).
        timeout: Default request timeout in seconds (default: 60).
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 60,
    ):
        if not api_key:
            raise ValueError("API key is required")
        if not api_key.startswith("gpuniq_"):
            raise ValueError("Invalid API key format. Key should start with 'gpuniq_'")

        self._http = HTTPClient(api_key=api_key, base_url=base_url, timeout=timeout)

        self.marketplace = Marketplace(self._http)
        self.instances = Instances(self._http)
        self.volumes = Volumes(self._http)
        self.burst = Burst(self._http)
        self.payments = Payments(self._http)
        self.settings = Settings(self._http)
        self.llm = LLM(self._http)
        self.gpu_cloud = GPUCloud(self._http)

    # Backward compatibility with v1.x
    def request(
        self,
        model: str,
        message: str,
        role: str = "user",
        timeout: int = 30,
    ) -> str:
        """Send a simple LLM request (v1.x backward compatibility).

        Use ``client.llm.chat()`` for new code.
        """
        return self.llm.chat(model, message, role=role, timeout=timeout)


# Backward compatibility: gpuniq.init("key") still works
GPUniqClient = GPUniq


def init(api_key: str) -> GPUniq:
    """Initialize and return a GPUniq client.

    Backward-compatible with v1.x. Equivalent to ``GPUniq(api_key=...)``.
    """
    return GPUniq(api_key=api_key)
