"""F030 unit tests for ``TenantMountService.mount_child`` transaction behaviour.

Validates the two regressions fixed alongside F030:

1. INSERT tenant + UPDATE department happen inside a single session — when
   the dept update raises, ``session.commit`` is never called so SQLAlchemy
   rolls the INSERT back. (Pre-fix: two independent commits left a tenant
   row with an occupied ``tenant_code`` plus a NULL ``root_dept_id``,
   blocking every retry with 1062 Duplicate entry.)

2. ``tenant.root_dept_id`` is populated as part of the same INSERT, so the
   bidirectional dept↔tenant link is set in one shot. (Pre-fix: the column
   was always NULL, silently breaking every reader that scoped queries by
   it — most importantly ``TenantUserDialog`` member-picker subtree.)
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_operator():
    op = MagicMock()
    op.is_global_super = True
    op.user_id = 1
    return op


def _make_dept(dept_id: int = 4):
    dept = MagicMock()
    dept.id = dept_id
    dept.parent_id = 1  # not the root dept
    dept.is_tenant_root = 0
    dept.path = '/root/科技发展部'
    return dept


@asynccontextmanager
async def _yield_session(session):
    """Wrap a single session in an async-context-manager so it can stand in
    for ``get_async_db_session()`` inside the production code."""
    yield session


@pytest.mark.asyncio
async def test_mount_child_writes_root_dept_id_and_single_commit():
    """Happy path: tenant gets root_dept_id=dept_id and only one commit fires."""
    from bisheng.tenant.domain.services import tenant_mount_service as svc_mod

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    # Stand-in dept; DepartmentDao calls are mocked so we never hit the DB.
    dept = _make_dept(dept_id=4)

    with patch.object(svc_mod.DepartmentDao, 'aget_by_id', new=AsyncMock(return_value=dept)), \
         patch.object(svc_mod.DepartmentDao, 'aget_ancestors_with_mount', new=AsyncMock(return_value=None)), \
         patch.object(svc_mod, 'get_async_db_session', return_value=_yield_session(session)), \
         patch.object(svc_mod.TenantMountService, '_on_child_mounted', new=AsyncMock(return_value=[])), \
         patch.object(svc_mod, '_safe_audit', new=AsyncMock()):

        await svc_mod.TenantMountService.mount_child(
            dept_id=4,
            tenant_code='keji',
            tenant_name='科技发展部',
            operator=_make_operator(),
        )

    # ── INSERT side ────────────────────────────────────────────────
    session.add.assert_called_once()
    added_tenant = session.add.call_args.args[0]
    assert added_tenant.tenant_code == 'keji'
    assert added_tenant.tenant_name == '科技发展部'
    # ★ Bug-2 fix: bidirectional link written on INSERT.
    assert added_tenant.root_dept_id == 4

    # ── UPDATE side runs inside the same session ──────────────────
    session.execute.assert_awaited_once()
    # SQLAlchemy `update(...).where(...).values(...)` is the first positional arg.
    update_stmt = session.execute.await_args.args[0]
    compiled = str(update_stmt).lower()
    assert 'update' in compiled and 'department' in compiled

    # ── Single commit ────────────────────────────────────────────
    # Pre-fix code committed twice (once per DAO). The transaction fix
    # collapses both writes into one.
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_mount_child_rolls_back_when_dept_update_fails():
    """If the dept update raises, commit must NOT fire — INSERT rolls back
    cleanly with the session, leaving no tenant_code-occupied orphan."""
    from bisheng.tenant.domain.services import tenant_mount_service as svc_mod

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    # Simulate a failure halfway through (e.g. dept row vanished, FK
    # violation, deadlock — anything raised by the UPDATE).
    session.execute = AsyncMock(side_effect=RuntimeError('dept update boom'))
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    dept = _make_dept(dept_id=4)

    with patch.object(svc_mod.DepartmentDao, 'aget_by_id', new=AsyncMock(return_value=dept)), \
         patch.object(svc_mod.DepartmentDao, 'aget_ancestors_with_mount', new=AsyncMock(return_value=None)), \
         patch.object(svc_mod, 'get_async_db_session', return_value=_yield_session(session)), \
         patch.object(svc_mod.TenantMountService, '_on_child_mounted', new=AsyncMock(return_value=[])), \
         patch.object(svc_mod, '_safe_audit', new=AsyncMock()):

        with pytest.raises(RuntimeError, match='dept update boom'):
            await svc_mod.TenantMountService.mount_child(
                dept_id=4,
                tenant_code='keji',
                tenant_name='科技发展部',
                operator=_make_operator(),
            )

    # ★ Bug-1 fix: commit MUST NOT fire on failure. SQLAlchemy then closes
    # the session at the with-exit and rolls the INSERT back automatically.
    session.commit.assert_not_awaited()
    # Sanity: side effects gated on success never run.
    session.refresh.assert_not_awaited()
