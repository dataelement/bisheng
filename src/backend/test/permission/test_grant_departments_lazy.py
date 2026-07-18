"""F038 T005: lazy authorization-tree helpers (grant-subject departments).

The grant-subject department picker (knowledge-space share + channel authorize,
which share one backend helper) moves from one-shot full-tree to lazy
children/search/path-tree. Unlike the platform tree, scope here is the TENANT
ROOT SUBTREE minus child-tenant mount subtrees, optionally narrowed to a bound
department's subtree (F033) — NOT the admin scope (design decision 3).

These drive the shared helpers directly against an aiosqlite engine (mirroring
test_permission_api_integration.py's helper test), exercising:
- non-root tenant (no child-mount carve-out),
- ROOT tenant (child-mount subtrees excluded from browse/search/locate),
- F033 restrict_root_path (clamped to the bound department's subtree) — the
  channel picker is the restrict=None case, also covered here.

Covers AC-24/AC-26 (backend side).
"""

import sys
from contextlib import asynccontextmanager, contextmanager, nullcontext
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain

premock_import_chain()

from bisheng.permission.api.endpoints import resource_permission

_DEPT_DDL = """CREATE TABLE IF NOT EXISTS department (
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

_TENANT_DDL = """CREATE TABLE IF NOT EXISTS tenant (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_code VARCHAR(64) NOT NULL UNIQUE,
    tenant_name VARCHAR(128) NOT NULL,
    logo VARCHAR(512),
    root_dept_id INTEGER,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    parent_tenant_id INTEGER,
    share_default_to_children INTEGER NOT NULL DEFAULT 0,
    contact_name VARCHAR(64),
    contact_phone VARCHAR(32),
    contact_email VARCHAR(128),
    quota_config JSON,
    storage_config JSON,
    create_user INTEGER,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)"""

# (id, code, name, root_dept_id) — tenant 1 is the ROOT tenant (child-mount carve-out applies)
_TENANTS = [
    (1, "root", "Root Tenant", 10),
    (5, "t5", "Tenant Five", 50),
]

# (id, dept_id, name, parent_id, path, status, sort_order, is_tenant_root, mounted_tenant_id, tenant_id)
_DEPTS = [
    # ROOT-tenant tree (root 10), with a child-tenant mount at 20
    (10, "BS@10", "Org", None, "/10/", "active", 0, 0, None, 1),
    (11, "BS@11", "Eng", 10, "/10/11/", "active", 0, 0, None, 1),
    (12, "BS@12", "EngTeam", 11, "/10/11/12/", "active", 0, 0, None, 1),
    (13, "BS@13", "Sales", 10, "/10/13/", "active", 1, 0, None, 1),
    (20, "BS@20", "ChildMount", 10, "/10/20/", "active", 2, 1, 2, 1),
    (21, "BS@21", "ChildKid", 20, "/10/20/21/", "active", 0, 0, None, 2),
    # non-root tenant tree (root 50)
    (50, "BS@50", "T5Root", None, "/50/", "active", 0, 0, None, 5),
    (51, "BS@51", "T5Eng", 50, "/50/51/", "active", 0, 0, None, 5),
    (52, "BS@52", "T5Deep", 51, "/50/51/52/", "active", 0, 0, None, 5),
]


@pytest.fixture()
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.execute(text(_DEPT_DDL))
        await conn.execute(text(_TENANT_DDL))
        for row in _TENANTS:
            await conn.execute(
                text(
                    "INSERT INTO tenant (id, tenant_code, tenant_name, root_dept_id) VALUES (:id, :code, :name, :root)"
                ),
                dict(zip(("id", "code", "name", "root"), row)),
            )
        dcols = (
            "id",
            "dept_id",
            "name",
            "parent_id",
            "path",
            "status",
            "sort_order",
            "is_tenant_root",
            "mounted_tenant_id",
            "tenant_id",
        )
        for row in _DEPTS:
            await conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, parent_id, path, status, "
                    "sort_order, is_tenant_root, mounted_tenant_id, tenant_id) VALUES "
                    "(:id, :dept_id, :name, :parent_id, :path, :status, :sort_order, "
                    ":is_tenant_root, :mounted_tenant_id, :tenant_id)"
                ),
                dict(zip(dcols, row)),
            )
    yield eng
    await eng.dispose()


@contextmanager
def _patch(engine):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(engine) as session:
            yield session

    with (
        patch("bisheng.core.database.get_async_db_session", _factory),
        patch("bisheng.core.context.tenant.bypass_tenant_filter", lambda: nullcontext()),
    ):
        yield


# --------------------------------------------------------------------------- #
# children (browse one layer) + child-mount exclusion
# --------------------------------------------------------------------------- #
class TestGrantChildren:
    async def test_root_layer_non_root_tenant(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_children(tenant_id=5)
        assert [n["id"] for n in data] == [50]
        assert data[0]["has_children"] is True

    async def test_children_of_node(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_children(tenant_id=5, parent_id=50)
        by_id = {n["id"]: n for n in data}
        assert set(by_id) == {51}
        assert by_id[51]["has_children"] is True  # 52

    async def test_root_tenant_browse_excludes_child_mount(self, engine):
        """decision 3: ROOT tenant browse carves out child-tenant mount subtrees."""
        with _patch(engine):
            data = await resource_permission._grant_departments_children(tenant_id=1, parent_id=10)
        assert [n["id"] for n in data] == [11, 13]  # 20 (mount) excluded

    async def test_has_children_false_for_leaf(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_children(tenant_id=1, parent_id=11)
        by_id = {n["id"]: n for n in data}
        assert by_id[12]["has_children"] is False

    async def test_out_of_scope_parent_returns_empty(self, engine):
        """A parent inside an excluded child mount yields nothing (no leak)."""
        with _patch(engine):
            data = await resource_permission._grant_departments_children(tenant_id=1, parent_id=20)
        assert data == []


# --------------------------------------------------------------------------- #
# search → pruned tree, scoped + clamped
# --------------------------------------------------------------------------- #
class TestGrantSearch:
    async def test_pruned_to_root(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_search(tenant_id=1, keyword="EngTeam")
        assert data["truncated"] is False
        assert data["total_matches"] == 1
        assert [n["id"] for n in data["roots"]] == [10]
        n11 = data["roots"][0]["children"][0]
        assert n11["id"] == 11
        assert n11["children"][0]["id"] == 12
        assert n11["children"][0]["matched"] is True

    async def test_search_excludes_child_mount(self, engine):
        """Hits inside an excluded child mount are not returned (scope carve-out)."""
        with _patch(engine):
            data = await resource_permission._grant_departments_search(tenant_id=1, keyword="ChildKid")
        assert data["roots"] == []
        assert data["total_matches"] == 0

    async def test_empty_keyword(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_search(tenant_id=1, keyword="  ")
        assert data == {"roots": [], "total_matches": 0, "truncated": False}

    async def test_truncated(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_search(tenant_id=1, keyword="a", limit=1)
        # 'a' matches Org/Sales/... in root tenant → >1 → truncated
        assert data["truncated"] is True


# --------------------------------------------------------------------------- #
# path-tree (locate/reveal)
# --------------------------------------------------------------------------- #
class TestGrantPathTree:
    async def test_locate(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_path_tree(tenant_id=1, dept_id=12)
        assert [n["id"] for n in data["roots"]] == [10]
        leaf = data["roots"][0]["children"][0]["children"][0]
        assert leaf["id"] == 12 and leaf["matched"] is True

    async def test_locate_in_child_mount_returns_empty(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_path_tree(tenant_id=1, dept_id=21)
        assert data["roots"] == []


# --------------------------------------------------------------------------- #
# F033 restrict (department knowledge space) — clamp to bound subtree
# --------------------------------------------------------------------------- #
class TestF033Restrict:
    async def test_root_layer_is_bound_dept(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_children(tenant_id=1, restrict_root_path="/10/11/")
        assert [n["id"] for n in data] == [11]

    async def test_search_clamped_to_bound(self, engine):
        with _patch(engine):
            # "Org" (dept 10) is ABOVE the bound dept 11 → out of restricted scope
            data = await resource_permission._grant_departments_search(
                tenant_id=1, keyword="Org", restrict_root_path="/10/11/"
            )
        assert data["roots"] == []
        assert data["total_matches"] == 0

    async def test_path_tree_clamped_to_bound(self, engine):
        with _patch(engine):
            data = await resource_permission._grant_departments_path_tree(
                tenant_id=1, dept_id=12, restrict_root_path="/10/11/"
            )
        assert [n["id"] for n in data["roots"]] == [11]  # clamped at bound, not 10
