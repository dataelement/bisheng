"""The identity / organisation MCP tools (F052 T207a, served by F067 ``open_mcp``).

``identity:read`` is the high-risk scope: granting it means the whole tenant's
org chart is readable, and there is deliberately no way to narrow it to some
departments. So what has to hold is (a) a service account with no management
role still sees the *full* tree — reusing the department admin tree would have
handed it an empty one and looked like a permission bug; (b) the tenant is a
hard wall, and crossing it is indistinguishable from asking for something that
does not exist; (c) no credential-bearing field can leave, and service accounts
never appear among people.
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.mcp_face import McpIdentityNotFoundError
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.department.domain.services.org_directory_service import OrgDirectoryService
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_mcp.registry import TOOL_REGISTRY, list_tools_for
from bisheng.open_mcp.tools import execute_tool
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole

TENANT = 9
OTHER_TENANT = 10

#: Every module whose DAOs must talk to the in-memory engine instead of MySQL.
_DAO_MODULES = (
    "bisheng.database.models.department",
    "bisheng.database.models.role",
    "bisheng.database.models.tenant",
    "bisheng.user.domain.models.user",
    "bisheng.user.domain.models.user_role",
)


@pytest.fixture
async def org(monkeypatch):
    """Two tenants, a two-level tree, one disabled person, one role."""

    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as connection:
        for model in (Department, UserDepartment, User, UserTenant, Role):
            await connection.run_sync(model.__table__.create)
        # ``UserRole`` declares an autoincrement ``id`` alongside a composite
        # primary key, which SQLite refuses to compile. Hand-written DDL rather
        # than reshaping a production model to suit a test engine.
        await connection.execute(
            text(
                "CREATE TABLE userrole ("
                " id INTEGER,"
                " user_id INTEGER NOT NULL,"
                " role_id INTEGER NOT NULL,"
                " tenant_id INTEGER NOT NULL DEFAULT 1,"
                " create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
                " update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,"
                " PRIMARY KEY (user_id, role_id))"
            )
        )

    @asynccontextmanager
    async def session_factory():
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for module_name in _DAO_MODULES:
        monkeypatch.setattr(importlib.import_module(module_name), "get_async_db_session", session_factory)

    async with session_factory() as session:
        session.add_all(
            [
                Department(id=1, dept_id="BS@root", name="总部", parent_id=None, tenant_id=TENANT, path="/1/"),
                Department(
                    id=2, dept_id="BS@rd", name="研发", parent_id=1, tenant_id=TENANT, path="/1/2/", sort_order=1
                ),
                Department(
                    id=3, dept_id="BS@ops", name="运维", parent_id=1, tenant_id=TENANT, path="/1/3/", sort_order=0
                ),
                Department(
                    id=4,
                    dept_id="BS@arch",
                    name="已归档",
                    parent_id=1,
                    tenant_id=TENANT,
                    path="/1/4/",
                    status="archived",
                ),
                Department(id=5, dept_id="BS@other", name="他租户", parent_id=None, tenant_id=OTHER_TENANT, path="/5/"),
                User(user_id=101, user_name="alice", password="x"),
                User(user_id=102, user_name="bob", password="x"),
                User(user_id=103, user_name="carol", password="x", delete=1),
                User(user_id=901, user_name="outsider", password="x"),
                UserTenant(user_id=101, tenant_id=TENANT, is_active=1),
                UserTenant(user_id=102, tenant_id=TENANT, is_active=1),
                UserTenant(user_id=103, tenant_id=TENANT, is_active=1),
                UserTenant(user_id=901, tenant_id=OTHER_TENANT, is_active=1),
                # Explicit ids: ``user_department.id`` is a BigInteger, and
                # SQLite only autoincrements a plain INTEGER primary key.
                UserDepartment(id=1, user_id=101, department_id=2),
                UserDepartment(id=2, user_id=102, department_id=3),
                UserDepartment(id=3, user_id=103, department_id=2),
                Role(id=50, role_name="知识管理员", tenant_id=TENANT),
                UserRole(user_id=101, role_id=50, tenant_id=TENANT),
            ]
        )
        await session.commit()

    token = set_current_tenant_id(TENANT)
    try:
        yield session_factory
    finally:
        from bisheng.core.context.tenant import current_tenant_id

        current_tenant_id.reset(token)
        await engine.dispose()


# --- the service ------------------------------------------------------------


async def test_the_tree_is_the_whole_tenant_with_no_management_role_needed(org):
    """A service account administers nothing; the department admin tree would be empty."""

    tree = await OrgDirectoryService.atree()
    assert [node["dept_id"] for node in tree] == ["BS@root"]
    children = tree[0]["children"]
    # Sorted by sort_order, then name — the archived node is not in the tree.
    assert [node["dept_id"] for node in children] == ["BS@ops", "BS@rd"]
    assert tree[0]["parent_id"] is None
    assert children[0]["parent_id"] == "BS@root"


async def test_the_tree_carries_no_tenant_topology(org):
    """``is_tenant_root`` / ``mounted_tenant_id`` are platform administration, not org data."""

    tree = await OrgDirectoryService.atree()
    assert set(tree[0]) == {
        "dept_id",
        "name",
        "parent_id",
        "path",
        "sort_order",
        "source",
        "status",
        "children",
    }


async def test_another_tenants_departments_are_not_in_the_tree(org):
    tree = await OrgDirectoryService.atree()
    flattened = []

    def walk(nodes):
        for node in nodes:
            flattened.append(node["dept_id"])
            walk(node["children"])

    walk(tree)
    assert "BS@other" not in flattened


async def test_a_person_lookup_carries_no_credential_field(org):
    payload = await OrgDirectoryService.aget_user(101)
    assert set(payload) == {"user_id", "user_name", "status", "departments", "roles"}
    assert payload["user_name"] == "alice"
    assert payload["roles"] == ["知识管理员"]
    assert payload["departments"] == [{"dept_id": "BS@rd", "name": "研发", "path": "/1/2/"}]


async def test_a_disabled_person_is_reported_as_disabled_not_hidden(org):
    """Hiding them would read as "no such user" and send an agent hunting a typo.

    It would also make ``status`` a field that can only ever say "active".
    """

    payload = await OrgDirectoryService.aget_user(103)
    assert payload["user_name"] == "carol"
    assert payload["status"] == "disabled"

    members = await OrgDirectoryService.amembers("BS@rd")
    assert {member["user_name"]: member["status"] for member in members["members"]} == {
        "alice": "active",
        "carol": "disabled",
    }


async def test_another_tenants_person_is_indistinguishable_from_a_missing_one(org):
    assert await OrgDirectoryService.aget_user(901) is None
    assert await OrgDirectoryService.aget_user(99999) is None


async def test_department_members_are_paged(org):
    payload = await OrgDirectoryService.amembers("BS@rd", page=1, size=1)
    assert payload["total"] == 2
    assert len(payload["members"]) == 1
    assert set(payload["members"][0]) == {"user_id", "user_name", "status"}


async def test_members_of_another_tenants_department_read_as_missing(org):
    assert await OrgDirectoryService.amembers("BS@other") is None
    assert await OrgDirectoryService.amembers("BS@nope") is None


# --- through the MCP tool layer -----------------------------------------------


async def test_the_tools_answer_with_the_identity_scope(org):
    tree = await execute_tool("bisheng_org_tree", {})
    user = await execute_tool("bisheng_identity_get_user", {"target_user_id": 101})
    members = await execute_tool("bisheng_dept_members", {"dept_id": "BS@rd"})

    assert tree.departments[0].dept_id == "BS@root"
    assert user.user_name == "alice"
    assert members.total == 2


async def test_a_cross_tenant_lookup_and_a_missing_one_give_the_same_answer(org):
    with pytest.raises(McpIdentityNotFoundError) as outsider:
        await execute_tool("bisheng_identity_get_user", {"target_user_id": 901})
    with pytest.raises(McpIdentityNotFoundError) as absent:
        await execute_tool("bisheng_identity_get_user", {"target_user_id": 99999})

    assert outsider.value.to_dict() == absent.value.to_dict()
    assert outsider.value.code == 26306


async def test_service_accounts_never_appear_among_people(org):
    """They have no ``user`` row and belong to no department, so this is structural.

    The key's own subject id is 31; asking for it must not resolve to the
    natural person who happens to hold user id 31.
    """

    with pytest.raises(McpIdentityNotFoundError):
        await execute_tool("bisheng_identity_get_user", {"target_user_id": 31})


def test_without_the_scope_the_tools_are_neither_listed_nor_callable():
    principal = _principal(frozenset({"knowledge:read"}))
    listed = {tool.name for tool in list_tools_for(principal)}

    assert "bisheng_org_tree" not in listed
    assert not TOOL_REGISTRY["bisheng_dept_members"].visible_to(principal)


def test_with_the_scope_all_three_tools_are_listed():
    listed = {tool.name for tool in list_tools_for(_principal(frozenset({"identity:read"})))}

    assert {"bisheng_identity_get_user", "bisheng_org_tree", "bisheng_dept_members"} <= listed


def _principal(scopes: frozenset[str]) -> OpenApiPrincipal:
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind="service_account",
        actor_id=31,
        actor_name="indexer",
        tenant_id=9,
        resource_owner_user_id=12,
        scopes=scopes,
        authorization_subject_type="service_account",
        authorization_subject_id=31,
        effective_user_id=None,
    )
