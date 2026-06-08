"""
test_services.py - Tests for the users and orders service handlers.

Covers every route, including happy paths, validation errors,
edge cases, and response shape assertions.

Run with:  python -m pytest test_services.py -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from services import orders_router, users_router


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_event(method: str, path: str, body=None, query=None) -> dict:
    """Build a minimal API Gateway v2 event."""
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"content-type": "application/json"},
        "queryStringParameters": query or {},
        "body": json.dumps(body) if body is not None else None,
    }


def body_of(result: dict) -> dict:
    """Deserialise the response body JSON."""
    return json.loads(result["body"])


# ===========================================================================
# Users service
# ===========================================================================

class TestListUsers(unittest.TestCase):

    def _call(self, query=None):
        return users_router.resolve(make_event("GET", "/users", query=query))

    # --- status & shape ---

    def test_returns_200(self):
        self.assertEqual(self._call()["statusCode"], 200)

    def test_body_contains_users_list(self):
        data = body_of(self._call())
        self.assertIn("users", data)
        self.assertIsInstance(data["users"], list)

    def test_body_contains_pagination_fields(self):
        data = body_of(self._call())
        self.assertIn("page", data)
        self.assertIn("limit", data)

    # --- pagination ---

    def test_default_page_is_1(self):
        self.assertEqual(body_of(self._call())["page"], 1)

    def test_default_limit_is_20(self):
        self.assertEqual(body_of(self._call())["limit"], 20)

    def test_custom_page_param(self):
        self.assertEqual(body_of(self._call(query={"page": "3"}))["page"], 3)

    def test_custom_limit_param(self):
        self.assertEqual(body_of(self._call(query={"limit": "5"}))["limit"], 5)

    def test_page_and_limit_together(self):
        data = body_of(self._call(query={"page": "2", "limit": "10"}))
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["limit"], 10)

    # --- user objects ---

    def test_each_user_has_id_and_name(self):
        for user in body_of(self._call())["users"]:
            self.assertIn("id", user)
            self.assertIn("name", user)


class TestCreateUser(unittest.TestCase):

    def _call(self, body):
        return users_router.resolve(make_event("POST", "/users", body=body))

    # --- happy path ---

    def test_returns_201(self):
        self.assertEqual(self._call({"name": "Alice"})["statusCode"], 201)

    def test_response_contains_id(self):
        self.assertIn("id", body_of(self._call({"name": "Alice"})))

    def test_response_echoes_name(self):
        self.assertEqual(body_of(self._call({"name": "Carol"}))["name"], "Carol")

    def test_extra_fields_in_body_do_not_break(self):
        result = self._call({"name": "Dave", "email": "dave@example.com"})
        self.assertEqual(result["statusCode"], 201)

    # --- validation ---

    def test_missing_name_returns_400(self):
        self.assertEqual(self._call({})["statusCode"], 400)

    def test_missing_name_error_message(self):
        self.assertIn("name", body_of(self._call({}))["error"])

    def test_null_body_returns_400(self):
        result = users_router.resolve(make_event("POST", "/users", body=None))
        self.assertEqual(result["statusCode"], 400)

    def test_name_as_non_string_still_accepted(self):
        # The handler only checks key presence, not type — document that behaviour.
        result = self._call({"name": 42})
        self.assertEqual(result["statusCode"], 201)


class TestGetUser(unittest.TestCase):

    def _call(self, user_id: str):
        return users_router.resolve(make_event("GET", f"/users/{user_id}"))

    # --- happy path ---

    def test_returns_200_for_valid_id(self):
        self.assertEqual(self._call("u-001")["statusCode"], 200)

    def test_response_id_matches_path_param(self):
        self.assertEqual(body_of(self._call("u-abc"))["id"], "u-abc")

    def test_response_contains_name(self):
        self.assertIn("name", body_of(self._call("u-001")))

    # --- not-found sentinel ---

    def test_sentinel_id_returns_404(self):
        self.assertEqual(self._call("u-000")["statusCode"], 404)

    def test_404_error_message_contains_id(self):
        self.assertIn("u-000", body_of(self._call("u-000"))["error"])

    # --- path param edge cases ---

    def test_numeric_id(self):
        self.assertEqual(self._call("12345")["statusCode"], 200)

    def test_hyphenated_id(self):
        self.assertEqual(self._call("user-x-99")["statusCode"], 200)


class TestUpdateUser(unittest.TestCase):

    def _call(self, user_id: str, body: dict):
        return users_router.resolve(make_event("PUT", f"/users/{user_id}", body=body))

    # --- happy path ---

    def test_returns_200(self):
        self.assertEqual(self._call("u-001", {"name": "Updated"})["statusCode"], 200)

    def test_response_id_matches_path(self):
        self.assertEqual(body_of(self._call("u-001", {"name": "X"}))["id"], "u-001")

    def test_updated_fields_reflected_in_response(self):
        data = body_of(self._call("u-007", {"name": "NewName", "role": "admin"}))
        self.assertEqual(data["name"], "NewName")
        self.assertEqual(data["role"], "admin")

    def test_empty_body_still_returns_200(self):
        # Handler merges body with id; empty body is valid
        result = self._call("u-001", {})
        self.assertEqual(result["statusCode"], 200)

    def test_path_id_not_overridden_by_body(self):
        # Even if body contains an 'id', the path param governs
        data = body_of(self._call("u-001", {"id": "u-WRONG"}))
        self.assertEqual(data["id"], "u-001")


class TestDeleteUser(unittest.TestCase):

    def _call(self, user_id: str):
        return users_router.resolve(make_event("DELETE", f"/users/{user_id}"))

    def test_returns_204(self):
        self.assertEqual(self._call("u-001")["statusCode"], 204)

    def test_body_is_empty(self):
        self.assertEqual(self._call("u-001")["body"], "")

    def test_different_ids_all_return_204(self):
        for uid in ("u-001", "u-999", "nonexistent-id"):
            with self.subTest(uid=uid):
                self.assertEqual(self._call(uid)["statusCode"], 204)


class TestUsersRouterMethodRouting(unittest.TestCase):
    """Verify that wrong HTTP methods return 405, not 404."""

    def test_patch_users_collection_is_405(self):
        result = users_router.resolve(make_event("PATCH", "/users"))
        self.assertEqual(result["statusCode"], 405)

    def test_delete_users_collection_is_405(self):
        result = users_router.resolve(make_event("DELETE", "/users"))
        self.assertEqual(result["statusCode"], 405)

    def test_post_to_user_detail_is_405(self):
        result = users_router.resolve(make_event("POST", "/users/u-001"))
        self.assertEqual(result["statusCode"], 405)


# ===========================================================================
# Orders service
# ===========================================================================

class TestListOrders(unittest.TestCase):

    def _call(self, user_id: str):
        return orders_router.resolve(make_event("GET", f"/users/{user_id}/orders"))

    # --- status & shape ---

    def test_returns_200(self):
        self.assertEqual(self._call("u-001")["statusCode"], 200)

    def test_body_contains_orders_list(self):
        data = body_of(self._call("u-001"))
        self.assertIn("orders", data)
        self.assertIsInstance(data["orders"], list)

    def test_body_contains_user_id(self):
        self.assertEqual(body_of(self._call("u-007"))["user_id"], "u-007")

    def test_user_id_reflected_from_path(self):
        for uid in ("u-001", "u-XYZ", "99"):
            with self.subTest(uid=uid):
                self.assertEqual(body_of(self._call(uid))["user_id"], uid)

    # --- order objects ---

    def test_each_order_has_id_total_status(self):
        for order in body_of(self._call("u-001"))["orders"]:
            self.assertIn("id", order)
            self.assertIn("total", order)
            self.assertIn("status", order)

    def test_order_total_is_numeric(self):
        for order in body_of(self._call("u-001"))["orders"]:
            self.assertIsInstance(order["total"], (int, float))


class TestCreateOrder(unittest.TestCase):

    def _call(self, user_id: str, body):
        return orders_router.resolve(
            make_event("POST", f"/users/{user_id}/orders", body=body)
        )

    # --- happy path ---

    def test_returns_201(self):
        result = self._call("u-001", {"items": [{"sku": "A1", "qty": 2}]})
        self.assertEqual(result["statusCode"], 201)

    def test_response_contains_order_id(self):
        data = body_of(self._call("u-001", {"items": []}))
        self.assertIn("id", data)

    def test_response_user_id_matches_path(self):
        data = body_of(self._call("u-042", {"items": []}))
        self.assertEqual(data["user_id"], "u-042")

    def test_response_echoes_items(self):
        items = [{"sku": "B2", "qty": 1}]
        data = body_of(self._call("u-001", {"items": items}))
        self.assertEqual(data["items"], items)

    def test_new_order_status_is_pending(self):
        data = body_of(self._call("u-001", {"items": []}))
        self.assertEqual(data["status"], "pending")

    def test_empty_items_list_is_accepted(self):
        result = self._call("u-001", {"items": []})
        self.assertEqual(result["statusCode"], 201)

    # --- validation ---

    def test_missing_items_returns_400(self):
        self.assertEqual(self._call("u-001", {})["statusCode"], 400)

    def test_missing_items_error_message(self):
        self.assertIn("items", body_of(self._call("u-001", {}))["error"])

    def test_null_body_returns_400(self):
        result = orders_router.resolve(
            make_event("POST", "/users/u-001/orders", body=None)
        )
        self.assertEqual(result["statusCode"], 400)


class TestGetOrder(unittest.TestCase):

    def _call(self, user_id: str, order_id: str):
        return orders_router.resolve(
            make_event("GET", f"/users/{user_id}/orders/{order_id}")
        )

    # --- happy path ---

    def test_returns_200(self):
        self.assertEqual(self._call("u-001", "ord-001")["statusCode"], 200)

    def test_order_id_matches_path(self):
        self.assertEqual(body_of(self._call("u-001", "ord-XYZ"))["id"], "ord-XYZ")

    def test_user_id_matches_path(self):
        self.assertEqual(body_of(self._call("u-999", "ord-001"))["user_id"], "u-999")

    def test_response_contains_status(self):
        self.assertIn("status", body_of(self._call("u-001", "ord-001")))

    # --- path param combinations ---

    def test_various_id_formats(self):
        combos = [
            ("user-a", "order-1"),
            ("1234", "5678"),
            ("u-abc-def", "ord-xyz-99"),
        ]
        for uid, oid in combos:
            with self.subTest(uid=uid, oid=oid):
                result = self._call(uid, oid)
                self.assertEqual(result["statusCode"], 200)
                data = body_of(result)
                self.assertEqual(data["id"], oid)
                self.assertEqual(data["user_id"], uid)


class TestUpdateOrderStatus(unittest.TestCase):

    def _call(self, user_id: str, order_id: str, body):
        return orders_router.resolve(
            make_event("PATCH", f"/users/{user_id}/orders/{order_id}", body=body)
        )

    # --- happy path ---

    def test_returns_200(self):
        result = self._call("u-001", "ord-001", {"status": "shipped"})
        self.assertEqual(result["statusCode"], 200)

    def test_response_order_id_matches_path(self):
        data = body_of(self._call("u-001", "ord-XYZ", {"status": "cancelled"}))
        self.assertEqual(data["id"], "ord-XYZ")

    def test_response_status_reflects_update(self):
        for new_status in ("shipped", "cancelled", "delivered", "refunded"):
            with self.subTest(status=new_status):
                data = body_of(self._call("u-001", "ord-001", {"status": new_status}))
                self.assertEqual(data["status"], new_status)

    # --- validation ---

    def test_missing_status_returns_400(self):
        result = self._call("u-001", "ord-001", {})
        self.assertEqual(result["statusCode"], 400)

    def test_missing_status_error_message(self):
        data = body_of(self._call("u-001", "ord-001", {}))
        self.assertIn("status", data["error"])

    def test_null_body_returns_400(self):
        result = orders_router.resolve(
            make_event("PATCH", "/users/u-001/orders/ord-001", body=None)
        )
        self.assertEqual(result["statusCode"], 400)

    def test_extra_fields_do_not_cause_error(self):
        result = self._call("u-001", "ord-001", {"status": "shipped", "note": "fast"})
        self.assertEqual(result["statusCode"], 200)


class TestOrdersRouterMethodRouting(unittest.TestCase):
    """Verify that unsupported methods on orders routes return 405."""

    def test_put_order_is_405(self):
        result = orders_router.resolve(
            make_event("PUT", "/users/u-001/orders/ord-001")
        )
        self.assertEqual(result["statusCode"], 405)

    def test_delete_order_is_405(self):
        result = orders_router.resolve(
            make_event("DELETE", "/users/u-001/orders/ord-001")
        )
        self.assertEqual(result["statusCode"], 405)

    def test_patch_orders_collection_is_405(self):
        result = orders_router.resolve(
            make_event("PATCH", "/users/u-001/orders")
        )
        self.assertEqual(result["statusCode"], 405)

    def test_delete_orders_collection_is_405(self):
        result = orders_router.resolve(
            make_event("DELETE", "/users/u-001/orders")
        )
        self.assertEqual(result["statusCode"], 405)


if __name__ == "__main__":
    unittest.main()
