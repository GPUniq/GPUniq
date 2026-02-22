"""GPUniq SDK exceptions."""

from typing import Optional


class GPUniqError(Exception):
    """Base exception for GPUniq API errors."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        http_status: Optional[int] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.http_status = http_status
        super().__init__(self.message)


class AuthenticationError(GPUniqError):
    """Raised on 401 Unauthorized."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, error_code="UNAUTHORIZED", http_status=401)


class RateLimitError(GPUniqError):
    """Raised on 429 Too Many Requests."""

    def __init__(self, message: str, retry_after: Optional[int] = None):
        self.retry_after = retry_after
        super().__init__(message, error_code="RATE_LIMIT_EXCEEDED", http_status=429)


class NotFoundError(GPUniqError):
    """Raised on 404 Not Found."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, error_code="NOT_FOUND", http_status=404)


class ValidationError(GPUniqError):
    """Raised on 422 Validation Error."""

    def __init__(self, message: str, details: Optional[list] = None):
        self.details = details
        super().__init__(message, error_code="VALIDATION_ERROR", http_status=422)
