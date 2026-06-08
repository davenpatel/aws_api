"""
handler.py - AWS Lambda entry point.

Wires together the router, middleware, and all service sub-routers.
Deploy this file as your Lambda handler and set the handler to:

    handler.lambda_handler
"""

from middleware import (
    api_key_middleware,
    cors_middleware,
    jwt_auth_middleware,
    logging_middleware,
    request_id_middleware,
)
from router import Router
from services import health_router, orders_router, users_router

# ---------------------------------------------------------------------------
# Build the root router
# ---------------------------------------------------------------------------

app = Router()

# ---------------------------------------------------------------------------
# Middleware (applied in order: first registered = outermost = runs first)
# ---------------------------------------------------------------------------

app.use(request_id_middleware())          # 1. stamp every request with an ID
app.use(logging_middleware)               # 2. structured request/response log
app.use(cors_middleware(                  # 3. CORS headers
    allow_origins=["https://myapp.com", "http://localhost:3000"]
))
# Choose ONE of the auth middlewares below (or layer both for defence-in-depth):

# Option A — JWT Bearer token
app.use(jwt_auth_middleware(skip_paths=["/health"]))

# Option B — static API key  (uncomment to use instead / in addition)
# app.use(api_key_middleware(skip_paths=["/health"]))

# ---------------------------------------------------------------------------
# Mount service routers under a versioned prefix
# ---------------------------------------------------------------------------

API_PREFIX = "/api/v1"

app.include(health_router)               # GET /health  (no prefix — public)
app.include(users_router,  API_PREFIX)   # GET/POST /api/v1/users, etc.
app.include(orders_router, API_PREFIX)   # GET/POST /api/v1/users/{id}/orders, etc.

# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    """
    AWS Lambda entry point.

    Supports both:
      - API Gateway REST API (v1 payload format)
      - API Gateway HTTP API (v2 payload format)
    """
    return app.resolve(event, context)
