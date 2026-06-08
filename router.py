"""
router.py - Core routing infrastructure for AWS Lambda API Gateway events.

Supports:
  - Method + path routing with path parameters (e.g. /users/{id})
  - Middleware pipeline (auth, logging, CORS, etc.)
  - Centralized error handling
  - Response helpers
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from dataclasses import dataclass, field
from functools import wraps
from http import HTTPStatus
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Handler = Callable[["Request", "Context"], "Response"]
Middleware = Callable[[Handler], Handler]


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------

@dataclass
class Request:
    """Parsed, enriched representation of an API Gateway v2 (HTTP API) event."""

    method: str
    path: str
    path_params: dict[str, str]
    query_params: dict[str, str]
    headers: dict[str, str]
    body: Any                           # parsed JSON or raw string
    raw_event: dict                     # original Lambda event
    context: dict = field(default_factory=dict)   # shared bag for middleware

    @classmethod
    def from_event(cls, event: dict) -> "Request":
        raw_body = event.get("body") or ""
        content_type = (event.get("headers") or {}).get("content-type", "")
        if raw_body and "application/json" in content_type:
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                body = raw_body
        else:
            body = raw_body

        return cls(
            method=event.get("requestContext", {})
                        .get("http", {})
                        .get("method", event.get("httpMethod", "GET"))
                        .upper(),
            path=event.get("requestContext", {})
                      .get("http", {})
                      .get("path", event.get("path", "/")),
            path_params=event.get("pathParameters") or {},
            query_params=event.get("queryStringParameters") or {},
            headers={k.lower(): v for k, v in (event.get("headers") or {}).items()},
            body=body,
            raw_event=event,
        )


@dataclass
class Response:
    """HTTP response that API Gateway understands."""

    status_code: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    is_base64_encoded: bool = False

    def to_dict(self) -> dict:
        headers = {"Content-Type": "application/json", **self.headers}
        return {
            "statusCode": self.status_code,
            "headers": headers,
            "body": json.dumps(self.body) if self.body is not None else "",
            "isBase64Encoded": self.is_base64_encoded,
        }

    # ------------------------------------------------------------------
    # Convenience factory methods
    # ------------------------------------------------------------------

    @classmethod
    def ok(cls, body: Any = None, **kwargs) -> "Response":
        return cls(status_code=200, body=body, **kwargs)

    @classmethod
    def created(cls, body: Any = None, **kwargs) -> "Response":
        return cls(status_code=201, body=body, **kwargs)

    @classmethod
    def no_content(cls) -> "Response":
        return cls(status_code=204)

    @classmethod
    def bad_request(cls, message: str = "Bad Request") -> "Response":
        return cls(status_code=400, body={"error": message})

    @classmethod
    def unauthorized(cls, message: str = "Unauthorized") -> "Response":
        return cls(status_code=401, body={"error": message})

    @classmethod
    def forbidden(cls, message: str = "Forbidden") -> "Response":
        return cls(status_code=403, body={"error": message})

    @classmethod
    def not_found(cls, message: str = "Not Found") -> "Response":
        return cls(status_code=404, body={"error": message})

    @classmethod
    def method_not_allowed(cls) -> "Response":
        return cls(status_code=405, body={"error": "Method Not Allowed"})

    @classmethod
    def internal_error(cls, message: str = "Internal Server Error") -> "Response":
        return cls(status_code=500, body={"error": message})


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@dataclass
class Route:
    """A compiled route pattern bound to a handler."""

    method: str                    # HTTP verb or "*" for any
    pattern: str                   # original path template, e.g. /users/{id}
    handler: Handler
    _regex: re.Pattern = field(init=False, repr=False)
    _param_names: list[str] = field(init=False, repr=False)

    def __post_init__(self):
        # Convert /users/{id}/orders/{order_id} → named-group regex
        param_re = re.compile(r"\{(\w+)\}")
        self._param_names = param_re.findall(self.pattern)
        regex_pattern = param_re.sub(lambda m: f"(?P<{m.group(1)}>[^/]+)", self.pattern)
        self._regex = re.compile(f"^{regex_pattern}$")

    def match(self, method: str, path: str) -> Optional[dict[str, str]]:
        """Return extracted path params dict if this route matches, else None."""
        # OPTIONS is handled by CORS middleware; match path regardless of stored method
        if self.method not in (method, "*") and method != "OPTIONS":
            return None
        m = self._regex.match(path)
        if m is None:
            return None
        return m.groupdict()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class Router:
    """
    Central router.  Register routes with decorators, then call
    ``router.resolve(event, context)`` from your Lambda handler.
    """

    def __init__(self):
        self._routes: list[Route] = []
        self._middleware: list[Middleware] = []

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    def use(self, middleware: Middleware) -> None:
        """Add a middleware to the pipeline (applied in registration order)."""
        self._middleware.append(middleware)

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _add_route(self, method: str, path: str, handler: Handler) -> None:
        self._routes.append(Route(method=method.upper(), pattern=path, handler=handler))

    def route(self, method: str, path: str):
        """Generic decorator: ``@router.route('GET', '/ping')``."""
        def decorator(fn: Handler) -> Handler:
            self._add_route(method, path, fn)
            return fn
        return decorator

    def get(self, path: str):
        return self.route("GET", path)

    def post(self, path: str):
        return self.route("POST", path)

    def put(self, path: str):
        return self.route("PUT", path)

    def patch(self, path: str):
        return self.route("PATCH", path)

    def delete(self, path: str):
        return self.route("DELETE", path)

    def any(self, path: str):
        return self.route("*", path)

    # ------------------------------------------------------------------
    # Include sub-routers (for service decomposition)
    # ------------------------------------------------------------------

    def include(self, other: "Router", prefix: str = "") -> None:
        """Mount another router's routes under an optional prefix."""
        for route in other._routes:
            new_pattern = prefix.rstrip("/") + route.pattern
            self._add_route(route.method, new_pattern, route.handler)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, event: dict, lambda_context: Any = None) -> dict:
        """
        Entry point called by the Lambda handler function.
        Returns an API Gateway-compatible response dict.
        """
        request = Request.from_event(event)
        logger.info("%s %s", request.method, request.path)

        try:
            for route in self._routes:
                path_params = route.match(request.method, request.path)
                if path_params is not None:
                    request.path_params = path_params
                    handler = self._wrap_middleware(route.handler)
                    response = handler(request, lambda_context)
                    return response.to_dict()

            # Check if path exists with a different method → 405
            path_matched = any(
                Route(method="*", pattern=r.pattern, handler=r.handler)
                    ._regex.match(request.path)
                for r in self._routes
            )
            if path_matched:
                return Response.method_not_allowed().to_dict()

            return Response.not_found(f"No route for {request.method} {request.path}").to_dict()

        except HttpException as exc:
            return Response(status_code=exc.status_code, body={"error": exc.message}).to_dict()
        except Exception:
            logger.error("Unhandled exception:\n%s", traceback.format_exc())
            return Response.internal_error().to_dict()

    def _wrap_middleware(self, handler: Handler) -> Handler:
        """Apply the middleware stack (outermost last → runs first)."""
        wrapped = handler
        for mw in reversed(self._middleware):
            wrapped = mw(wrapped)
        return wrapped


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class HttpException(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
