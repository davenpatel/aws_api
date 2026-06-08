"""
tests.py - Unit tests (no AWS account required).

Run with:  python -m pytest tests.py -v
"""

import json
import sys
import os
import unittest

# Make the package importable from this directory
sys.path.insert(0, os.path.dirname(__file__))

from router import Request, Response, Router, HttpException
from middleware import cors_middleware, logging_middleware, request_id_middleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(method: str, path: str, body=None, headers=None, query=None) -> dict:
    """Build a minimal API Gateway v2 event."""
    return {
        "requestContext": {
            "http": {"method": method, "path": path}
        },
        "headers": {
            "content-type": "application/json",
            **(headers or {}),
        },
        "queryStringParameters": query or {},
        "body": json.dumps(body) if body else None,
    }


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

class TestRouter(unittest.TestCase):

    def setUp(self):
        self.router = Router()

        @self.router.get("/ping")
        def ping(req, ctx):
            return Response.ok({"pong": True})

        @self.router.get("/users/{user_id}")
        def get_user(req, ctx):
            return Response.ok({"id": req.path_params["user_id"]})

        @self.router.post("/users")
        def create_user(req, ctx):
            return Response.created({"name": req.body.get("name")})

    def test_simple_get(self):
        result = self.router.resolve(make_event("GET", "/ping"))
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertTrue(body["pong"])

    def test_path_parameter(self):
        result = self.router.resolve(make_event("GET", "/users/abc-123"))
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["id"], "abc-123")

    def test_post_with_body(self):
        result = self.router.resolve(make_event("POST", "/users", body={"name": "Alice"}))
        self.assertEqual(result["statusCode"], 201)
        self.assertEqual(json.loads(result["body"])["name"], "Alice")

    def test_not_found(self):
        result = self.router.resolve(make_event("GET", "/nonexistent"))
        self.assertEqual(result["statusCode"], 404)

    def test_method_not_allowed(self):
        result = self.router.resolve(make_event("DELETE", "/ping"))
        self.assertEqual(result["statusCode"], 405)

    def test_http_exception_propagation(self):
        router = Router()

        @router.get("/secret")
        def secret(req, ctx):
            raise HttpException(403, "Forbidden zone")

        result = router.resolve(make_event("GET", "/secret"))
        self.assertEqual(result["statusCode"], 403)

    def test_unhandled_exception_returns_500(self):
        router = Router()

        @router.get("/boom")
        def boom(req, ctx):
            raise RuntimeError("unexpected!")

        result = router.resolve(make_event("GET", "/boom"))
        self.assertEqual(result["statusCode"], 500)

    def test_include_prefix(self):
        sub = Router()

        @sub.get("/items")
        def items(req, ctx):
            return Response.ok({"items": []})

        self.router.include(sub, "/api/v1")
        result = self.router.resolve(make_event("GET", "/api/v1/items"))
        self.assertEqual(result["statusCode"], 200)


# ---------------------------------------------------------------------------
# Middleware tests
# ---------------------------------------------------------------------------

class TestMiddleware(unittest.TestCase):

    def _make_router(self, *middlewares):
        router = Router()
        for mw in middlewares:
            router.use(mw)

        @router.get("/test")
        def handler(req, ctx):
            return Response.ok({"ok": True})

        return router

    def test_cors_headers(self):
        router = self._make_router(cors_middleware(allow_origins="*"))
        result = router.resolve(make_event("GET", "/test"))
        self.assertEqual(result["headers"]["Access-Control-Allow-Origin"], "*")

    def test_cors_preflight(self):
        router = self._make_router(cors_middleware())
        result = router.resolve(make_event("OPTIONS", "/test"))
        self.assertEqual(result["statusCode"], 204)

    def test_request_id_generated(self):
        router = self._make_router(request_id_middleware())
        result = router.resolve(make_event("GET", "/test"))
        self.assertIn("x-request-id", result["headers"])

    def test_request_id_propagated(self):
        router = self._make_router(request_id_middleware())
        event = make_event("GET", "/test", headers={"x-request-id": "my-id-123"})
        result = router.resolve(event)
        self.assertEqual(result["headers"]["x-request-id"], "my-id-123")

    def test_logging_middleware(self):
        """Logging middleware should not alter status code."""
        router = self._make_router(logging_middleware)
        result = router.resolve(make_event("GET", "/test"))
        self.assertEqual(result["statusCode"], 200)


# ---------------------------------------------------------------------------
# Response factory tests
# ---------------------------------------------------------------------------

class TestResponse(unittest.TestCase):

    def test_ok(self):
        r = Response.ok({"key": "value"})
        self.assertEqual(r.status_code, 200)

    def test_created(self):
        r = Response.created({"id": 1})
        self.assertEqual(r.status_code, 201)

    def test_no_content(self):
        r = Response.no_content()
        d = r.to_dict()
        self.assertEqual(d["statusCode"], 204)
        self.assertEqual(d["body"], "")

    def test_bad_request(self):
        r = Response.bad_request("oops")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.body["error"], "oops")

    def test_to_dict_serializes_body(self):
        r = Response.ok({"hello": "world"})
        d = r.to_dict()
        self.assertEqual(json.loads(d["body"]), {"hello": "world"})


if __name__ == "__main__":
    unittest.main()
