"""Optional bearer-token auth for the HTTP surface.

Off by default (local-only 127.0.0.1 bind is the security boundary). When
enabled via config.auth.require_auth or $M3_REQUIRE_AUTH, every /api/v1/*
request must present Authorization: Bearer <key>.

Key generation: `m3 auth generate-key` produces a fresh token and stores it
in config.yml. `m3 auth show-key` prints it.

SPA / static routes are deliberately NOT gated — the bundle itself isn't
sensitive; the data behind /api/v1 is.
"""

from __future__ import annotations

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_500_INTERNAL_SERVER_ERROR

from m3.core import config as _cfg


def generate_key() -> str:
    """Fresh URL-safe token. 32 bytes → ~43 chars."""
    return secrets.token_urlsafe(32)


async def auth_middleware(request: Request, call_next):
    # Non-API routes (SPA, static assets) stay open.
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    if not _cfg.auth_required():
        return await call_next(request)
    key = _cfg.auth_api_key()
    if not key:
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": (
                    "auth required but no key configured; "
                    "run `m3 auth generate-key`"
                )
            },
        )
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return JSONResponse(
            status_code=HTTP_401_UNAUTHORIZED,
            content={"detail": "missing bearer token"},
        )
    presented = header.split(None, 1)[1].strip()
    if not secrets.compare_digest(presented, key):
        return JSONResponse(
            status_code=HTTP_401_UNAUTHORIZED,
            content={"detail": "invalid token"},
        )
    return await call_next(request)
