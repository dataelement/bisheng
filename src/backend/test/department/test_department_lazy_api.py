"""F038 T003: integration tests for the platform lazy department-tree endpoints.

Drives the real endpoints (router → DepartmentService → DepartmentDao) against an
aiosqlite engine, mirroring test_department_api.py's harness:
- GET /departments/children?parent_id=&include_archived=   — one lazy layer
- GET /departments/search?keyword=&limit=&include_archived= — pruned match tree
- GET /departments/{id}/path-tree?include_archived=         — locate/reveal tree

Covers AC-01/02/03 (layer + has_children), AC-06/07/08/09 (search + truncate +
empty), AC-10 (locate deep node), AC-15 (out-of-scope denied without leak), plus
the three-tier scope (sys-admin full vs dept-admin clamped to its subtree).

Scope is computed by the same _aget_user_scope helper aget_tree uses; for the
dept-admin cases the admin/tenant lookups are mocked (no FGA), exactly like
test_department_scope_parity.py.
"""

import sys
from contextlib import ExitStack, asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.testclient import TestClient

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.database.models.department import DepartmentDao
from bisheng.department.api.router import router as department_router

_SVC = "bisheng.department.domain.services.department_service"

_DDL = """CREATE TABLE IF NOT EXISTS department (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dept_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    parent_id INTEGER,
    tenant_id INTEGER NOT NULL DEFAULT 1,
    path VARCHAR(512) NOT NULL DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    source VARCHAR(32) DEFAULT 'local',
    external_id VARCHAR(128),
    status VARCHAR(16) DEFAULT 'active',
    is_tenant_root INTEGER NOT NULL DEFAULT 0,
    mounted_tenant_id INTEGER,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    last_sync_ts BIGINT NOT NULL DEFAULT 0,
    default_role_ids JSON,
    concurrent_session_limit INTEGER NOT NULL DEFAULT 0,
    create_user INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(source, external_id)
)"""

# (id, dept_id, name, parent_id, path, status, sort_order)
_SEED = [
    (1, "BS@1", "Root", None, "/1/", "active", 0),
    (2, "BS@2", "Engineering", 1, "/1/2/", "active", 0),
    (3, "BS@3", "Sales", 1, "/1/3/", "active", 1),
    (4, "BS@4", "Backend", 2, "/1/2/4/", "active", 0),
    (5, "BS@5", "Frontend", 2, "/1/2/5/", "active", 1),
    (6, "BS@6", "OldUnit", 1, "/1/6/", "archived", 2),
    (7, "BS@7", "DeepTeam", 4, "/1/2/4/7/", "active", 0),
    (8, "BS@8", "SalesEast", 3, "/1/3/8/", "active", 0),
]


class MockAdminUser:
    user_id = 1
    user_name = "admin"
    user_role = [1]  # AdminRole → _is_admin True
    tenant_id = 1
    group_cache = {}


class MockNonAdminUser:
    user_id = 99
    user_name = "deptadmin"
    user_role = [2]
    tenant_id = 1
    group_cache = {}


@pytest.fixture()
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.execute(text(_DDL))
        cols = ("id", "dept_id", "name", "parent_id", "path", "status", "sort_order")
        for row in _SEED:
            await conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, parent_id, path, status, sort_order) "
                    "VALUES (:id, :dept_id, :name, :parent_id, :path, :status, :sort_order)"
                ),
                dict(zip(cols, row)),
            )
    yield eng
    await eng.dispose()


@contextmanager
def _client_for(engine, user):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(department_router, prefix="/api/v1")

    async def _get_user():
        return user

    app.dependency_overrides[UserPayload.get_login_user] = _get_user
    with (
        patch(f"{_SVC}.get_async_db_session", _factory),
        patch("bisheng.database.models.department.get_async_db_session", _factory),
    ):
        with TestClient(app) as c:
            yield c


@pytest.fixture()
def admin_client(engine):
    with _client_for(engine, MockAdminUser()) as c:
        yield c


