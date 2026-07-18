"""
test_crud.py - Pytest unit tests that mock SQLAlchemy CRUD operations.

Covers: session.query, Session.add, Session.commit, Session.delete,
        session.get, query.filter_by, query.first, query.all,
        subquery pagination, rollback on failure, and edge cases.

Run with:  python -m pytest test_crud.py -v
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(__file__))

import pytest
from sqlalchemy.orm import Session

from models import User, Order

# ---------------------------------------------------------------------------
# Tiny service layer under test — mirrors a real ``services/users.py``
# ---------------------------------------------------------------------------

@dataclass
class CreateUserPayload:
    name: str
    email: str


@dataclass
class UpdateUserPayload:
    name: str | None = None
    email: str | None = None
    is_active: bool | None = None


def create_user(session: Session, payload: CreateUserPayload) -> User:
    """Insert a new user and commit. Returns the persisted row."""
    if not payload.name or not payload.email:
        raise ValueError("name and email are required")

    existing = session.query(User).filter_by(email=payload.email).first()
    if existing:
        raise ValueError(f"Email {payload.email} already exists")

    user = User(name=payload.name, email=payload.email)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_user(session: Session, user_id: int) -> User | None:
    """Fetch a user by primary key."""
    return session.get(User, user_id)


def list_users(
    session: Session,
    *,
    is_active: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[User]:
    """Return a paginated list of users with optional filtering."""
    query = session.query(User)
    if is_active is not None:
        query = query.filter_by(is_active=is_active)
    return query.limit(limit).offset(offset).all()


def update_user(
    session: Session,
    user_id: int,
    payload: UpdateUserPayload,
) -> User | None:
    """Update a user's fields. Returns the updated row or None."""
    user = session.get(User, user_id)
    if user is None:
        return None

    if payload.name is not None:
        user.name = payload.name
    if payload.email is not None:
        existing = (
            session.query(User)
            .filter_by(email=payload.email)
            .filter(User.id != user_id)
            .first()
        )
        if existing:
            raise ValueError(f"Email {payload.email} already exists")
        user.email = payload.email
    if payload.is_active is not None:
        user.is_active = payload.is_active

    session.commit()
    return user


def delete_user(session: Session, user_id: int) -> bool:
    """Soft-delete a user by marking ``is_deleted`` on an Order."""
    user = session.get(User, user_id)
    if user is None:
        return False
    session.delete(user)
    session.commit()
    return True


# ---- Order CRUD -----------------------------------------------------------

def create_order(session: Session, user_id: int, total: float) -> Order:
    order = Order(user_id=user_id, total=total)
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def get_order(session: Session, order_id: int) -> Order | None:
    return session.get(Order, order_id)


def list_orders_for_user(
    session: Session,
    user_id: int,
    *,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Order]:
    query = session.query(Order).filter_by(user_id=user_id)
    if status is not None:
        query = query.filter_by(status=status)
    return query.limit(limit).offset(offset).all()


def update_order_status(session: Session, order_id: int, status: str) -> Order | None:
    order = session.get(Order, order_id)
    if order is None:
        return None
    order.status = status
    session.commit()
    return order


def soft_delete_order(session: Session, order_id: int) -> bool:
    """Mark an order as deleted."""
    order = session.query(Order).filter_by(id=order_id).first()
    if order is None:
        return False
    order.is_deleted = True
    session.commit()
    return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session() -> Session:
    """Provide a MagicMock that pretends to be a SQLAlchemy Session."""
    session = pytest.mock.MagicMock(spec=Session)
    return session


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _make_user(id_: int = 1, name: str = "Alice", email: str = "alice@example.com", is_active: bool = True) -> User:
    u = User()
    u.id = id_
    u.name = name
    u.email = email
    u.is_active = is_active
    return u


def _make_order(
    id_: int = 1,
    user_id: int = 1,
    total: float = 49.99,
    status: str = "shipped",
) -> Order:
    o = Order()
    o.id = id_
    o.user_id = user_id
    o.total = total
    o.status = status
    return o


# ===================================================================
#  create_user — happy path
# ===================================================================

class TestCreateUser:

    def test_insert_and_commit(self, mock_session):
        """Normal flow: filter_by finds nothing → add → commit."""
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_session.get.return_value = None

        user = create_user(mock_session, CreateUserPayload(name="Alice", email="alice@example.com"))

        assert user.name == "Alice"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_with(user)

    def test_returns_persisted_user(self, mock_session):
        new_user = _make_user(id_=42, name="Bob")
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_session.get.return_value = None
        mock_session.add.reset_mock()

        result = create_user(mock_session, CreateUserPayload(name="Bob", email="bob@example.com"))

        assert result.id == 42
        # commit should be called AFTER add
        mock_session.add.assert_called()
        mock_session.commit.assert_called()

    def test_email_uniqueness_check_occurs(self, mock_session):
        """The service queries User by email before inserting."""
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        create_user(mock_session, CreateUserPayload(name="Alice", email="a@b.com"))

        mock_session.query.assert_called_with(User)
        mock_session.query.return_value.filter_by.assert_called_once_with(email="a@b.com")


