"""F003 T007: organisation and user candidates of the audit tabs (design §6.1)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.session import MessageSession
from bisheng.user.domain.models.user import User
from test.fixtures.table_definitions import TABLE_DEFINITIONS

# (id, name, parent_id, path, status, tenant_id, is_tenant_root, external_id, mounted_tenant_id)
# MountCo keeps the parent tree's tenant_id; the child tenant is mounted_tenant_id.
_DEPTS = [
    (1, "Root", None, "/1/", "active", 1, 1, None, None),
    (2, "Sales", 1, "/1/2/", "active", 1, 0, None, None),
    (3, "East", 2, "/1/2/3/", "active", 1, 0, "E-110", None),
    (4, "OldTeam", 2, "/1/2/4/", "archived", 1, 0, None, None),
    (20, "R&D", 1, "/1/20/", "active", 1, 0, None, None),
    (50, "ChildCo", 1, "/1/50/", "active", 5, 1, None, None),
    (51, "ChildOps", 50, "/1/50/51/", "active", 5, 0, None, None),
    (70, "MountCo", 1, "/1/70/", "active", 1, 1, None, 9),
    (71, "MountOps", 70, "/1/70/71/", "active", 1, 0, None, None),
    # Stored on the parent tree, with no mount flag. The child tenant points
    # at 80 through tenant.root_dept_id.
    (80, "LocalRoot", 1, "/1/80/", "active", 1, 0, None, None),
    (81, "LocalTeam", 80, "/1/80/81/", "active", 1, 0, None, None),
]


@pytest.fixture()
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text(TABLE_DEFINITIONS["tenant"]))
        await conn.execute(text(TABLE_DEFINITIONS["department"]))
        await conn.execute(
            text(
                "INSERT INTO tenant (id, tenant_code, tenant_name, root_dept_id, status) "
                "VALUES (11, 'local-11', 'LocalTenant', 80, 'active')"
            )
        )
        await conn.run_sync(lambda sync: MessageSession.__table__.create(sync))
        await conn.run_sync(lambda sync: User.__table__.create(sync))
        for dept_id, name, parent_id, path, status, tenant_id, is_root, external_id, mounted_tenant_id in _DEPTS:
            await conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, parent_id, path, status, tenant_id, "
                    "is_tenant_root, external_id, mounted_tenant_id) "
                    "VALUES (:i, :c, :n, :p, :path, :s, :t, :r, :e, :m)"
                ),
                {
                    "i": dept_id,
                    "c": f"BS@{dept_id}",
                    "n": name,
                    "p": parent_id,
                    "path": path,
                    "s": status,
                    "t": tenant_id,
                    "r": is_root,
                    "e": external_id,
                    "m": mounted_tenant_id,
                },
            )
        for user_id, name, dept_id in [(31, "alice", 2), (32, "bob", 3), (34, "carol", 20)]:
            await conn.execute(insert(User.__table__).values(user_id=user_id, user_name=name, password="x"))
            await conn.execute(
                insert(MessageSession.__table__).values(
                    chat_id=f"chat-{user_id}",
                    flow_id="f",
                    flow_type=15,
                    flow_name="n",
                    user_id=user_id,
                    tenant_id=1,
                    operator_dept_id=dept_id,
                )
            )

    @asynccontextmanager
    async def _session():
        async with AsyncSession(engine) as one:
            yield one

    monkeypatch.setattr("bisheng.department.domain.repositories.audit_dept_repository.get_async_db_session", _session)
    monkeypatch.setattr(
        "bisheng.chat_session.domain.repositories.audit_session_repository.get_async_db_session", _session
    )
    yield
    await engine.dispose()


def _user(*, admin=False, global_super=False):
    user = MagicMock()
    user.user_id = 900
    user.is_admin.return_value = admin
    user.is_global_super = global_super
    return user


async def _departments(user, *, tenant=1, admin_scope=None, **kwargs):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=admin_scope),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=tenant),
    ):
        return await AuditLogService.get_audit_departments(
            user,
            parent_id=kwargs.get("parent_id"),
            keyword=kwargs.get("keyword"),
            tenant_id=kwargs.get("tenant_id"),
            limit=50,
        )


def _ids(nodes):
    return [node["id"] for node in nodes]


class TestTopLevel:
    async def test_tenant_admin_sees_tenant_root_and_fixed_items(self, db):
        data = await _departments(_user(admin=True))
        assert _ids(data["active"]) == [1]
        assert data["active"][0]["has_children"] is True
        assert _ids(data["archived"]) == [4]
        assert data["archived"][0]["path_name"] == "Root/Sales/OldTeam"
        assert (data["show_none"], data["show_unrecorded"]) == (True, True)

    async def test_global_super_gets_every_tenant_root(self, db):
        data = await _departments(_user(admin=True, global_super=True))
        assert [(node["id"], node["tenant_id"]) for node in data["active"]] == [(1, 1), (70, 1), (50, 5)]

    async def test_rbac_super_tenant_admin_hides_unrecorded(self, db, monkeypatch):
        async def _tenant_admin(user_id, tenant_id):
            return tenant_id == 9

        monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", _tenant_admin)
        data = await _departments(_user(admin=True, global_super=True), tenant=9, admin_scope=9)
        assert _ids(data["active"]) == [70]
        assert (data["show_none"], data["show_unrecorded"]) == (False, False)

    async def test_tenant_admin_sees_root_dept_subtree_without_mount_flag(self, db, monkeypatch):
        async def _tenant_admin(user_id, tenant_id):
            return tenant_id == 11

        monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", _tenant_admin)
        data = await _departments(_user(admin=True, global_super=True), tenant=11, admin_scope=11)
        assert _ids(data["active"]) == [80]
        assert data["active"][0]["has_children"] is True
        assert (data["show_none"], data["show_unrecorded"]) == (False, False)
        children = await _departments(_user(admin=True, global_super=True), tenant=11, admin_scope=11, parent_id=80)
        assert _ids(children["active"]) == [81]

    async def test_child_tenant_admin_sees_the_mounted_department(self, db, monkeypatch):
        async def _tenant_admin(user_id, tenant_id):
            return tenant_id == 9

        monkeypatch.setattr("bisheng.common.permission_identity.check_tenant_admin", _tenant_admin)
        data = await _departments(_user(), tenant=9)
        assert _ids(data["active"]) == [70]
        assert (data["show_none"], data["show_unrecorded"]) == (False, False)
        children = await _departments(_user(), tenant=9, parent_id=70)
        assert _ids(children["active"]) == [71]

    async def test_rbac_admin_sees_the_mounted_department(self, db):
        data = await _departments(_user(admin=True), tenant=9)
        assert _ids(data["active"]) == [70]
        assert data["active"][0]["has_children"] is True
        children = await _departments(_user(admin=True), tenant=9, parent_id=70)
        assert _ids(children["active"]) == [71]
        found = await _departments(_user(admin=True), tenant=9, keyword="MountOps")
        assert _ids(found["active"]) == [71]

    async def test_global_super_narrowed_by_tenant_id(self, db):
        data = await _departments(_user(admin=True, global_super=True), tenant_id=5)
        assert _ids(data["active"]) == [50]

    async def test_department_admin_sees_managed_roots_only(self, db, audit_identity):
        audit_identity.menu = True
        audit_identity.admin_departments = [SimpleNamespace(path="/1/2/", tenant_id=1, is_deleted=0)]
        data = await _departments(_user())
        assert _ids(data["active"]) == [2]
        assert _ids(data["archived"]) == [4]
        assert (data["show_none"], data["show_unrecorded"]) == (False, False)

    async def test_menu_role_sees_primary_department_without_children(self, db, audit_identity):
        audit_identity.menu = True
        audit_identity.primary_dept_id = 2
        data = await _departments(_user())
        assert _ids(data["active"]) == [2]
        assert data["active"][0]["has_children"] is False
        assert data["archived"] == []

    async def test_refused_without_menu(self, db):
        with pytest.raises(UnAuthorizedError):
            await _departments(_user())

    async def test_other_tenant_id_refused_for_tenant_reader(self, db):
        with pytest.raises(UnAuthorizedError):
            await _departments(_user(admin=True), tenant_id=5)


class TestLazyAndSearch:
    async def test_children_are_active_only(self, db):
        data = await _departments(_user(admin=True), parent_id=2)
        assert _ids(data["active"]) == [3]
        assert data["archived"] == []

    async def test_lifted_tenant_root_is_not_repeated_as_child(self, db):
        data = await _departments(_user(admin=True, global_super=True), parent_id=1)
        assert _ids(data["active"]) == [2, 20, 80]

    @pytest.mark.parametrize("keyword,expected", [("ast", [3]), ("BS@3", [3]), ("E-110", [3])])
    async def test_search_matches_name_dept_id_external_id(self, db, keyword, expected):
        data = await _departments(_user(admin=True), keyword=keyword)
        assert _ids(data["active"]) == expected
        assert data["active"][0]["path_name"] == "Root/Sales/East"

    async def test_search_flattens_archived(self, db):
        data = await _departments(_user(admin=True), keyword="Old")
        assert (_ids(data["active"]), _ids(data["archived"])) == ([], [4])

    async def test_search_stays_inside_closure(self, db, audit_identity):
        audit_identity.menu = True
        audit_identity.admin_departments = [SimpleNamespace(path="/1/2/", tenant_id=1, is_deleted=0)]
        data = await _departments(_user(), keyword="R&D")
        assert data["active"] == []


class TestSessionUsers:
    async def _users(self, user, keyword=None):
        with (
            patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
            patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=1),
        ):
            return await AuditLogService.get_session_users(user, keyword, 50)

    async def test_admin_sees_every_session_user(self, db):
        assert [one["user_id"] for one in await self._users(_user(admin=True))] == [31, 32, 34]

    async def test_limited_to_the_scope(self, db, audit_identity):
        audit_identity.menu = True
        audit_identity.admin_departments = [SimpleNamespace(path="/1/2/", tenant_id=1, is_deleted=0)]
        assert [one["user_name"] for one in await self._users(_user())] == ["alice", "bob"]

    async def test_keyword(self, db):
        assert [one["user_name"] for one in await self._users(_user(admin=True), "car")] == ["carol"]