@pytest.fixture()
def dept_admin_client(engine):
    """Non-sys-admin who administers dept 2 (Engineering, /1/2/). FGA/tenant
    lookups mocked so scope = the /1/2/ subtree only."""
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_SVC}._is_admin", return_value=False))
        stack.enter_context(
            patch.object(
                DepartmentDao,
                "aget_user_admin_departments",
                new=AsyncMock(return_value=[SimpleNamespace(id=2, path="/1/2/")]),
            )
        )
        stack.enter_context(patch(f"{_SVC}._is_tenant_admin", new=AsyncMock(return_value=False)))
        with _client_for(engine, MockNonAdminUser()) as c:
            yield c


def _ok(resp):
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200, body
    return body["data"]


# --------------------------------------------------------------------------- #
# children: lazy layer + has_children (AC-01/02/03)
# --------------------------------------------------------------------------- #
class TestChildrenLayer:
    def test_root_layer_sys_admin(self, admin_client):
        """AC-01: root layer = the tenant root only, not the whole tree."""
        data = _ok(admin_client.get("/api/v1/departments/children"))
        assert [n["id"] for n in data] == [1]
        assert data[0]["has_children"] is True
        assert data[0]["children"] == []

    def test_children_of_node_active_only(self, admin_client):
        """AC-02/03: direct children (active only), has_children per node."""
        data = _ok(admin_client.get("/api/v1/departments/children", params={"parent_id": 1}))
        assert [n["id"] for n in data] == [2, 3]  # archived 6 excluded
        by_id = {n["id"]: n for n in data}
        assert by_id[2]["has_children"] is True  # 4,5
        assert by_id[3]["has_children"] is True  # 8

    def test_children_include_archived(self, admin_client):
        """AC-16 support: management tree may include archived nodes."""
        data = _ok(
            admin_client.get(
                "/api/v1/departments/children",
                params={"parent_id": 1, "include_archived": "true"},
            )
        )
        assert [n["id"] for n in data] == [2, 3, 6]
        by_id = {n["id"]: n for n in data}
        assert by_id[6]["has_children"] is False  # leaf

    def test_has_children_false_for_leaf(self, admin_client):
        data = _ok(admin_client.get("/api/v1/departments/children", params={"parent_id": 2}))
        by_id = {n["id"]: n for n in data}
        assert by_id[4]["has_children"] is True  # has 7
        assert by_id[5]["has_children"] is False  # leaf

    def test_leaf_children_empty(self, admin_client):
        data = _ok(admin_client.get("/api/v1/departments/children", params={"parent_id": 5}))
        assert data == []


# --------------------------------------------------------------------------- #
# search: pruned tree + truncation + empty (AC-06/07/08)
# --------------------------------------------------------------------------- #
class TestSearch:
    def test_prunes_to_ancestor_chain(self, admin_client):
        """AC-06: match returns a tree expandable/locatable to the hit."""
        data = _ok(admin_client.get("/api/v1/departments/search", params={"keyword": "DeepTeam"}))
        assert data["truncated"] is False
        assert data["total_matches"] == 1
        assert [n["id"] for n in data["roots"]] == [1]
        n1 = data["roots"][0]
        assert [n["id"] for n in n1["children"]] == [2]
        n2 = n1["children"][0]
        assert [n["id"] for n in n2["children"]] == [4]
        n4 = n2["children"][0]
        assert [n["id"] for n in n4["children"]] == [7]
        assert n4["children"][0]["matched"] is True
        # ancestors are not themselves matches
        assert n1["matched"] is False

    def test_case_insensitive(self, admin_client):
        data = _ok(admin_client.get("/api/v1/departments/search", params={"keyword": "deepteam"}))
        assert data["total_matches"] == 1

    def test_truncated_when_over_limit(self, admin_client):
        """AC-07: more matches than limit → truncated flag."""
        data = _ok(admin_client.get("/api/v1/departments/search", params={"keyword": "e", "limit": 2}))
        # 'e' matches >2 active depts (Engineering/Sales/Backend/Frontend/DeepTeam/SalesEast)
        assert data["truncated"] is True

    def test_empty_keyword_returns_empty(self, admin_client):
        """AC-08: blank keyword → empty, no scan."""
        data = _ok(admin_client.get("/api/v1/departments/search", params={"keyword": "   "}))
        assert data == {"roots": [], "total_matches": 0, "truncated": False}


