"""Burst — multi-GPU burst deployment orders."""

from typing import Any, Dict, List, Optional


class Burst:
    """Burst GPU deployments: create multi-GPU orders with fallback GPUs."""

    def __init__(self, client):
        self._c = client

    # ── Orders CRUD ──────────────────────────────────────────────────

    def create_order(
        self,
        docker_image: str,
        primary_gpu: str,
        gpu_count: int,
        *,
        extra_gpus: Optional[List[Dict[str, Any]]] = None,
        volume_id: Optional[int] = None,
        disk_gb: int = 50,
    ) -> Dict[str, Any]:
        """Create a burst order.

        Args:
            docker_image: Docker image to deploy.
            primary_gpu: Primary GPU name (e.g. "RTX_4090").
            gpu_count: Number of GPUs to provision (1-100).
            extra_gpus: Optional fallback GPUs, e.g. [{"gpu_name": "RTX_3090", "max_price": 0.5}].
            volume_id: Optional volume to attach.
            disk_gb: Disk size in GB (20-1024, default 50).
        """
        body: Dict[str, Any] = {
            "docker_image": docker_image,
            "primary_gpu": primary_gpu,
            "gpu_count": gpu_count,
            "disk_gb": disk_gb,
        }
        if extra_gpus is not None:
            body["extra_gpus"] = extra_gpus
        if volume_id is not None:
            body["volume_id"] = volume_id
        return self._c.post("/burst/orders", json=body)

    def list_orders(self, *, limit: int = 100, offset: int = 0) -> Any:
        """List your burst orders."""
        return self._c.get("/burst/orders", params={"limit": limit, "offset": offset})

    def get_order(self, order_id: int) -> Dict[str, Any]:
        """Get burst order details."""
        return self._c.get(f"/burst/orders/{order_id}")

    # ── Order actions ────────────────────────────────────────────────

    def start_order(self, order_id: int) -> Dict[str, Any]:
        """Start a burst order."""
        return self._c.post(f"/burst/orders/{order_id}/start")

    def stop_order(self, order_id: int) -> Dict[str, Any]:
        """Stop a burst order."""
        return self._c.post(f"/burst/orders/{order_id}/stop")

    def delete_order(self, order_id: int) -> Dict[str, Any]:
        """Delete a burst order."""
        return self._c.delete(f"/burst/orders/{order_id}")

    # ── Order history ────────────────────────────────────────────────

    def transactions(self, order_id: int, *, limit: int = 50, offset: int = 0) -> Any:
        """Get billing transactions for a burst order."""
        return self._c.get(
            f"/burst/orders/{order_id}/transactions",
            params={"limit": limit, "offset": offset},
        )

    def runs(self, order_id: int, *, limit: int = 50, offset: int = 0) -> Any:
        """Get GPU run history for a burst order."""
        return self._c.get(
            f"/burst/orders/{order_id}/runs",
            params={"limit": limit, "offset": offset},
        )

    # ── Utilities ────────────────────────────────────────────────────

    def estimate(
        self,
        docker_image: str,
        primary_gpu: str,
        gpu_count: int,
        *,
        extra_gpus: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Estimate cost for a burst deployment (does not create order)."""
        body: Dict[str, Any] = {
            "docker_image": docker_image,
            "primary_gpu": primary_gpu,
            "requested_quantity": gpu_count,
        }
        if extra_gpus is not None:
            body["extra_gpus"] = extra_gpus
        return self._c.post("/burst/estimate", json=body)

    def check_image_size(
        self,
        image: str,
        *,
        platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Check Docker image size before deploying."""
        body: Dict[str, Any] = {"image": image}
        if platform is not None:
            body["platform"] = platform
        return self._c.post("/burst/image-size", json=body)
