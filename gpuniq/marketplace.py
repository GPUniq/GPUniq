"""Marketplace — browse GPUs and create orders."""

from typing import Any, Dict, List, Optional


class Marketplace:
    """GPU marketplace: browse offers, create orders, check availability."""

    def __init__(self, client):
        self._c = client

    # ── Browse ───────────────────────────────────────────────────────

    def statistics(
        self,
        *,
        gpu_model: Optional[List[str]] = None,
        min_ram_gb: Optional[float] = None,
        max_ram_gb: Optional[float] = None,
        min_price_per_hour: Optional[float] = None,
        max_price_per_hour: Optional[float] = None,
        location: Optional[str] = None,
        min_vram_gb: Optional[float] = None,
        max_vram_gb: Optional[float] = None,
        verified_only: Optional[bool] = None,
        min_gpu_count: Optional[int] = None,
        max_gpu_count: Optional[int] = None,
        provider: Optional[str] = None,
        min_disk_gb: Optional[float] = None,
        min_inet_speed_mbps: Optional[float] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get marketplace statistics with optional filters."""
        params = {
            "min_ram_gb": min_ram_gb,
            "max_ram_gb": max_ram_gb,
            "min_price_per_hour": min_price_per_hour,
            "max_price_per_hour": max_price_per_hour,
            "location": location,
            "min_vram_gb": min_vram_gb,
            "max_vram_gb": max_vram_gb,
            "verified_only": verified_only,
            "min_gpu_count": min_gpu_count,
            "max_gpu_count": max_gpu_count,
            "provider": provider,
            "min_disk_gb": min_disk_gb,
            "min_inet_speed_mbps": min_inet_speed_mbps,
            "search": search,
        }
        if gpu_model:
            params["gpu_model"] = gpu_model
        return self._c.get("/marketplace/statistics", params=params)

    def list(
        self,
        *,
        gpu_model: Optional[List[str]] = None,
        min_ram_gb: Optional[float] = None,
        max_ram_gb: Optional[float] = None,
        min_price_per_hour: Optional[float] = None,
        max_price_per_hour: Optional[float] = None,
        location: Optional[str] = None,
        min_vram_gb: Optional[float] = None,
        max_vram_gb: Optional[float] = None,
        verified_only: Optional[bool] = None,
        min_gpu_count: Optional[int] = None,
        max_gpu_count: Optional[int] = None,
        provider: Optional[str] = None,
        min_disk_gb: Optional[float] = None,
        min_inet_speed_mbps: Optional[float] = None,
        search: Optional[str] = None,
        sort_by: str = "price-low",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List available GPU offers with filters and pagination."""
        params = {
            "min_ram_gb": min_ram_gb,
            "max_ram_gb": max_ram_gb,
            "min_price_per_hour": min_price_per_hour,
            "max_price_per_hour": max_price_per_hour,
            "location": location,
            "min_vram_gb": min_vram_gb,
            "max_vram_gb": max_vram_gb,
            "verified_only": verified_only,
            "min_gpu_count": min_gpu_count,
            "max_gpu_count": max_gpu_count,
            "provider": provider,
            "min_disk_gb": min_disk_gb,
            "min_inet_speed_mbps": min_inet_speed_mbps,
            "search": search,
            "sort_by": sort_by,
            "page": page,
            "page_size": page_size,
        }
        if gpu_model:
            params["gpu_model"] = gpu_model
        return self._c.get("/marketplace/list", params=params)

    def get_agent(self, agent_id: int) -> Dict[str, Any]:
        """Get detailed info about a specific agent/offer."""
        return self._c.get(f"/marketplace/agent/{agent_id}")

    # ── Orders ───────────────────────────────────────────────────────

    def create_order(
        self,
        agent_id: int,
        *,
        gpu_required: int = 0,
        docker_image: Optional[str] = None,
        pricing_type: str = "month",
        ssh_key_ids: Optional[List[int]] = None,
        disk_gb: Optional[int] = None,
        web_ports: Optional[Dict[str, int]] = None,
        volume_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a GPU rental order (synchronous)."""
        body = {
            "agent_id": agent_id,
            "gpu_required": gpu_required,
            "pricing_type": pricing_type,
        }
        if docker_image is not None:
            body["docker_image"] = docker_image
        if ssh_key_ids is not None:
            body["ssh_key_ids"] = ssh_key_ids
        if disk_gb is not None:
            body["disk_gb"] = disk_gb
        if web_ports is not None:
            body["web_ports"] = web_ports
        if volume_id is not None:
            body["volume_id"] = volume_id
        return self._c.post("/marketplace/order", json=body)

    def create_order_async(
        self,
        agent_id: int,
        *,
        gpu_required: int = 0,
        docker_image: Optional[str] = None,
        pricing_type: str = "month",
        ssh_key_ids: Optional[List[int]] = None,
        disk_gb: Optional[int] = None,
        web_ports: Optional[Dict[str, int]] = None,
        volume_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a GPU rental order (async — returns job_id for polling)."""
        body = {
            "agent_id": agent_id,
            "gpu_required": gpu_required,
            "pricing_type": pricing_type,
        }
        if docker_image is not None:
            body["docker_image"] = docker_image
        if ssh_key_ids is not None:
            body["ssh_key_ids"] = ssh_key_ids
        if disk_gb is not None:
            body["disk_gb"] = disk_gb
        if web_ports is not None:
            body["web_ports"] = web_ports
        if volume_id is not None:
            body["volume_id"] = volume_id
        return self._c.post("/marketplace/order/async", json=body)

    def get_order_status(self, job_id: str) -> Dict[str, Any]:
        """Poll async order creation status."""
        return self._c.get(f"/marketplace/order/status/{job_id}")

    def check_availability(self, agent_id: int) -> Dict[str, Any]:
        """Check if an offer is still available."""
        return self._c.get(f"/marketplace/offer/{agent_id}/availability")