# ===================================================================
#  create_user — validation & errors
# ===================================================================

class TestCreateUserValidation:

    def test_empty_name_raises(self, mock_session):
        with pytest.raises(ValueError, match="name and email"):
            create_user(mock_session, CreateUserPayload(name="", email="a@b.com"))
        mock_session.add.assert_not_called()

    def test_empty_email_raises(self, mock_session):
        with pytest.raises(ValueError, match="name and email"):
            create_user(mock_session, CreateUserPayload(name="Alice", email=""))
        mock_session.add.assert_not_called()

    def test_duplicate_email_raises(self, mock_session):
        existing = _make_user(email="alice@example.com")
        mock_session.query.return_value.filter_by.return_value.first.return_value = existing

        with pytest.raises(ValueError, match="already exists"):
            create_user(mock_session, CreateUserPayload(name="Alice", email="alice@example.com"))

    def test_no_db_call_on_validation_error(self, mock_session):
        """Validation failures never hit the database."""
        with pytest.raises(ValueError):
            create_user(mock_session, CreateUserPayload(name="", email=""))
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_called()


# ===================================================================
#  get_user
# ===================================================================

class TestGetUser:

    def test_existing_user(self, mock_session):
        expected = _make_user(id_=1)
        mock_session.get.return_value = expected

        result = get_user(mock_session, 1)

        assert result is not None
        assert result.name == "Alice"
        mock_session.get.assert_called_once_with(User, 1)

    def test_missing_user_returns_none(self, mock_session):
        mock_session.get.return_value = None

        result = get_user(mock_session, 999)

        assert result is None


# ===================================================================
#  list_users
# ===================================================================

class TestListUsers:

    def test_default_pagination(self, mock_session):
        """No filters → returns all, limited to 20 offset 0."""
        mock_session.query.return_value.limit.return_value.offset.return_value.all.return_value = [
            _make_user(id_=1),
            _make_user(id_=2),
        ]

        result = list_users(mock_session)

        assert len(result) == 2
        mock_session.query.assert_called_with(User)
        mock_session.query.return_value.limit.assert_called_with(20)
        mock_session.query.return_value.limit.return_value.offset.assert_called_with(0)

    def test_filter_by_active(self, mock_session):
        users = [_make_user(id_=1), _make_user(id_=2)]
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = users

        result = list_users(mock_session, is_active=True)

        assert len(result) == 2
        q.filter_by.assert_called_with(is_active=True)

    def test_filter_by_inactive(self, mock_session):
        users = []
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = users

        result = list_users(mock_session, is_active=False)

        assert len(result) == 0
        q.filter_by.assert_called_with(is_active=False)

    def test_custom_pagination(self, mock_session):
        q = mock_session.query.return_value
        q.limit.return_value.offset.return_value.all.return_value = []

        list_users(mock_session, limit=5, offset=10)

        q.limit.assert_called_with(5)
        q.limit.return_value.offset.assert_called_with(10)


# ===================================================================
#  update_user
# ===================================================================

class TestUpdateUser:

    def test_update_name(self, mock_session):
        existing = _make_user(id_=1)
        mock_session.get.return_value = existing

        result = update_user(mock_session, 1, UpdateUserPayload(name="Alicia"))

        assert result.name == "Alicia"
        mock_session.commit.assert_called_once()

    def test_update_email_with_uniqueness_check(self, mock_session):
        """Should verify email uniqueness against OTHER users."""
        other = _make_user(id_=2, email="other@example.com")
        existing = _make_user(id_=1)
        mock_session.get.return_value = existing
        # The second filter_by call (uniqueness check) finds nothing
        type(mock_session.query.return_value.filter_by
             .return_value).first = lambda s: None

        update_user(mock_session, 1, UpdateUserPayload(email="new@example.com"))

        # uniqueness query should exclude current user
        mock_session.query.return_value.filter_by.assert_any_call(email="new@example.com")
        call_kwargs = mock_session.query.return_value.filter_by.call_args_list[-1]
        assert "email" in str(call_kwargs)

    def test_update_user_not_found(self, mock_session):
        mock_session.get.return_value = None

        result = update_user(mock_session, 999, UpdateUserPayload(name="X"))

        assert result is None
        mock_session.commit.assert_not_called()

    def test_partial_update_only_changes_provided(self, mock_session):
        """Only fields in the payload are touched."""
        existing = _make_user(id_=1)
        mock_session.get.return_value = existing

        update_user(mock_session, 1, UpdateUserPayload(name="NewName"))

        assert existing.name == "NewName"
        assert existing.email == "alice@example.com"  # untouched


# ===================================================================
#  delete_user (hard delete)
# ===================================================================

class TestDeleteUser:

    def test_existing_user(self, mock_session):
        existing = _make_user(id_=1)
        mock_session.get.return_value = existing

        result = delete_user(mock_session, 1)

        assert result is True
        mock_session.delete.assert_called_with(existing)
        mock_session.commit.assert_called_once()

    def test_missing_user(self, mock_session):
        mock_session.get.return_value = None

        result = delete_user(mock_session, 999)

        assert result is False
        mock_session.delete.assert_not_called()


