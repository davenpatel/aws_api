"""
services/ — Example domain service handlers.

Each service defines its own Router instance with its routes.
The main handler mounts them all under version-prefixed paths.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# services/health.py
# ---------------------------------------------------------------------------

from router import Request, Response, Router

health_router = Router()


@health_router.get("/health")
def health_check(request: Request, context) -> Response:
    return Response.ok({"status": "ok", "service": "lambda-api"})


# ---------------------------------------------------------------------------
# services/users.py
# ---------------------------------------------------------------------------

users_router = Router()


@users_router.get("/users")
def list_users(request: Request, context) -> Response:
    # Replace with real data access (DynamoDB, RDS, etc.)
    page = int(request.query_params.get("page", 1))
    limit = int(request.query_params.get("limit", 20))
    return Response.ok({
        "users": [
            {"id": "u-001", "name": "Alice"},
            {"id": "u-002", "name": "Bob"},
        ],
        "page": page,
        "limit": limit,
    })


@users_router.post("/users")
def create_user(request: Request, context) -> Response:
    body = request.body or {}
    if not isinstance(body, dict) or "name" not in body:
        return Response.bad_request("'name' is required")
    # Persist to your data store here
    new_user = {"id": "u-999", "name": body["name"]}
    return Response.created(new_user)


@users_router.get("/users/{user_id}")
def get_user(request: Request, context) -> Response:
    user_id = request.path_params["user_id"]
    # Fetch from data store
    if user_id == "u-000":
        return Response.not_found(f"User {user_id} not found")
    return Response.ok({"id": user_id, "name": "Alice"})


@users_router.put("/users/{user_id}")
def update_user(request: Request, context) -> Response:
    user_id = request.path_params["user_id"]
    body = request.body or {}
    # Strip any 'id' supplied in the body — the path param is authoritative.
    body.pop("id", None)
    # Update in data store
    return Response.ok({"id": user_id, **body})


@users_router.delete("/users/{user_id}")
def delete_user(request: Request, context) -> Response:
    # Delete from data store
    return Response.no_content()


# ---------------------------------------------------------------------------
# services/orders.py
# ---------------------------------------------------------------------------

orders_router = Router()


@orders_router.get("/users/{user_id}/orders")
def list_orders(request: Request, context) -> Response:
    user_id = request.path_params["user_id"]
    return Response.ok({
        "user_id": user_id,
        "orders": [
            {"id": "ord-001", "total": 49.99, "status": "shipped"},
            {"id": "ord-002", "total": 120.00, "status": "pending"},
        ],
    })


@orders_router.post("/users/{user_id}/orders")
def create_order(request: Request, context) -> Response:
    user_id = request.path_params["user_id"]
    body = request.body or {}
    if "items" not in body:
        return Response.bad_request("'items' is required")
    order = {"id": "ord-999", "user_id": user_id, "items": body["items"], "status": "pending"}
    return Response.created(order)


@orders_router.get("/users/{user_id}/orders/{order_id}")
def get_order(request: Request, context) -> Response:
    user_id = request.path_params["user_id"]
    order_id = request.path_params["order_id"]
    return Response.ok({"id": order_id, "user_id": user_id, "status": "shipped"})


@orders_router.patch("/users/{user_id}/orders/{order_id}")
def update_order_status(request: Request, context) -> Response:
    order_id = request.path_params["order_id"]
    body = request.body or {}
    if "status" not in body:
        return Response.bad_request("'status' is required")
    return Response.ok({"id": order_id, "status": body["status"]})
