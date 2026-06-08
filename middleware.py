"""
middleware.py - Ready-to-use middleware for the Lambda router.

Available middleware
--------------------
  cors_middleware         Add CORS headers to every response.
  logging_middleware      Structured request/response logging.
  request_id_middleware   Propagate / generate X-Request-ID.
  jwt_auth_middleware     Validate a Bearer JWT; inject claims into request.context.
  api_key_middleware      Validate a static API key from a header.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import time
import uuid
from typing import Callable, Optional

from router import Handler, HttpException, Request, Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def cors_middleware(
    allow_origins: list[str] | str = "*",
    allow_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    allow_headers: str = "Content-Type,Authorization,X-Request-ID",
    max_age: int = 86400,
) -> Callable[[Handler], Handler]:
    """
    Usage::

        router.use(cors_middleware(allow_origins=["https://myapp.com"]))
    """
    origins = allow_origins if isinstance(allow_origins, str) else ",".join(allow_origins)

    def middleware(handler: Handler) -> Handler:
        def wrapped(request: Request, context) -> Response:
            # Preflight
            if request.method == "OPTIONS":
                return Response(
                    status_code=204,
                    headers={
                        "Access-Control-Allow-Origin": origins,
                        "Access-Control-Allow-Methods": allow_methods,
                        "Access-Control-Allow-Headers": allow_headers,
                        "Access-Control-Max-Age": str(max_age),
                    },
                )
            response = handler(request, context)
            response.headers["Access-Control-Allow-Origin"] = origins
            return response
        return wrapped
    return middleware


# ---------------------------------------------------------------------------
# Request ID
# ---------------------------------------------------------------------------

def request_id_middleware(header: str = "x-request-id") -> Callable[[Handler], Handler]:
    """
    Reads X-Request-ID from the incoming request (or generates one),
    stores it on ``request.context["request_id"]``, and echoes it back
    in the response header.
    """
    def middleware(handler: Handler) -> Handler:
        def wrapped(request: Request, context) -> Response:
            request_id = request.headers.get(header, str(uuid.uuid4()))
            request.context["request_id"] = request_id
            response = handler(request, context)
            response.headers[header] = request_id
            return response
        return wrapped
    return middleware


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

def logging_middleware(handler: Handler) -> Handler:
    """
    Logs method, path, status code, and duration for every request.
    Attach *after* ``request_id_middleware`` to include the request ID.
    """
    def wrapped(request: Request, context) -> Response:
        start = time.perf_counter()
        response = handler(request, context)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            json.dumps({
                "request_id": request.context.get("request_id", "-"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            })
        )
        return response
    return wrapped


# ---------------------------------------------------------------------------
# JWT auth (HS256 / RS256 — lightweight, no third-party deps)
# ---------------------------------------------------------------------------

def jwt_auth_middleware(
    secret: Optional[str] = None,
    *,
    skip_paths: list[str] | None = None,
    header: str = "authorization",
) -> Callable[[Handler], Handler]:
    """
    Validates a Bearer JWT using HMAC-SHA256 (symmetric secret).

    The decoded payload is stored in ``request.context["jwt_claims"]``.

    For RS256 / JWKS validation, replace ``_verify_hs256`` with your own
    implementation or use a library such as PyJWT.

    Parameters
    ----------
    secret:
        HMAC secret.  Falls back to the ``JWT_SECRET`` env var.
    skip_paths:
        List of exact paths that bypass auth (e.g. ``["/health"]``).
    """
    _secret = secret or os.environ.get("JWT_SECRET", "")
    _skip = set(skip_paths or [])

    def middleware(handler: Handler) -> Handler:
        def wrapped(request: Request, context) -> Response:
            if request.path in _skip:
                return handler(request, context)

            auth_header = request.headers.get(header, "")
            if not auth_header.lower().startswith("bearer "):
                raise HttpException(401, "Missing or invalid Authorization header")

            token = auth_header[7:]
            try:
                claims = _verify_hs256(token, _secret)
            except ValueError as exc:
                raise HttpException(401, str(exc)) from exc

            request.context["jwt_claims"] = claims
            return handler(request, context)
        return wrapped
    return middleware


def _b64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding)


def _verify_hs256(token: str, secret: str) -> dict:
    """Minimal HS256 verification — no external dependencies."""
    import hashlib
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT")

    header_b64, payload_b64, signature_b64 = parts

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid JWT signature")

    # Decode payload
    payload = json.loads(_b64url_decode(payload_b64))

    # Check expiry
    exp = payload.get("exp")
    if exp and time.time() > exp:
        raise ValueError("JWT has expired")

    return payload


# ---------------------------------------------------------------------------
# Static API-key auth
# ---------------------------------------------------------------------------

def api_key_middleware(
    valid_keys: list[str] | None = None,
    *,
    header: str = "x-api-key",
    skip_paths: list[str] | None = None,
) -> Callable[[Handler], Handler]:
    """
    Checks that the request carries a known API key in a header.

    Keys can also be supplied via the ``API_KEYS`` env var (comma-separated).
    """
    env_keys = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]
    _valid = set(valid_keys or []) | set(env_keys)
    _skip = set(skip_paths or [])

    def middleware(handler: Handler) -> Handler:
        def wrapped(request: Request, context) -> Response:
            if request.path in _skip:
                return handler(request, context)
            key = request.headers.get(header.lower(), "")
            if key not in _valid:
                raise HttpException(403, "Invalid or missing API key")
            return handler(request, context)
        return wrapped
    return middleware
