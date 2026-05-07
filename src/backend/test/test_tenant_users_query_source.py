"""Tests for F024 ``UserDepartmentDao.aget_users_by_tenant_subtree``.

Real-DB integration tests using aiosqlite. The new DAO replaces
``UserTenantDao.aget_tenant_users`` as the authoritative source for the
tenant user list — it derives membership from primary department mounted
in the tenant subtree (consistent with ``TenantResolver``), not from
``UserTenant`` rows.

Covers:
  - AC-01: only users whose primary dept is in the tenant subtree appear
  - AC-02: same after a primary-dept relocation (verified by data shape,
    actual relocation flow tested in test_apply_local_primary_dept_sync.py)
  - AC-03: secondary (is_primary=0) memberships do not surface
  - AC-04: keyword filter works
  - AC-12: legacy phantom UserTenant rows (v2.5.0 ``aadd_users`` residue
    where the user's primary dept is NOT in the subtree) do NOT appear

Self-contained DDL — does not rely on conftest table fixtures (which had
schema drift causing failures in earlier P0/G1/G2 fix sessions).
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime
from types import ModuleType
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


# ── Real User SQLModel (replaces the conftest pre-mock for THIS file) ─────
# The DAO under test does ``from bisheng.user.domain.models.user import User``
# inside its body. The conftest pre-mocks that module path with MagicMock,
# which doesn't satisfy SQLAlchemy's ``select(User.user_id)``.
#
# We *augment* (not replace) the existing pre-mocked module: keep the
# MagicMock attributes (``UserDao`` etc. used by other tests in the same
# pytest session) and add a real ``User`` SQLModel for the column refs.

class _TestUser(SQLModel, table=True):
    __tablename__ = 'user'
    __table_args__ = {'extend_existing': True}

    user_id: Optional[int] = Field(default=None, primary_key=True)
    user_name: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    avatar: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    password: str = Field(default='hashed', sa_column=Column(String(255), nullable=False))


_existing = sys.modules.get('bisheng.user.domain.models.user')
if _existing is None:
    _existing = ModuleType('bisheng.user.domain.models.user')
    sys.modules['bisheng.user.domain.models.user'] = _existing
# Always set real User class; preserve any other attrs (UserDao etc. from
# the conftest MagicMock) untouched.
_existing.User = _TestUser


# ── DDL: minimal 5-table schema needed by the DAO query ───────────────────

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS tenant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_code VARCHAR(64) NOT NULL UNIQUE,
        tenant_name VARCHAR(128) NOT NULL,
        root_dept_id INTEGER,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        parent_tenant_id INTEGER,
        share_default_to_children INTEGER NOT NULL DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dept_id VARCHAR(64) NOT NULL UNIQUE,
        name VARCHAR(128) NOT NULL,
        parent_id INTEGER,
        tenant_id INTEGER NOT NULL DEFAULT 1,
        path VARCHAR(512) NOT NULL DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        source VARCHAR(32) DEFAULT 'local',
        status VARCHAR(16) DEFAULT 'active',
        is_tenant_root INTEGER NOT NULL DEFAULT 0,
        mounted_tenant_id INTEGER,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_department (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        department_id INTEGER NOT NULL,
        is_primary INTEGER DEFAULT 1,
        source VARCHAR(32) DEFAULT 'local',
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        UNIQUE(user_id, department_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_tenant (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tenant_id INTEGER NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        is_active INTEGER,
        last_access_time DATETIME,
        join_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name VARCHAR(255) UNIQUE,
        password VARCHAR(255) NOT NULL DEFAULT 'hashed',
        avatar VARCHAR(512),
        "delete" INTEGER DEFAULT 0,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
]


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        'sqlite+aiosqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine):
    async with AsyncSession(bind=db_engine) as s:
        yield s


@pytest_asyncio.fixture
async def patched_dao(db_engine, monkeypatch):
    """Monkeypatch ``get_async_db_session`` inside the department module so
    the DAO under test runs against our sqlite engine.
    """

    @asynccontextmanager
    async def _factory():
        async with AsyncSession(bind=db_engine) as s:
            yield s

    from bisheng.database import models as models_pkg  # noqa: F401
    monkeypatch.setattr(
        'bisheng.database.models.department.get_async_db_session', _factory,
    )
    yield


# ── Data-builder helpers ──────────────────────────────────────────────────

async def _insert_tenant(session: AsyncSession, *, tid: int, code: str,
                         root_dept_id: Optional[int] = None,
                         parent_tenant_id: Optional[int] = None) -> None:
    await session.execute(text(
        'INSERT INTO tenant (id, tenant_code, tenant_name, root_dept_id, '
        '                    parent_tenant_id, status) '
        'VALUES (:id, :code, :name, :rd, :pt, "active")'
    ), {'id': tid, 'code': code, 'name': f'T{tid}',
        'rd': root_dept_id, 'pt': parent_tenant_id})


async def _insert_dept(session: AsyncSession, *, did: int, dept_id: str,
                       path: str, parent_id: Optional[int] = None,
                       tenant_id: int = 1) -> None:
    await session.execute(text(
        'INSERT INTO department (id, dept_id, name, parent_id, tenant_id, '
        '                        path, status) '
        'VALUES (:id, :dept_id, :name, :pid, :tid, :path, "active")'
    ), {'id': did, 'dept_id': dept_id, 'name': dept_id,
        'pid': parent_id, 'tid': tenant_id, 'path': path})


async def _insert_user(session: AsyncSession, *, uid: int, name: str,
                       avatar: Optional[str] = None) -> None:
    await session.execute(text(
        'INSERT INTO user (user_id, user_name, avatar, password) '
        'VALUES (:uid, :name, :avatar, "hashed")'
    ), {'uid': uid, 'name': name, 'avatar': avatar})


async def _insert_user_dept(session: AsyncSession, *, uid: int,
                            dept_id: int, is_primary: int = 1) -> None:
    await session.execute(text(
        'INSERT INTO user_department (user_id, department_id, is_primary) '
        'VALUES (:uid, :did, :ip)'
    ), {'uid': uid, 'did': dept_id, 'ip': is_primary})


async def _insert_user_tenant(session: AsyncSession, *, uid: int, tid: int,
                              is_active: Optional[int] = None,
                              last_access: Optional[datetime] = None) -> None:
    await session.execute(text(
        'INSERT INTO user_tenant (user_id, tenant_id, is_active, '
        '                         last_access_time) '
        'VALUES (:uid, :tid, :ia, :la)'
    ), {'uid': uid, 'tid': tid, 'ia': is_active, 'la': last_access})


async def _setup_two_tenant_world(session: AsyncSession) -> None:
    """Build a world with:
      - Tenant 1 (Root) — root dept id=10, path='/10/'
      - Tenant 5 (Child mounted at dept 20) — root dept id=20, path='/10/20/'
      - sub-dept 30 of tenant 5 — path='/10/20/30/'
      - sibling dept 40 of root — path='/10/40/' (NOT in tenant 5 subtree)
    """
    await _insert_tenant(session, tid=1, code='root', root_dept_id=10)
    await _insert_tenant(session, tid=5, code='child', root_dept_id=20,
                         parent_tenant_id=1)
    await _insert_dept(session, did=10, dept_id='BS@root', path='/10/',
                       tenant_id=1)
    await _insert_dept(session, did=20, dept_id='BS@child', path='/10/20/',
                       parent_id=10, tenant_id=5)
    await _insert_dept(session, did=30, dept_id='BS@sub', path='/10/20/30/',
                       parent_id=20, tenant_id=5)
    await _insert_dept(session, did=40, dept_id='BS@sibling', path='/10/40/',
                       parent_id=10, tenant_id=1)
    await session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_returns_users_with_primary_dept_in_subtree(
    session, patched_dao,
):
    """AC-01: Users whose primary dept is in tenant 5 subtree appear."""
    await _setup_two_tenant_world(session)
    # User A: primary dept = 20 (tenant 5 root) → IN subtree
    await _insert_user(session, uid=101, name='alice')
    await _insert_user_dept(session, uid=101, dept_id=20, is_primary=1)
    # User B: primary dept = 30 (tenant 5 sub-dept) → IN subtree
    await _insert_user(session, uid=102, name='bob')
    await _insert_user_dept(session, uid=102, dept_id=30, is_primary=1)
    # User C: primary dept = 40 (tenant 1 sibling) → NOT in subtree
    await _insert_user(session, uid=103, name='charlie')
    await _insert_user_dept(session, uid=103, dept_id=40, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=20,
    )

    assert total == 2
    uids = {r['user_id'] for r in rows}
    assert uids == {101, 102}


@pytest.mark.asyncio
async def test_secondary_membership_does_not_surface(session, patched_dao):
    """AC-03: Users whose only tie to the subtree is is_primary=0 are excluded."""
    await _setup_two_tenant_world(session)
    # User D: primary in dept 40 (NOT subtree), secondary in dept 30 (in subtree)
    await _insert_user(session, uid=201, name='dora')
    await _insert_user_dept(session, uid=201, dept_id=40, is_primary=1)
    await _insert_user_dept(session, uid=201, dept_id=30, is_primary=0)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=20,
    )

    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_legacy_user_tenant_phantom_rows_excluded(session, patched_dao):
    """AC-12: v2.5.0 ``aadd_users`` residue (UserTenant row but primary dept
    is NOT in the subtree) does NOT appear in the new query.
    """
    await _setup_two_tenant_world(session)
    # User E: primary dept = 40 (NOT in tenant 5 subtree) — but has a
    # passive UserTenant(tenant=5) row written by legacy aadd_users.
    await _insert_user(session, uid=301, name='eve')
    await _insert_user_dept(session, uid=301, dept_id=40, is_primary=1)
    await _insert_user_tenant(session, uid=301, tid=5, is_active=None)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=20,
    )

    assert total == 0


@pytest.mark.asyncio
async def test_user_tenant_left_join_decorates_join_time(session, patched_dao):
    """AC-01 detail: users with a UserTenant(tenant_id=this, is_active=1) row
    get ``join_time`` populated; users without one still return (LEFT JOIN).
    """
    await _setup_two_tenant_world(session)
    last_access = datetime(2026, 5, 1, 12, 0, 0)
    # User F: primary in dept 20 + active UserTenant row → join_time populated
    await _insert_user(session, uid=401, name='frank')
    await _insert_user_dept(session, uid=401, dept_id=20, is_primary=1)
    await _insert_user_tenant(session, uid=401, tid=5, is_active=1,
                              last_access=last_access)
    # User G: primary in dept 30, no UserTenant row at all → still in list
    await _insert_user(session, uid=402, name='grace')
    await _insert_user_dept(session, uid=402, dept_id=30, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=20,
    )

    assert total == 2
    by_uid = {r['user_id']: r for r in rows}
    assert by_uid[401]['join_time'] is not None
    assert by_uid[402]['join_time'] is None


@pytest.mark.asyncio
async def test_keyword_filter(session, patched_dao):
    """AC-04: keyword filter on user_name."""
    await _setup_two_tenant_world(session)
    await _insert_user(session, uid=501, name='alice_smith')
    await _insert_user_dept(session, uid=501, dept_id=20, is_primary=1)
    await _insert_user(session, uid=502, name='bob_jones')
    await _insert_user_dept(session, uid=502, dept_id=20, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=20, keyword='alice',
    )

    assert total == 1
    assert rows[0]['user_id'] == 501


@pytest.mark.asyncio
async def test_pagination(session, patched_dao):
    """page/page_size respected; total reflects full match count."""
    await _setup_two_tenant_world(session)
    for i in range(5):
        await _insert_user(session, uid=600 + i, name=f'user{i}')
        await _insert_user_dept(session, uid=600 + i, dept_id=20, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows1, total1 = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=2,
    )
    rows2, total2 = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=2, page_size=2,
    )

    assert total1 == 5
    assert total2 == 5
    assert len(rows1) == 2
    assert len(rows2) == 2
    # No overlap between pages
    assert {r['user_id'] for r in rows1}.isdisjoint(
        {r['user_id'] for r in rows2}
    )


@pytest.mark.asyncio
async def test_fallback_when_tenant_has_no_root_dept_id(session, patched_dao):
    """v2.5.0 / early v2.5.1 data: tenant.root_dept_id IS NULL — fall back
    to ``Department.tenant_id == tenant_id`` filter so the view still works.
    """
    # Tenant 7 with no root_dept_id set
    await _insert_tenant(session, tid=7, code='legacy', root_dept_id=None)
    await _insert_dept(session, did=70, dept_id='BS@legacy_root', path='/70/',
                       tenant_id=7)
    await _insert_user(session, uid=701, name='heidi')
    await _insert_user_dept(session, uid=701, dept_id=70, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    rows, total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=7, page=1, page_size=20,
    )

    assert total == 1
    assert rows[0]['user_id'] == 701


# ── F024 phase-2: count parity tests ──────────────────────────────────────
# The tenant list "user_count" column must match the dialog list source. We
# verify ``acount_users_by_tenant_subtree`` (single + batch) and the legacy
# list DAO's ``total`` agree under all the scenarios above so phantom rows
# never re-surface.


@pytest.mark.asyncio
async def test_count_subtree_matches_list_total(session, patched_dao):
    """count == aget_users_by_tenant_subtree.total for the same tenant."""
    await _setup_two_tenant_world(session)
    await _insert_user(session, uid=801, name='ivan')
    await _insert_user_dept(session, uid=801, dept_id=20, is_primary=1)
    await _insert_user(session, uid=802, name='judy')
    await _insert_user_dept(session, uid=802, dept_id=30, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    _, list_total = await UserDepartmentDao.aget_users_by_tenant_subtree(
        tenant_id=5, page=1, page_size=20,
    )
    count = await UserDepartmentDao.acount_users_by_tenant_subtree(tenant_id=5)
    assert count == list_total == 2


@pytest.mark.asyncio
async def test_count_subtree_excludes_phantom_user_tenant(session, patched_dao):
    """Phantom-only tenants must report user_count=0 — the precise bug F035 fixes."""
    await _setup_two_tenant_world(session)
    # Phantom: user's primary dept is in the sibling subtree, but a stale
    # is_active=1 UserTenant row points at tenant 5.
    await _insert_user(session, uid=901, name='kate')
    await _insert_user_dept(session, uid=901, dept_id=40, is_primary=1)
    await _insert_user_tenant(session, uid=901, tid=5, is_active=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    count = await UserDepartmentDao.acount_users_by_tenant_subtree(tenant_id=5)
    assert count == 0


@pytest.mark.asyncio
async def test_count_subtree_batch_matches_singles(session, patched_dao):
    """Batch result must equal the per-tenant single-count for every id."""
    await _setup_two_tenant_world(session)
    # Tenant 5: one user; Tenant 1: one user via dept 40.
    await _insert_user(session, uid=1001, name='leo')
    await _insert_user_dept(session, uid=1001, dept_id=20, is_primary=1)
    await _insert_user(session, uid=1002, name='mia')
    await _insert_user_dept(session, uid=1002, dept_id=40, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    batch = await UserDepartmentDao.acount_users_by_tenant_subtree_batch(
        [1, 5, 9999],
    )
    single_1 = await UserDepartmentDao.acount_users_by_tenant_subtree(1)
    single_5 = await UserDepartmentDao.acount_users_by_tenant_subtree(5)
    # Tenant 1's subtree includes its descendants — both deps live under /10/.
    assert batch.get(1, 0) == single_1
    assert batch.get(5, 0) == single_5
    # Unknown tenant id → omitted (default 0).
    assert 9999 not in batch


@pytest.mark.asyncio
async def test_count_subtree_fallback_no_root_dept_id(session, patched_dao):
    """Same fallback semantic as the list DAO — uses Department.tenant_id."""
    await _insert_tenant(session, tid=8, code='legacy2', root_dept_id=None)
    await _insert_dept(session, did=80, dept_id='BS@legacy2_root', path='/80/',
                       tenant_id=8)
    await _insert_user(session, uid=1101, name='nora')
    await _insert_user_dept(session, uid=1101, dept_id=80, is_primary=1)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    count = await UserDepartmentDao.acount_users_by_tenant_subtree(8)
    batch = await UserDepartmentDao.acount_users_by_tenant_subtree_batch([8])
    assert count == 1
    assert batch.get(8) == 1


@pytest.mark.asyncio
async def test_count_subtree_secondary_membership_excluded(session, patched_dao):
    """is_primary=0 ties must not bump the count (parity with list DAO)."""
    await _setup_two_tenant_world(session)
    await _insert_user(session, uid=1201, name='oscar')
    await _insert_user_dept(session, uid=1201, dept_id=40, is_primary=1)
    await _insert_user_dept(session, uid=1201, dept_id=30, is_primary=0)
    await session.commit()

    from bisheng.database.models.department import UserDepartmentDao
    count = await UserDepartmentDao.acount_users_by_tenant_subtree(tenant_id=5)
    assert count == 0