# --------------------------------------------------------------------------- #
# path-tree: locate/reveal (AC-10) + out-of-scope no-leak (AC-15)
# --------------------------------------------------------------------------- #
class TestPathTree:
    def test_locate_deep_node_sys_admin(self, admin_client):
        data = _ok(admin_client.get("/api/v1/departments/7/path-tree"))
        assert [n["id"] for n in data["roots"]] == [1]
        chain = []
        cur = data["roots"][0]
        while cur:
            chain.append(cur["id"])
            cur = cur["children"][0] if cur["children"] else None
        assert chain == [1, 2, 4, 7]
        # target flagged
        leaf = data["roots"][0]["children"][0]["children"][0]["children"][0]
        assert leaf["id"] == 7 and leaf["matched"] is True

    def test_locate_missing_node_sys_admin(self, admin_client):
        body = admin_client.get("/api/v1/departments/999/path-tree").json()
        assert body["status_code"] == 21000  # DepartmentNotFoundError


# --------------------------------------------------------------------------- #
# dept-admin scope clamp (AC-12/13) + out-of-scope no-leak (AC-15)
# --------------------------------------------------------------------------- #
class TestDeptAdminScope:
    def test_root_layer_is_admin_dept(self, dept_admin_client):
        """AC-12: root layer = the admin's own department, not the org root."""
        data = _ok(dept_admin_client.get("/api/v1/departments/children"))
        assert [n["id"] for n in data] == [2]

    def test_search_ancestors_clamped_to_scope(self, dept_admin_client):
        """AC-13 / gotcha 4: pruned tree roots at the admin dept, never above."""
        data = _ok(dept_admin_client.get("/api/v1/departments/search", params={"keyword": "DeepTeam"}))
        assert [n["id"] for n in data["roots"]] == [2]  # clamped, NOT 1
        assert data["roots"][0]["children"][0]["id"] == 4

    def test_path_tree_clamped(self, dept_admin_client):
        data = _ok(dept_admin_client.get("/api/v1/departments/7/path-tree"))
        assert [n["id"] for n in data["roots"]] == [2]

    def test_children_out_of_scope_parent_denied_no_leak(self, dept_admin_client):
        """AC-15: expanding an out-of-scope parent → permission error, no leak."""
        resp = dept_admin_client.get("/api/v1/departments/children", params={"parent_id": 3})
        body = resp.json()
        assert body["status_code"] == 21009  # DepartmentPermissionDeniedError
        assert "Sales" not in resp.text

    def test_locate_out_of_scope_denied_no_leak(self, dept_admin_client):
        resp = dept_admin_client.get("/api/v1/departments/3/path-tree")
        body = resp.json()
        assert body["status_code"] == 21009
        assert "Sales" not in resp.text


@pytest.mark.asyncio
async def test_search_empty_scope_returns_empty_no_count_leak():
    """F038 (review M1): a non-sys-admin whose visible scope resolves to EMPTY
    must get an empty search — no rows AND no tenant-wide ``total_matches`` count —
    not an unscoped ``name LIKE``. Short-circuited before the DAO."""
    from unittest.mock import MagicMock

    from bisheng.database.models.department import DepartmentDao
    from bisheng.department.domain.services.department_service import DepartmentService

    with (
        patch(f"{_SVC}._aget_user_scope", new=AsyncMock(return_value=(False, set()))),
        patch.object(DepartmentDao, "aget_by_name_like", new=AsyncMock(return_value=[])) as mock_search,
    ):
        result = await DepartmentService.asearch_tree(MagicMock(), keyword="anything")

    assert result == {"roots": [], "total_matches": 0, "truncated": False}
    mock_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_aget_by_name_like_empty_scope_returns_no_rows():
    """F038 (review M1): the DAO fails CLOSED — an empty ``path_prefixes`` list
    yields no rows (never an unscoped search), distinct from ``None`` (unscoped)."""
    from bisheng.database.models.department import DepartmentDao

    rows = await DepartmentDao.aget_by_name_like("x", path_prefixes=[])
    assert rows == []
