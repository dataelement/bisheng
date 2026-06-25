"""Tests for DepartmentService.aget_global_members_search.

Performance-oriented rewrite (option A): username PREFIX search (index-friendly),
no GROUP BY (relies on the single-primary-department invariant), and a single
``COUNT(*) OVER()`` window for the total instead of a second aggregate query.

Runs the real SQL against an async SQLite engine so the query semantics
(prefix match, per-user dedup, total count, visible-scope filter) are exercised
end-to-end rather than asserted on a mocked statement string.
"""

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.department.domain.services.department_service import DepartmentService

_DDL = [
    """CREATE TABLE IF NOT EXISTS department (
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
    )""",
    """CREATE TABLE IF NOT EXISTS user_department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        department_id INTEGER NOT NULL,
        is_primary INTEGER DEFAULT 1,
        source VARCHAR(32) DEFAULT 'local',
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        UNIQUE(user_id, department_id)
    )""",
    """CREATE TABLE IF NOT EXISTS user (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name VARCHAR(255) UNIQUE,
        email VARCHAR(255),
        phone_number VARCHAR(64),
        dept_id VARCHAR(64),
        password VARCHAR(255) NOT NULL DEFAULT 'hashed',
        "delete" INTEGER DEFAULT 0,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )""",
]


@pytest.fixture()
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))
    yield eng
    await eng.dispose()


def _session_patch(engine):
    @asynccontextmanager
    async def _factory():
        async with AsyncSession(engine) as session:
            yield session

    return patch(
        "bisheng.department.domain.services.department_service.get_async_db_session",
        _factory,
    )


async def _seed_dept(engine, *, did, dept_id, name, path):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO department (id, dept_id, name, path, status) "
                "VALUES (:id, :dept_id, :name, :path, 'active')"
            ),
            {"id": did, "dept_id": dept_id, "name": name, "path": path},
        )


async def _seed_user(engine, *, uid, name, dept_int_id, is_primary=1, deleted=0):
    async with engine.begin() as conn:
        await conn.execute(
            text('INSERT OR IGNORE INTO user (user_id, user_name, "delete") VALUES (:uid, :name, :deleted)'),
            {"uid": uid, "name": name, "deleted": deleted},
        )
        await conn.execute(
            text("INSERT INTO user_department (user_id, department_id, is_primary) VALUES (:uid, :dept, :prim)"),
            {"uid": uid, "dept": dept_int_id, "prim": is_primary},
        )


def _visible_tree(*dept_ids):
    nodes = [SimpleNamespace(id=d, children=[]) for d in dept_ids]
    return patch.object(
        DepartmentService,
        "aget_tree",
        new_callable=AsyncMock,
        return_value=nodes,
    )


_login = SimpleNamespace(user_id=1, tenant_id=1, is_global_super=True)


class TestGlobalMembersSearch:
    async def test_prefix_match_excludes_infix_hits(self, engine):
        """'li' must match 'lisa' (prefix) but NOT 'alice' (infix).

        This is the behavioral switch from ``LIKE '%kw%'`` to ``LIKE 'kw%'``.
        """
        await _seed_dept(engine, did=10, dept_id="BS@d", name="Dept", path="/10/")
        await _seed_user(engine, uid=1, name="lisa", dept_int_id=10)
        await _seed_user(engine, uid=2, name="alice", dept_int_id=10)
        await _seed_user(engine, uid=3, name="bob", dept_int_id=10)

        with _session_patch(engine), _visible_tree(10):
            res = await DepartmentService.aget_global_members_search("li", 1, 20, _login)

        names = {r["user_name"] for r in res["data"]}
        assert names == {"lisa"}
        assert res["total"] == 1

    async def test_total_uses_single_window_count(self, engine):
        """Total reflects all matches across pages, from one query (window count)."""
        await _seed_dept(engine, did=10, dept_id="BS@d", name="Dept", path="/10/")
        for i in range(25):
            await _seed_user(engine, uid=100 + i, name=f"team{i:02d}", dept_int_id=10)

        with _session_patch(engine), _visible_tree(10):
            page1 = await DepartmentService.aget_global_members_search("team", 1, 20, _login)
        with _session_patch(engine), _visible_tree(10):
            page2 = await DepartmentService.aget_global_members_search("team", 2, 20, _login)

        assert page1["total"] == 25
        assert page2["total"] == 25
        assert len(page1["data"]) == 20
        assert len(page2["data"]) == 5
        # No user appears on both pages (stable ordering, real pagination).
        assert not ({r["user_id"] for r in page1["data"]} & {r["user_id"] for r in page2["data"]})

    async def test_out_of_range_page_keeps_total(self, engine):
        """An over-paged request returns empty data but the correct total."""
        await _seed_dept(engine, did=10, dept_id="BS@d", name="Dept", path="/10/")
        for i in range(5):
            await _seed_user(engine, uid=200 + i, name=f"crew{i}", dept_int_id=10)

        with _session_patch(engine), _visible_tree(10):
            res = await DepartmentService.aget_global_members_search("crew", 3, 20, _login)

        assert res["data"] == []
        assert res["total"] == 5

    async def test_one_row_per_user_with_secondary_membership(self, engine):
        """A user with a secondary (is_primary=0) dept yields exactly one row."""
        await _seed_dept(engine, did=10, dept_id="BS@d1", name="Primary", path="/10/")
        await _seed_dept(engine, did=11, dept_id="BS@d2", name="Second", path="/11/")
        await _seed_user(engine, uid=1, name="kelly", dept_int_id=10, is_primary=1)
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO user_department (user_id, department_id, is_primary) VALUES (1, 11, 0)")
            )

        with _session_patch(engine), _visible_tree(10, 11):
            res = await DepartmentService.aget_global_members_search("kelly", 1, 20, _login)

        assert res["total"] == 1
        assert len(res["data"]) == 1
        assert res["data"][0]["primary_department_dept_id"] == "BS@d1"

    async def test_visible_scope_filters_out_other_departments(self, engine):
        """Users whose primary dept is outside the visible set are excluded."""
        await _seed_dept(engine, did=10, dept_id="BS@vis", name="Visible", path="/10/")
        await _seed_dept(engine, did=20, dept_id="BS@hid", name="Hidden", path="/20/")
        await _seed_user(engine, uid=1, name="sam_in", dept_int_id=10)
        await _seed_user(engine, uid=2, name="sam_out", dept_int_id=20)

        with _session_patch(engine), _visible_tree(10):
            res = await DepartmentService.aget_global_members_search("sam", 1, 20, _login)

        assert {r["user_name"] for r in res["data"]} == {"sam_in"}
        assert res["total"] == 1

    async def test_disabled_user_included_and_flagged(self, engine):
        """Disabled accounts (delete=1) are returned with enabled=False."""
        await _seed_dept(engine, did=10, dept_id="BS@d", name="Dept", path="/10/")
        await _seed_user(engine, uid=1, name="gone", dept_int_id=10, deleted=1)

        with _session_patch(engine), _visible_tree(10):
            res = await DepartmentService.aget_global_members_search("gone", 1, 20, _login)

        assert res["total"] == 1
        assert res["data"][0]["enabled"] is False

    async def test_blank_keyword_short_circuits(self, engine):
        with _session_patch(engine), _visible_tree(10):
            res = await DepartmentService.aget_global_members_search("   ", 1, 20, _login)
        assert res == {"data": [], "total": 0}
