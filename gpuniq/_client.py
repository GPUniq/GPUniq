"""Low-level HTTP client for GPUniq API."""

import time
from typing import Any, Dict, Optional

import requests

from ._exceptions import (
    AuthenticationError,
    GPUniqError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

DEFAULT_BASE_URL = "https://api.gpuniq.com/v1"
DEFAULT_TIMEOUT = 60
MAX_RATE_LIMIT_RETRIES = 3


class HTTPClient:
    """Internal HTTP client handling auth, errors, and rate limit retries."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        })
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Any = None,
        files: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        raw_response: bool = False,
    ) -> Any:
        url = f"{self._base_url}{path}"

        req_headers = {}
        if headers:
            req_headers.update(headers)

        # Remove Content-Type for multipart uploads
        if files:
            req_headers["Content-Type"] = None

        # Filter None values from params
        if params:
            params = {k: v for k, v in params.items() if v is not None}

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            resp = self._session.request(
                method=method,
                url=url,
                params=params,
                json=json,
                data=data,
                files=files,
                headers=req_headers,
                timeout=timeout or self._timeout,
            )

            # Rate limited — retry with backoff
            if resp.status_code == 429:
                if attempt < MAX_RATE_LIMIT_RETRIES:
                    retry_after = int(resp.headers.get("Retry-After", 2))
                    time.sleep(retry_after)
                    continue
                raise RateLimitError(
                    "Rate limit exceeded",
                    retry_after=int(resp.headers.get("Retry-After", 60)),
                )
            break

        # Return raw response for file downloads
        if raw_response:
            if resp.status_code >= 400:
                self._raise_for_status(resp)
            return resp

        # Parse JSON response
        if resp.status_code == 401:
            raise AuthenticationError()
        if resp.status_code == 404:
            raise NotFoundError()
        if resp.status_code == 422:
            try:
                body = resp.json()
                detail = body.get("detail", body.get("message", "Validation error"))
                raise ValidationError(str(detail), details=body.get("detail"))
            except (ValueError, KeyError):
                raise ValidationError("Validation error")

        if resp.status_code >= 400:
            self._raise_for_status(resp)

        body = resp.json()

        # Unwrap ResponseSchema: {"exception": 0, "data": ..., "message": ...}
        if isinstance(body, dict) and "exception" in body:
            if body["exception"] != 0:
                raise GPUniqError(
                    message=body.get("message", "Unknown error"),
                    error_code=str(body["exception"]),
                    http_status=resp.status_code,
                )
            return body.get("data")

        return body

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def _raise_for_status(self, resp: requests.Response) -> None:
        try:
            body = resp.json()
            message = body.get("message", body.get("detail", resp.text))
        except (ValueError, KeyError):
            message = resp.text
        raise GPUniqError(
            message=str(message),
            http_status=resp.status_code,
        )
