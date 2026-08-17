"""Service accounts can neither log in nor be managed as people (F049 T015, pairs with T016 / T017).

Three separate defences are asserted here, because each one alone has a known
hole (design D7 / pits 3, 5, 9, 10):

1. **The login guard** ``UserService._reject_login_if_user_has_no_usable_access``
   — the one function all four in-repo login entries funnel through. It must
   ``raise`` 26012 (not *return* a response) and it must do so **before** the
   ``AdminRole`` short-circuit, otherwise a service account that somebody
   wrongly granted AdminRole would sail through, and the two entries that
   translate a returned response would flatten the rejection into "no menu".
2. **The DAO default** — ``_filter_users_statement`` excludes service accounts
   unless a caller explicitly asks for them, so every one of the eight
   ``/user/list`` consumers is covered by construction (fail-safe direction:
   forgetting the parameter hides the account, it never leaks it).
3. **The management-interface assertion** ``assert_natural_persons`` — the DAO
   default cannot stop a direct POST that names a user id, so the write
   endpoints check the target's type at entry (26022).

覆盖 AC: AC-15 (no login entry yields a session), AC-16 (never in a people
picker, still resolvable by id), AC-20 (people-only user operations refused),
AC-22 (no roles / tenant-admin identity).

Test downgrade (AC-15, recorded in T015): the Java gateway login sync, the SSO
gateway callback and the commercial licence login are out of this repository —
they all terminate in one of the four guarded call sites asserted below, and are
verified by hand on 109 (T075).
"""

from __future__ import annotations

import ast
import importlib
import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from bisheng.common.errcode.open_api import (
    ServiceAccountLoginForbiddenError,
    ServiceAccountOperationForbiddenError,
)
from bisheng.common.errcode.user import UserNoRoleForLoginError
from bisheng.database.constants import AdminRole
from bisheng.user.domain.models.user import (
    USER_TYPE_HUMAN,
    USER_TYPE_SERVICE,
    User,
    UserDao,
)
from bisheng.user.domain.services.user import UserService

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD_NAME = "_reject_login_if_user_has_no_usable_access"

# The four in-repo login entries that funnel through the shared guard (pit 3).
LOGIN_ENTRY_FILES = (
    "bisheng/user/domain/services/user.py",  # local login
    "bisheng/user/api/user.py",  # legacy /user/sso
    "bisheng/sso_sync/domain/services/login_sync_service.py",  # HMAC login-sync
    "bisheng/tenant/domain/services/tenant_service.py",  # tenant switch
)

_USER_MODULE = "bisheng.user.api.user"


def _service_user(user_id: int = 70001, name: str = "ci-bot") -> User:
    return User(
        user_id=user_id,
        user_name=name,
        password="x",
        user_type=USER_TYPE_SERVICE,
        source="service_account",
        external_id=None,
        delete=0,
    )


def _human_user(user_id: int = 70002, name: str = "alice") -> User:
    return User(user_id=user_id, user_name=name, password="x", user_type=USER_TYPE_HUMAN, delete=0)


# ---------------------------------------------------------------------------
# 1. Login guard (AC-15)
# ---------------------------------------------------------------------------


async def test_service_account_login_is_rejected_with_26012():
    """AC-15: the shared guard raises — the four entries cannot turn this into a session."""
    with pytest.raises(ServiceAccountLoginForbiddenError) as excinfo:
        await UserService._reject_login_if_user_has_no_usable_access(_service_user())
    assert excinfo.value.code == 26012
    assert excinfo.value.http_status == 403


async def test_guard_runs_before_admin_role_shortcut():
    """AC-15 / pit 3: even a wrongly granted AdminRole cannot buy a service account a session."""
    with pytest.raises(ServiceAccountLoginForbiddenError):
        await UserService._reject_login_if_user_has_no_usable_access(
            _service_user(), role_ids=[AdminRole], is_department_admin=True
        )


