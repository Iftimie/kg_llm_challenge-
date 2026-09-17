"""In-memory sliding-window rate limiting (single process).

No external dependencies and no persistence: counters reset on restart. This is
sufficient for a single-instance deployment. A multi-instance deployment would
need a shared store (e.g. Redis) with the same keying scheme.

``limit <= 0`` disables limiting (always allow) so the offline test suite can
turn the guard off by monkeypatching ``config.RATE_LIMIT_*``.
"""
from __future__ import annotations

import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import config


class RateLimiter:
    """Thread-safe sliding-window limiter keyed by an arbitrary string."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        """Return True and record a hit, or False when ``key`` is over ``limit``."""
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, [])
            while hits and now - hits[0] >= window_s:
                hits.pop(0)
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


# Separate buckets: chat is scoped per authenticated user, auth per client IP.
chat_limiter = RateLimiter()
auth_limiter = RateLimiter()

_AUTH_PATHS = {"/api/auth/register", "/api/auth/login"}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _chat_key(request: Request) -> str:
    """Key chat requests by user id (from the bearer token) or IP as fallback."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        from app.auth.security import decode_token  # local import to avoid cycles

        try:
            payload = decode_token(auth[len("Bearer ") :].strip())
            return f"user:{payload.get('sub', '')}"
        except ValueError:
            pass
    return f"ip:{_client_ip(request)}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply per-user chat limits and per-IP auth limits; 429 on exceed."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path == "/api/chat":
            if not chat_limiter.allow(
                _chat_key(request), config.RATE_LIMIT_CHAT_PER_MIN
            ):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={"Retry-After": "60"},
                )
        elif path in _AUTH_PATHS:
            if not auth_limiter.allow(
                f"ip:{_client_ip(request)}", config.RATE_LIMIT_AUTH_PER_MIN
            ):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)
