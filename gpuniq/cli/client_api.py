import sys
from typing import List, Optional

import requests


def _extract_error_detail(response) -> str:
    """Best-effort pull of a human-readable error message from a requests.Response.

    Handles three FastAPI shapes: {detail: str}, {detail: {message|message_ru|detail}},
    {detail: [{msg}...]} (validation errors), and falls back to the raw text body."""
    if response is None:
        return ""
    body = None
    try:
        body = response.json()
    except Exception:
        text = (response.text or "").strip()
        return text[:500]

    if isinstance(body, dict):
        detail = body.get("detail", body)
    else:
        detail = body

    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return (
            detail.get("message")
            or detail.get("message_ru")
            or detail.get("detail")
            or str(detail)
        )
    if isinstance(detail, list) and detail:
        # Pydantic validation: each entry usually has {loc, msg, type}
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                msg = item.get("msg") or ""
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(p for p in parts if p)
    return str(detail)


class OrderOfferGone(Exception):
    """Raised when POST /marketplace/order returns 410 — offer is no longer available
    (another user rented it, or the provider removed it). Callers typically handle this
    by letting the user pick a different offer."""

    def __init__(self, message: str, agent_id):
        super().__init__(message)
        self.message = message
        self.agent_id = agent_id


class ClientAPI:
    """HTTP client for GPUniq API using API key authentication (X-API-Key)."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = api_key
        self.session.headers["Content-Type"] = "application/json"
        self.timeout = timeout

    def verify_key(self) -> Optional[dict]:
        """Verify API key by fetching instances. Returns user info or None."""
        try:
            resp = self.session.get(
                f"{self.base_url}/instances/my?page=1&page_size=1",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            self.send_heartbeat()
            return resp.json()
        except Exception as e:
            print(f"[gg] Error: API key verification failed: {e}", file=sys.stderr)
            return None

    def send_heartbeat(self) -> None:
        """Send heartbeat to backend so the web UI knows CLI is connected."""
        try:
            from importlib.metadata import version as pkg_version
            cli_version = pkg_version("gpuniq")
        except Exception:
            cli_version = "unknown"
        try:
            self.session.post(
                f"{self.base_url}/cli/heartbeat",
                json={"version": cli_version},
                timeout=5,
            )
        except Exception:
            pass  # non-critical, don't block CLI

    def get_instances(self, page: int = 1, page_size: int = 50) -> Optional[dict]:
        """Get user's rented instances with SSH connection data."""
        try:
            resp = self.session.get(
                f"{self.base_url}/instances/my?page={page}&page_size={page_size}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as e:
            print(f"[gg] Error: could not fetch instances: {e}", file=sys.stderr)
            return None

    def get_instance_ssh_keys(self, instance_id: int) -> Optional[List[dict]]:
        """Get SSH keys attached to an instance."""
        try:
            resp = self.session.get(
                f"{self.base_url}/instances/{instance_id}/ssh-keys",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data.get("ssh_keys", [])
        except Exception as e:
            print(f"[gg] Warning: could not fetch SSH keys: {e}", file=sys.stderr)
            return None

    def attach_ssh_key(self, instance_id: int, key_id: int) -> bool:
        """Attach an SSH key to an instance."""
        try:
            resp = self.session.post(
                f"{self.base_url}/instances/{instance_id}/ssh-keys",
                json={"ssh_key_id": key_id},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[gg] Warning: could not attach SSH key: {e}", file=sys.stderr)
            return False

    def stop_instance(self, task_id: int) -> Optional[dict]:
        """Stop a running instance (leaves it terminable later)."""
        try:
            resp = self.session.post(
                f"{self.base_url}/instances/{task_id}/stop",
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as e:
            print(f"[gg] Error: could not stop instance: {e}", file=sys.stderr)
            return None

    def delete_instance(self, task_id: int) -> bool:
        """Fully destroy an instance — terminates the provider machine, releases
        the SSH proxy port, and soft-deletes the task. Use this for `gg replace`
        where we never want the old instance back."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/instances/{task_id}",
                timeout=60,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[gg] Error: could not delete instance: {e}", file=sys.stderr)
            return False

    def ensure_ssh_proxy(self, task_id: int) -> Optional[dict]:
        """Ensure the instance has an SSH proxy (ssh.gpuniq.com) allocated.
        Returns {ssh_host, ssh_port, ssh_username} on success, None on failure
        (caller should fall back to direct IP)."""
        try:
            resp = self.session.post(
                f"{self.base_url}/instances/{task_id}/ssh-proxy/ensure",
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception:
            # Endpoint may not be deployed yet or the task may not support proxy —
            # silently fall back to whatever SSH info is already on the instance.
            return None

    # ─── SSH Keys (account-level) ────────────────────────────────────────────

    def list_ssh_keys(self) -> Optional[List[dict]]:
        """List user's SSH keys."""
        try:
            resp = self.session.get(
                f"{self.base_url}/settings/ssh-keys",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return data.get("ssh_keys", [])
        except Exception as e:
            print(f"[gg] Error: could not fetch SSH keys: {e}", file=sys.stderr)
            return None

    def add_ssh_key(self, key_name: str, public_key: str) -> Optional[dict]:
        """Add an SSH public key to the account."""
        try:
            resp = self.session.post(
                f"{self.base_url}/settings/ssh-keys",
                json={"key_name": key_name, "public_key": public_key},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                pass
            if "already exists" in str(detail).lower() or "duplicate" in str(detail).lower():
                print(f"[gg] This SSH key is already in your account.", file=sys.stderr)
            else:
                print(f"[gg] Error: could not add SSH key: {detail or e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[gg] Error: could not add SSH key: {e}", file=sys.stderr)
            return None

    def delete_ssh_key(self, key_id: int) -> bool:
        """Delete an SSH key from the account."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/settings/ssh-keys/{key_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[gg] Error: could not delete SSH key: {e}", file=sys.stderr)
            return False

    # ─── Volumes ─────────────────────────────────────────────────────────────

    def list_volumes(self) -> Optional[List[dict]]:
        """List user's volumes."""
        try:
            resp = self.session.get(
                f"{self.base_url}/volumes/",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[gg] Error: could not fetch volumes: {e}", file=sys.stderr)
            return None

    def create_volume(self, name: str, size_limit_gb: float = 10.0, description: str = None) -> Optional[dict]:
        """Create a new volume."""
        body = {"name": name, "size_limit_gb": size_limit_gb}
        if description:
            body["description"] = description
        try:
            resp = self.session.post(
                f"{self.base_url}/volumes/",
                json=body,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                pass
            print(f"[gg] Error: could not create volume: {detail or e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[gg] Error: could not create volume: {e}", file=sys.stderr)
            return None

    def delete_volume(self, volume_id: int) -> bool:
        """Delete a volume."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/volumes/{volume_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[gg] Error: could not delete volume: {e}", file=sys.stderr)
            return False

    # ─── Marketplace (browse + rent GPUs) ────────────────────────────────────

    def list_marketplace(
        self,
        page: int = 1,
        page_size: int = 10,
        gpu_model: Optional[List[str]] = None,
        min_gpu_count: Optional[int] = None,
        max_price_per_hour: Optional[float] = None,
        verified_only: Optional[bool] = None,
        sort_by: str = "price-low",
        search: Optional[str] = None,
    ) -> Optional[dict]:
        """Browse available GPUs in the marketplace."""
        params: dict = {"page": page, "page_size": page_size, "sort_by": sort_by}
        if gpu_model:
            params["gpu_model"] = gpu_model
        if min_gpu_count is not None:
            params["gpu_count"] = min_gpu_count
        if max_price_per_hour is not None:
            params["max_price_per_hour"] = max_price_per_hour
        if verified_only:
            params["verified"] = "true"
        if search:
            params["search"] = search

        try:
            resp = self.session.get(
                f"{self.base_url}/marketplace/list",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as e:
            print(f"[gg] Error: could not fetch marketplace: {e}", file=sys.stderr)
            return None

    def get_agent_details(self, agent_id) -> Optional[dict]:
        """Get full details for a marketplace agent (offer)."""
        try:
            resp = self.session.get(
                f"{self.base_url}/marketplace/agent/{agent_id}",
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except Exception as e:
            print(f"[gg] Error: could not fetch agent details: {e}", file=sys.stderr)
            return None

    def create_order(
        self,
        agent_id,
        pricing_type: str = "hour",
        gpu_required: int = 0,
        ssh_key_ids: Optional[List[int]] = None,
        volume_id: Optional[int] = None,
        docker_image: Optional[str] = None,
        disk_gb: Optional[int] = None,
    ) -> Optional[dict]:
        """Create a GPU rental order (synchronous)."""
        body: dict = {"agent_id": agent_id, "pricing_type": pricing_type}
        if gpu_required:
            body["gpu_required"] = gpu_required
        if ssh_key_ids:
            body["ssh_key_ids"] = ssh_key_ids
        if volume_id:
            body["volume_id"] = volume_id
        if docker_image:
            body["docker_image"] = docker_image
        if disk_gb:
            body["disk_gb"] = disk_gb

        try:
            resp = self.session.post(
                f"{self.base_url}/marketplace/order",
                json=body,
                timeout=120,  # provisioning can take a while
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            detail = _extract_error_detail(e.response)

            # 410 Gone — the specific offer was snapped up or removed between
            # listing and ordering. Let the caller offer an "try another" retry.
            if status == 410:
                raise OrderOfferGone(
                    detail or "This GPU offer is no longer available.",
                    agent_id,
                ) from e

            print(f"[gg] Error: order failed ({status}): {detail or e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[gg] Error: order failed: {e}", file=sys.stderr)
            return None
