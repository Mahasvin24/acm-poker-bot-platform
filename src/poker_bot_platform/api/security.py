from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from poker_bot_platform.api.rate_limit import RateLimitExceeded


def client_key(request: Request) -> str:
    """Identify the browser client, trusting X-Forwarded-For only from a local proxy."""

    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        try:
            trusted_proxy = ip_address(peer).is_loopback
        except ValueError:
            trusted_proxy = False
        if trusted_proxy:
            return forwarded.split(",", 1)[0].strip() or peer
    return peer


def too_many_attempts(exc: RateLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too many attempts; try again in a few minutes",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


class SameOriginGuard:
    """Reject browser cookie mutations that did not originate from this application."""

    def __init__(self, allowed_origin: str) -> None:
        parsed = urlsplit(allowed_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("allowed_origin must be an absolute HTTP(S) origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("allowed_origin cannot contain a path, query, or fragment")
        self.allowed_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    async def __call__(self, request: Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        supplied = request.headers.get("origin")
        if supplied is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Origin header is required for state-changing requests",
            )
        parsed = urlsplit(supplied)
        candidate = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or candidate != self.allowed_origin
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="cross-origin request rejected",
            )