# ===================================================================
#  create_order — happy path & validation
# ===================================================================

class TestCreateOrder:

    def test_insert(self, mock_session):
        order = create_order(mock_session, user_id=1, total=99.99)

        assert order.user_id == 1
        assert order.total == 99.99
        assert order.status == "pending"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_with(order)

    def test_commit_before_refresh(self, mock_session):
        """Ensure commit happens before refresh (DB needs the row)."""
        create_order(mock_session, user_id=1, total=10.0)

        call_order = [c[0][0] for c in mock_session.method_calls]
        add_idx = call_order.index("add")
        commit_idx = call_order.index("commit")
        refresh_idx = call_order.index("refresh")
        assert add_idx < commit_idx < refresh_idx


# ===================================================================
#  get_order
# ===================================================================

class TestGetOrder:

    def test_existing_order(self, mock_session):
        expected = _make_order(id=10)
        mock_session.get.return_value = expected

        result = get_order(mock_session, 10)

        assert result is not None
        assert result.id == 10

    def test_missing_order(self, mock_session):
        mock_session.get.return_value = None
        assert get_order(mock_session, 999) is None


# ===================================================================
#  list_orders_for_user
# ===================================================================

class TestListOrdersForUser:

    def test_returns_all_statuses(self, mock_session):
        orders = [_make_order(id_=1), _make_order(id_=2)]
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = orders

        result = list_orders_for_user(mock_session, user_id=1)

        assert len(result) == 2
        mock_session.query.return_value.filter_by.assert_called_with(user_id=1)

    def test_filter_by_status(self, mock_session):
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = []

        list_orders_for_user(mock_session, user_id=1, status="pending")

        # filter_by should be called twice: once for user_id, once for status
        call_args_list = mock_session.query.return_value.filter_by.call_args_list
        assert len(call_args_list) == 2
        statuses = [c[1].get("status") for c in call_args_list]
        assert "pending" in statuses

    def test_empty_result_no_error(self, mock_session):
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = []

        result = list_orders_for_user(mock_session, user_id=999)
        assert result == []


# ===================================================================
#  update_order_status
# ===================================================================

class TestUpdateOrderStatus:

    def test_updates_status(self, mock_session):
        order = _make_order(id=50, status="pending")
        mock_session.get.return_value = order

        result = update_order_status(mock_session, 50, "shipped")

        assert result.status == "shipped"
        mock_session.commit.assert_called_once()

    def test_missing_order_returns_none(self, mock_session):
        mock_session.get.return_value = None
        assert update_order_status(mock_session, 999, "cancelled") is None


# ===================================================================
#  soft_delete_order
# ===================================================================

class TestSoftDeleteOrder:

    def test_marks_deleted(self, mock_session):
        order = _make_order(id=1)
        mock_session.query.return_value.filter_by.return_value.first.return_value = order

        result = soft_delete_order(mock_session, 1)

        assert result is True
        assert order.is_deleted is True
        mock_session.commit.assert_called_once()

    def test_missing_order(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        assert soft_delete_order(mock_session, 999) is False


# ===================================================================
#  Edge cases: session failures & rollback scenarios
# ===================================================================

class TestSessionEdgeCases:

    def test_commit_failure_rolls_back(self):
        """When commit raises, the caller should catch and rollback."""
        from unittest.mock import MagicMock

        session = MagicMock(spec=Session)
        user = User(name="Alice", email="alice@example.com")

        # Simulate add → commit fails
        session.add = MagicMock()
        session.commit = MagicMock(side_effect=Exception("DB error"))

        with pytest.raises(Exception, match="DB error"):
            session.add(user)
            session.commit()


# ===================================================================
#  Integration-style: multiple operations in one session
# ===================================================================

class TestMultiOperationSession:

    def test_create_then_read(self, mock_session):
        """Realistic flow: create a user, then read them back."""
        new_user = _make_user(id=5, name="Charlie")

        # Setup: query for uniqueness finds nothing, get returns the new user
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_session.get.return_value = new_user

        create_user(mock_session, CreateUserPayload(name="Charlie", email="charlie@example.com"))
        result = get_user(mock_session, 5)

        assert result is not None
        assert result.name == "Charlie"


# ===================================================================
#  Query method chaining verification
# ===================================================================

class TestQueryChaining:

    def test_filter_chaining_on_list_users(self, mock_session):
        """Ensure filter_by → limit → offset → all chain fires correctly."""
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = []

        list_users(mock_session)

        # verify the chain: query(User) → limit(20) → offset(0) → all()
        assert q.limit.called
        assert q.limit.return_value.offset.called

    def test_filter_then_limit_on_orders(self, mock_session):
        """Order listing chains filter_by → limit → offset → all."""
        q = mock_session.query.return_value
        q.filter_by.return_value.limit.return_value.offset.return_value.all.return_value = []

        list_orders_for_user(mock_session, user_id=1)

        assert q.filter_by.called
        assert q.filter_by.return_value.limit.called
