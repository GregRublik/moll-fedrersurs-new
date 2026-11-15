from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BitrixApiError(Exception):
    method: str
    code: str | None
    description: str | None
    http_status: int | None = None

    def __str__(self) -> str:
        return f"{self.method}: HTTP {self.http_status}, error={self.code!r}, description={self.description!r}"


TRANSIENT_ERRORS = {
    "QUERY_LIMIT_EXCEEDED",
    "OVERLOAD_LIMIT",
    "INTERNAL_SERVER_ERROR",
    "OPERATION_TIME_LIMIT",
}

AUTH_ERRORS = {
    "NO_AUTH_FOUND",
    "INVALID_CREDENTIALS",
    "insufficient_scope",
    "expired_token",
    "ACCESS_DENIED",
    "PORTAL_DELETED",
}
