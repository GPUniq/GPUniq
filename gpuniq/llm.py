"""LLM — chat completions, image generation, chat sessions."""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict, List, Optional, Sequence, Union


DEFAULT_IMAGE_MODEL = "nano-banana"
_IMAGE_JOB_POLL_SECS = 3.0
_IMAGE_JOB_MAX_WAIT = 300  # 5 minutes


class LLM:
    """LLM API surface on the GPUniq platform.

    Billing is direct USD debit from ``user.balance`` — no token pool.

    Entry points:
        chat(...)                   — one-shot chat, returns plain text
        chat_completion(...)        — full request with message history, returns dict
        generate_image(...)         — synchronous image generation
        generate_image_async(...)   — async + poll convenience (Nano Banana)
        balance()                   — current USD balance
        models()                    — available text model slugs
    """

    def __init__(self, client):
        self._c = client

    # ── Chat completions ─────────────────────────────────────────────

    def chat(
        self,
        model: str,
        message: str,
        *,
        role: str = "user",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 120,
    ) -> str:
        """Send a single-turn chat message and get the reply text.

        Use :meth:`chat_completion` when you need the full response envelope
        (tokens used, cost, finish reason) or multi-turn history.
        """
        data = self.chat_completion(
            messages=[{"role": role, "content": message}],
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
            timeout=timeout,
        )
        return data.get("content", "")

    def chat_completion(
        self,
        messages: Sequence[Dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Send a full chat completion request.

        Response dict keys: ``content``, ``model``, ``tokens_used``,
        ``cost_usd``, ``balance_usd``, ``finish_reason``.
        """
        body: Dict[str, Any] = {"messages": list(messages)}
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if top_p is not None:
            body["top_p"] = top_p
        if presence_penalty is not None:
            body["presence_penalty"] = presence_penalty
        return self._c.post("/llm/chat/completions", json=body, timeout=timeout)

    # ── Image generation ─────────────────────────────────────────────

    def generate_image(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_IMAGE_MODEL,
        n: int = 1,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        response_format: str = "b64_json",
        input_images: Optional[Sequence[Union[str, bytes, os.PathLike]]] = None,
        save_to: Optional[Union[str, os.PathLike]] = None,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """Synchronously generate images from a prompt.

        Args:
            prompt: Text description.
            model: Image model slug (default: ``nano-banana``).
            n: Number of images to generate (1-4).
            size: Optional size hint (e.g. ``"1024x1024"``, ``"2048x2048"``).
            quality: Optional quality hint (``"standard"`` / ``"hd"``).
            response_format: ``"b64_json"`` (default, inline base64) or ``"url"``.
            input_images: Optional reference images for image-to-image flows.
                Each entry can be a local file path, raw bytes, a ``data:`` URL,
                an ``https://`` URL, or a bare base64 string.
            save_to: If set, decode each returned image and write to disk. Accepts
                either a single filename (single image) or a directory path. The
                list of written file paths is returned in the result under
                ``saved_paths``.
            timeout: Request timeout (default 180s).

        Returns:
            Dict with keys ``images``, ``model``, ``image_count``, ``cost_usd``,
            ``balance_usd``. When ``save_to`` is provided, also includes
            ``saved_paths: List[str]``.
        """
        body: Dict[str, Any] = {"prompt": prompt, "model": model, "n": int(n)}
        if size is not None:
            body["size"] = size
        if quality is not None:
            body["quality"] = quality
        if response_format:
            body["response_format"] = response_format
        if input_images:
            body["input_images"] = [_coerce_reference_image(x) for x in input_images]

        result = self._c.post("/llm/images/generations", json=body, timeout=timeout)

        if save_to and result and result.get("images"):
            result["saved_paths"] = _write_images(result["images"], save_to)
        return result

    def start_image_job(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_IMAGE_MODEL,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        input_images: Optional[Sequence[Union[str, bytes, os.PathLike]]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Kick off an async image-generation job. Returns ``{job_id, status}``.

        Only Nano Banana slugs are accepted on this surface and the backend
        enforces ``n=1``. Pair with :meth:`get_image_job` to poll.
        """
        body: Dict[str, Any] = {"prompt": prompt, "model": model, "n": 1}
        if size is not None:
            body["size"] = size
        if quality is not None:
            body["quality"] = quality
        if input_images:
            body["input_images"] = [_coerce_reference_image(x) for x in input_images]
        return self._c.post("/llm/images/jobs", json=body, timeout=timeout)

    def get_image_job(self, job_id: str, *, timeout: int = 15) -> Dict[str, Any]:
        """Return the current status of an image-generation job."""
        return self._c.get(f"/llm/images/jobs/{job_id}", timeout=timeout)

    def generate_image_async(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_IMAGE_MODEL,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        input_images: Optional[Sequence[Union[str, bytes, os.PathLike]]] = None,
        save_to: Optional[Union[str, os.PathLike]] = None,
        max_wait_seconds: int = _IMAGE_JOB_MAX_WAIT,
        poll_interval_seconds: float = _IMAGE_JOB_POLL_SECS,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Start an image job and block until it is ``completed`` or ``failed``.

        Useful when the sync endpoint would exceed a proxy's read timeout
        (Cloudflare caps requests at ~100s). Uses the job-based surface under
        the hood.
        """
        job = self.start_image_job(
            prompt, model=model, size=size, quality=quality, input_images=input_images,
        )
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            raise RuntimeError(f"start_image_job returned no job_id: {job!r}")

        deadline = time.monotonic() + max_wait_seconds
        last_status = None
        while True:
            status = self.get_image_job(job_id)
            current = status.get("status")
            if current != last_status and on_progress:
                on_progress(current, status)
                last_status = current
            if current == "completed":
                if save_to and status.get("images"):
                    status["saved_paths"] = _write_images(status["images"], save_to)
                return status
            if current == "failed":
                raise RuntimeError(
                    f"Image job {job_id} failed: {status.get('error') or status}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Image job {job_id} still {current!r} after {max_wait_seconds}s"
                )
            time.sleep(poll_interval_seconds)

    # ── Balance & models ─────────────────────────────────────────────

    def balance(self) -> Dict[str, Any]:
        """Return the user's balance in USD that pays for chat + images."""
        return self._c.get("/llm/balance")

    def models(self) -> List[str]:
        """Return the list of available text model slugs."""
        data = self._c.get("/llm/models")
        return list(data.get("models", [])) if isinstance(data, dict) else list(data or [])

    def default_model(self) -> Optional[str]:
        """Return the platform-default text model slug."""
        data = self._c.get("/llm/models")
        return data.get("default_model") if isinstance(data, dict) else None

    def model_catalog(self) -> Any:
        """Return the full catalog (text + image models with pricing metadata)."""
        return self._c.get("/llm/models/catalog")

    # ── Chat sessions (persistent multi-turn conversations) ──────────

    def create_chat_session(self, model: str, *, title: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"model": model}
        if title is not None:
            body["title"] = title
        return self._c.post("/llm/chats", json=body)

    def list_chat_sessions(self, *, limit: int = 50, offset: int = 0) -> Any:
        return self._c.get("/llm/chats", params={"limit": limit, "offset": offset})

    def get_chat_session(self, chat_id: int) -> Dict[str, Any]:
        return self._c.get(f"/llm/chats/{chat_id}")

    def update_chat_session(
        self, chat_id: int, *, title: Optional[str] = None, model: Optional[str] = None
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if model is not None:
            body["model"] = model
        return self._c.patch(f"/llm/chats/{chat_id}", json=body)

    def delete_chat_session(self, chat_id: int) -> Any:
        return self._c.delete(f"/llm/chats/{chat_id}")

    def send_message(
        self,
        chat_id: int,
        message: str,
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        input_images: Optional[Sequence[Union[str, bytes, os.PathLike]]] = None,
        size: Optional[str] = None,
        n: Optional[int] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """Send a message inside a persistent chat session.

        Works for text and image models. When the chat's model is an image
        slug, ``message`` is the prompt and ``input_images`` / ``size`` / ``n``
        configure the upstream image call.
        """
        body: Dict[str, Any] = {"message": message}
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if input_images is not None:
            body["input_images"] = [_coerce_reference_image(x) for x in input_images]
        if size is not None:
            body["size"] = size
        if n is not None:
            body["n"] = int(n)
        return self._c.post(f"/llm/chats/{chat_id}/messages", json=body, timeout=timeout)

    # ── Usage history ────────────────────────────────────────────────

    def usage_history(self, *, limit: int = 50, offset: int = 0) -> Any:
        return self._c.get("/llm/usage/history", params={"limit": limit, "offset": offset})


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _coerce_reference_image(entry: Union[str, bytes, os.PathLike]) -> str:
    """Turn a user-supplied reference image into the on-wire format.

    Accepts:
        * local file path (str / PathLike that exists) → ``data:`` URL
        * ``data:`` URL or ``http(s)://`` URL → passed through verbatim
        * bare base64 str → passed through
        * ``bytes`` / ``bytearray`` → base64-encoded bare string
    """
    if isinstance(entry, (bytes, bytearray)):
        return base64.b64encode(bytes(entry)).decode("ascii")
    if isinstance(entry, os.PathLike):
        entry = os.fspath(entry)
    if isinstance(entry, str):
        stripped = entry.strip()
        if stripped.startswith("data:") or stripped.startswith(("http://", "https://")):
            return stripped
        if os.path.isfile(stripped):
            mime = _guess_image_mime(stripped)
            with open(stripped, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"data:{mime};base64,{b64}"
        return stripped  # assume bare base64
    raise TypeError(f"Unsupported reference image type: {type(entry).__name__}")


def _guess_image_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")


def _write_images(
    images: List[Dict[str, Any]],
    save_to: Union[str, os.PathLike],
) -> List[str]:
    """Decode and persist each image. ``save_to`` is a filename (single image)
    or a directory (any count). Returns the written paths."""
    target = os.fspath(save_to)
    is_dir = os.path.isdir(target) or (len(images) > 1 and not os.path.splitext(target)[1])
    if is_dir:
        os.makedirs(target, exist_ok=True)

    paths: List[str] = []
    for idx, entry in enumerate(images):
        if "b64_json" in entry and entry["b64_json"]:
            data = base64.b64decode(entry["b64_json"])
        elif "url" in entry and entry["url"]:
            raise NotImplementedError(
                "save_to doesn't download URL results — pass response_format='b64_json'"
            )
        else:
            raise RuntimeError(f"Image #{idx} has no b64_json or url payload")

        if is_dir:
            path = os.path.join(target, f"image_{idx + 1}.png")
        elif len(images) == 1:
            path = target
        else:
            base, ext = os.path.splitext(target)
            path = f"{base}_{idx + 1}{ext or '.png'}"
        with open(path, "wb") as f:
            f.write(data)
        paths.append(path)
    return paths
