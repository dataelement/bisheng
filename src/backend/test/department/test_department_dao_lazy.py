"""F038 T001: DepartmentDao lazy-tree query extensions.

Runs the real async DAO methods against an aiosqlite engine (no middleware),
mirroring test_global_members_search.py's harness:
- aget_children(parent_id, include_archived) — single level, optional archived
- aget_children_existence(parent_ids, include_archived) — which parents have children
- aget_by_name_like(keyword, path_prefixes, limit, include_archived) — scoped name search

Scope (path_prefixes) is supplied by the Service; the DAO just applies it.
"""

import sys
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.database.models.department import DepartmentDao

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

# (id, dept_id, name, parent_id, path, status)
_SEED = [
    (1, "BS@1", "Root", None, "/1/", "active"),
    (2, "BS@2", "Alpha", 1, "/1/2/", "active"),
    (3, "BS@3", "Beta", 1, "/1/3/", "active"),
    (4, "BS@4", "Gamma", 2, "/1/2/4/", "active"),
    (5, "BS@5", "ArchivedDept", 1, "/1/5/", "archived"),
    (6, "BS@6", "OnlyArchivedParent", 1, "/1/6/", "active"),
    (7, "BS@7", "ArchKid", 6, "/1/6/7/", "archived"),
]


@pytest.fixture()
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.execute(text(_DDL))
        for row in _SEED:
            await conn.execute(
                text(
                    "INSERT INTO department (id, dept_id, name, parent_id, path, status) "
                    "VALUES (:id, :dept_id, :name, :parent_id, :path, :status)"
                ),
                dict(zip(("id", "dept_id", "name", "parent_id", "path", "status"), row)),
            )
    yield eng
    await eng.dispose()


def _patch(engine):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(engine) as session:
            yield session

    return patch("bisheng.database.models.department.get_async_db_session", _factory)


class TestAgetChildren:
    async def test_active_only_by_default(self, engine):
        with _patch(engine):
            children = await DepartmentDao.aget_children(1)
        assert {c.id for c in children} == {2, 3, 6}  # archived 5 excluded

    async def test_include_archived(self, engine):
        with _patch(engine):
            children = await DepartmentDao.aget_children(1, include_archived=True)
        assert {c.id for c in children} == {2, 3, 5, 6}

    async def test_root_layer_parent_none(self, engine):
        """F038: parent_id=None → root layer (parent_id IS NULL), i.e. the tenant root."""
        with _patch(engine):
            roots = await DepartmentDao.aget_children(None)
        assert {c.id for c in roots} == {1}


class TestAgetChildrenExistence:
    async def test_returns_only_parents_with_active_children(self, engine):
        with _patch(engine):
            existing = await DepartmentDao.aget_children_existence([1, 2, 3, 6])
        # 1→(2,3,6) yes; 2→(4) yes; 3→none; 6→only archived 7 (excluded) → no
        assert existing == {1, 2}

    async def test_include_archived_counts_archived_child(self, engine):
        with _patch(engine):
            existing = await DepartmentDao.aget_children_existence([6], include_archived=True)
        assert existing == {6}


class TestAgetByNameLike:
    async def test_substring_match_unscoped(self, engine):
        with _patch(engine):
            rows = await DepartmentDao.aget_by_name_like("amma", path_prefixes=None, limit=50)
        assert {r.id for r in rows} == {4}  # Gamma

    async def test_scope_path_prefixes(self, engine):
        with _patch(engine):
            rows = await DepartmentDao.aget_by_name_like("a", path_prefixes=["/1/2/"], limit=50)
        # only the /1/2/ subtree: Alpha(2, /1/2/) and Gamma(4, /1/2/4/); Beta(/1/3/) excluded
        assert {r.id for r in rows} == {2, 4}

    async def test_archived_excluded_by_default(self, engine):
        with _patch(engine):
            rows = await DepartmentDao.aget_by_name_like("rchiv", path_prefixes=None, limit=50)
        # ArchivedDept(5) and ArchKid(7) are archived → excluded; OnlyArchivedParent(6) active
        assert {r.id for r in rows} == {6}

    async def test_limit_caps_results(self, engine):
        with _patch(engine):
            rows = await DepartmentDao.aget_by_name_like("a", path_prefixes=None, limit=1)
        assert len(rows) == 1