async def test_guard_unchanged_for_natural_persons():
    """The guard's behaviour for people is untouched: admins pass, role-less users are refused."""
    assert (
        await UserService._reject_login_if_user_has_no_usable_access(
            _human_user(), role_ids=[AdminRole], is_department_admin=False
        )
        is None
    )

    with (
        patch("bisheng.user.domain.services.user.DepartmentDao") as dept_dao,
        patch("bisheng.user.domain.services.user.UserGroupDao") as group_dao,
    ):
        dept_dao.aget_user_admin_departments = AsyncMock(return_value=[])
        group_dao.aget_user_admin_group = AsyncMock(return_value=[])
        response = await UserService._reject_login_if_user_has_no_usable_access(
            _human_user(), role_ids=[], is_department_admin=False
        )
    assert response is not None and response.status_code == UserNoRoleForLoginError.Code


def test_four_login_entries_share_the_guard():
    """AC-15: every in-repo login entry goes through the one guarded function."""
    for relative in LOGIN_ENTRY_FILES:
        source = (BACKEND_ROOT / relative).read_text(encoding="utf-8")
        assert GUARD_NAME in source, f"{relative} no longer calls the shared login guard"


def test_no_login_entry_can_swallow_the_service_account_rejection():
    """pit 3: a ``raise`` only survives if no entry wraps the call in a broad ``except``.

    Two of the four entries translate a *returned* guard response into
    ``UserNoWebMenuForLoginError``; a raised 26012 flies past that translation —
    unless somebody later puts the call inside ``try/except Exception``.
    """
    for relative in LOGIN_ENTRY_FILES:
        tree = ast.parse((BACKEND_ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body_source = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if GUARD_NAME not in body_source:
                continue
            for handler in node.handlers:
                caught = handler.type
                names = (
                    {caught.id}
                    if isinstance(caught, ast.Name)
                    else {element.id for element in getattr(caught, "elts", []) if isinstance(element, ast.Name)}
                )
                assert caught is not None, f"{relative}: bare except around the login guard"
                assert not ({"Exception", "BaseException"} & names), (
                    f"{relative}: the login guard is wrapped in except {sorted(names)} — 26012 would be swallowed"
                )


# ---------------------------------------------------------------------------
# 2. DAO exclusion (AC-16)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def user_db(monkeypatch):
    """A ``user`` / ``user_tenant`` aiosqlite database bound into the user DAO module."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    importlib.import_module("bisheng.database.models.tenant")
    importlib.import_module("bisheng.user.domain.models.user")
    tables = [SQLModel.metadata.tables[name] for name in ("user", "user_tenant") if name in SQLModel.metadata.tables]
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables))

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr("bisheng.user.domain.models.user.get_async_db_session", _session)
    yield _session
    await engine.dispose()


@pytest.fixture()
async def seeded_users(user_db):
    """One natural person and one service account, both otherwise ordinary rows."""
    async with user_db() as session:
        human = _human_user()
        service = _service_user()
        # A service account never gets an external_id (pit 5); one is written
        # here on purpose so the second lock is what the assertion measures.
        service.external_id = "EMP-BOT"
        human.external_id = "EMP-1"
        session.add(human)
        session.add(service)
        await session.commit()
    return {"human": human, "service": service}


def test_filter_users_statement_defaults_to_human():
    """AC-16 / D7: the exclusion is the DAO default — forgetting it hides, never leaks."""
    statement = UserDao._filter_users_statement(select(User), [], None)
    default_where = str(statement.compile(compile_kwargs={"literal_binds": True})).split("WHERE", 1)
    assert len(default_where) == 2, "the default statement must carry a WHERE clause"
    assert "user_type" in default_where[1] and "'human'" in default_where[1]

    explicit = UserDao._filter_users_statement(select(User), [], None, user_type=None)
    # No other filter was requested, so opting out leaves no WHERE clause at all.
    assert "WHERE" not in str(explicit.compile(compile_kwargs={"literal_binds": True}))


async def test_afilter_users_excludes_service_accounts(seeded_users):
    """AC-16: the shared base of all eight ``/user/list`` consumers stops showing service accounts."""
    rows = await UserDao.afilter_users([], None, 1, 10)
    assert [row.user_id for row in rows] == [seeded_users["human"].user_id]

    including = await UserDao.afilter_users([], None, 1, 10, user_type=None)
    assert {row.user_id for row in including} == {
        seeded_users["human"].user_id,
        seeded_users["service"].user_id,
    }


async def test_login_candidates_exclude_service(seeded_users):
    """AC-15 second lock: even with an ``external_id``, a service account is not a login candidate."""
    assert await UserDao.aget_login_candidates_by_account("EMP-BOT") == []
    humans = await UserDao.aget_login_candidates_by_account("EMP-1")
    assert [row.user_id for row in humans] == [seeded_users["human"].user_id]


async def test_aget_user_by_ids_still_resolves_service_accounts(seeded_users):
    """AC-16: "displayable, not selectable" — name hydration must keep resolving them (pit 10)."""
    ids = [seeded_users["human"].user_id, seeded_users["service"].user_id]
    rows = await UserDao.aget_user_by_ids(ids)
    assert {row.user_id for row in rows} == set(ids)


# ---------------------------------------------------------------------------
# 3. Management interfaces (AC-20 / AC-22)
# ---------------------------------------------------------------------------


def _patch_targets(module: str, rows: list[User]):
    """Make ``(a)assert_natural_persons`` see ``rows`` as the requested targets."""
    return patch.multiple(
        "bisheng.user.domain.services.user.UserDao",
        aget_user_by_ids=AsyncMock(return_value=rows),
        get_user_by_ids=lambda user_ids: rows,
    )


async def test_assert_natural_persons_rejects_service_account():
    """AC-22: both the sync and the async form refuse as soon as one target is a service account."""
    service, human = _service_user(), _human_user()

    with _patch_targets("sync", [human, service]):
        with pytest.raises(ServiceAccountOperationForbiddenError) as excinfo:
            await UserService.aassert_natural_persons([human.user_id, service.user_id])
        assert excinfo.value.code == 26022
        with pytest.raises(ServiceAccountOperationForbiddenError):
            UserService.assert_natural_persons([human.user_id, service.user_id])

    with _patch_targets("sync", [human]):
        assert await UserService.aassert_natural_persons([human.user_id]) is None
        assert UserService.assert_natural_persons([human.user_id]) is None

    # An empty target list is a no-op, not a lookup.
    assert await UserService.aassert_natural_persons([]) is None


async def test_user_update_rejects_service_account():
    """AC-20: ``/user/update`` (including the bare ``delete`` toggle) refuses service accounts."""
    from bisheng.user.api.user import update

    service = _service_user()
    payload = type("Payload", (), {"user_id": service.user_id, "delete": 1, "avatar": None})()
    with _patch_targets("async", [service]):
        with pytest.raises(ServiceAccountOperationForbiddenError) as excinfo:
            await update(request=None, user=payload, login_user=_LoginUserStub())
    assert excinfo.value.code == 26022


async def test_reset_password_rejects_service_account():
    """AC-20: the admin password reset never reaches a service account row."""
    from bisheng.user.api.user import reset_password

    service = _service_user()
    with _patch_targets("async", [service]):
        with pytest.raises(ServiceAccountOperationForbiddenError):
            await reset_password(user_id=service.user_id, password="x", login_user=_LoginUserStub())


async def test_role_add_rejects_service_account():
    """AC-22: no role can be assigned to a service account — admin roles least of all."""
    from bisheng.user.api.user import user_addrole

    service = _service_user()
    user_role = type("UserRoleCreate", (), {"user_id": service.user_id, "role_id": [AdminRole, 2]})()
    with _patch_targets("async", [service]):
        with pytest.raises(ServiceAccountOperationForbiddenError):
            await user_addrole(request=None, user_role=user_role, login_user=_LoginUserStub())


async def test_grant_tenant_admin_rejects_service_account():
    """AC-22: "a key must never have a super admin behind it" — nor a tenant admin."""
    from bisheng.tenant.domain.services.tenant_admin_service import TenantAdminService

    service = _service_user()
    with _patch_targets("async", [service]):
        with pytest.raises(ServiceAccountOperationForbiddenError):
            await TenantAdminService.grant_tenant_admin(2, service.user_id)


class _LoginUserStub:
    """Enough of ``LoginUser`` for endpoints that reject before touching the caller."""

    user_id = 1

    def is_admin(self) -> bool:
        return True

    def check_groups_admin(self, group_ids) -> bool:
        return True
