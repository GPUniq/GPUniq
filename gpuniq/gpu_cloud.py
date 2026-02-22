"""GPU Cloud — browse and deploy GPU instances."""

from typing import Any, Dict, Optional


class GPUCloud:
    """GPU Cloud: browse available GPUs, check pricing, deploy instances."""

    def __init__(self, client):
        self._c = client

    def list_instances(
        self,
        *,
        search: Optional[str] = None,
        secure_cloud: bool = False,
        min_gpu_count: Optional[int] = None,
        min_ram_gb: Optional[float] = None,
        min_vram_gb: Optional[float] = None,
        min_memory_gb: Optional[float] = None,
    ) -> Dict[str, Any]:
        """List available GPU instance types.

        Args:
            search: Search by GPU name.
            secure_cloud: Only show secure cloud instances.
            min_gpu_count: Minimum GPU count filter.
            min_ram_gb: Minimum RAM filter.
            min_vram_gb: Minimum VRAM filter.
            min_memory_gb: Minimum memory filter.
        """
        return self._c.get("/gpu-cloud/instances", params={
            "search": search,
            "secure_cloud": secure_cloud,
            "min_gpu_count": min_gpu_count,
            "min_ram_gb": min_ram_gb,
            "min_vram_gb": min_vram_gb,
            "min_memory_gb": min_memory_gb,
        })

    def pricing(
        self,
        gpu_name: str,
        *,
        gpu_count: int = 1,
        disk_gb: int = 20,
        secure_cloud: bool = False,
    ) -> Dict[str, Any]:
        """Get pricing for a specific GPU configuration.

        Args:
            gpu_name: GPU name (e.g. "RTX_4090").
            gpu_count: Number of GPUs (default 1).
            disk_gb: Disk size in GB (default 20).
            secure_cloud: Use secure cloud.
        """
        return self._c.get(f"/gpu-cloud/instances/{gpu_name}/pricing", params={
            "gpu_count": gpu_count,
            "disk_gb": disk_gb,
            "secure_cloud": secure_cloud,
        })

    def deploy(
        self,
        gpu_name: str,
        *,
        gpu_count: int = 1,
        docker_image: str = "vastai/pytorch:cuda-12.9.1-auto",
        disk_gb: int = 50,
        volume_id: Optional[int] = None,
        secure_cloud: bool = False,
    ) -> Dict[str, Any]:
        """Deploy a GPU Cloud instance.

        Args:
            gpu_name: GPU name (e.g. "RTX_4090").
            gpu_count: Number of GPUs (1-8, default 1).
            docker_image: Docker image to use.
            disk_gb: Disk size in GB (20-2048, default 50).
            volume_id: Optional volume to attach.
            secure_cloud: Deploy on secure cloud.
        """
        body: Dict[str, Any] = {
            "gpu_name": gpu_name,
            "gpu_count": gpu_count,
            "docker_image": docker_image,
            "disk_gb": disk_gb,
            "secure_cloud": secure_cloud,
        }
        if volume_id is not None:
            body["volume_id"] = volume_id
        return self._c.post("/gpu-cloud/deploy", json=body)
