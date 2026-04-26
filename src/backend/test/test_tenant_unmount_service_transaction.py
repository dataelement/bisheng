"""F030 unit tests for ``TenantMountService.unmount_child`` transaction
behaviour and the archive-code suffix that lets operators remount under
the same code without 1062 Duplicate entry.

Validates:

1. ``archived_tenant_code`` adds a ``#archived#<unix_ts>`` suffix once and
   is idempotent on re-application (already-suffixed input is returned
   unchanged).
2. ``display_tenant_code`` strips the suffix for UI/audit display.
3. ``unmount_child`` archives the Child + frees its ``tenant_code`` + clears
   the dept mount flag inside a single ``session.commit`` so the dept and
   tenant cannot diverge into a half-archived/half-active state.
4. When the dept clear UPDATE fails, ``commit`` is never awaited — the
   archive UPDATE rolls back with the session, so retry is safe.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_operator():
    op = MagicMock()
    op.is_global_super = True
    op.user_id = 1
    return op


def _make_dept(dept_id: int = 4, tenant_id: int = 21):
    dept = MagicMock()
    dept.id = dept_id
    dept.parent_id = 1
    dept.is_tenant_root = 1
    dept.mounted_tenant_id = tenant_id
    dept.path = '/root/科技发展部'
    return dept


def _make_tenant(tenant_id: int = 21, code: str = 'keji'):
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.tenant_code = code
    tenant.tenant_name = '科技发展部'
    return tenant


@asynccontextmanager
async def _yield_session(session):
    yield session


# ── Pure helpers ───────────────────────────────────────────────────


def test_archived_tenant_code_appends_unix_timestamp():
    from bisheng.tenant.domain.services.tenant_mount_service import (
        ARCHIVED_CODE_SEPARATOR,
        archived_tenant_code,
    )

    out = archived_tenant_code('keji')
    assert out.startswith(f'keji{ARCHIVED_CODE_SEPARATOR}')
    # tail is a positive int (unix ts)
    suffix = out.split(ARCHIVED_CODE_SEPARATOR, 1)[1]
    assert suffix.isdigit() and int(suffix) > 0


def test_archived_tenant_code_is_idempotent():
    """Re-archiving an already-archived code must not double-suffix —
    the unmount path may run more than once during retries."""
    from bisheng.tenant.domain.services.tenant_mount_service import (
        archived_tenant_code,
    )

    once = archived_tenant_code('keji')
    twice = archived_tenant_code(once)
    assert once == twice


def test_display_tenant_code_strips_archive_suffix():
    from bisheng.tenant.domain.services.tenant_mount_service import (
        archived_tenant_code,
        display_tenant_code,
    )

    assert display_tenant_code('keji') == 'keji'  # active, untouched
    archived = archived_tenant_code('keji')
    assert display_tenant_code(archived) == 'keji'
    # Empty / None input must not crash
    assert display_tenant_code('') == ''


# ── Service-layer transaction tests ────────────────────────────────


@pytest.mark.asyncio
async def test_unmount_child_archives_code_and_single_commit():
    """Happy path: tenant gets archived + suffixed, dept gets unset,
    everything inside one session.commit."""
    from bisheng.tenant.domain.services import tenant_mount_service as svc_mod

    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    dept = _make_dept(dept_id=4, tenant_id=21)
    tenant = _make_tenant(tenant_id=21, code='keji')

    with patch.object(svc_mod.DepartmentDao, 'aget_by_id', new=AsyncMock(return_value=dept)), \
         patch.object(svc_mod.TenantDao, 'aget_by_id', new=AsyncMock(return_value=tenant)), \
         patch.object(svc_mod.TenantMountService, '_migrate_child_resources_to_root', new=AsyncMock(return_value={})), \
         patch.object(svc_mod, 'get_async_db_session', return_value=_yield_session(session)), \
         patch.object(svc_mod.TenantMountService, '_on_child_unmounted', new=AsyncMock()), \
         patch.object(svc_mod, '_safe_audit', new=AsyncMock()):

        await svc_mod.TenantMountService.unmount_child(
            dept_id=4,
            operator=_make_operator(),
        )

    # Two UPDATE statements: tenant archive + dept unset, in this order.
    assert session.execute.await_count == 2
    first_stmt = str(session.execute.await_args_list[0].args[0]).lower()
    second_stmt = str(session.execute.await_args_list[1].args[0]).lower()
    assert 'tenant' in first_stmt and 'update' in first_stmt
    assert 'department' in second_stmt and 'update' in second_stmt

    # ★ Single commit covers both writes.
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_unmount_child_rolls_back_when_dept_unset_fails():
    """If the dept UPDATE raises after the tenant archive UPDATE, commit
    must NOT fire — the in-flight archive change rolls back with the session
    so we don't end up with a half-archived tenant + still-mounted dept."""
    from bisheng.tenant.domain.services import tenant_mount_service as svc_mod

    session = MagicMock()
    # First UPDATE (tenant archive) succeeds; second (dept unset) blows up.
    session.execute = AsyncMock(side_effect=[None, RuntimeError('dept unset boom')])
    session.commit = AsyncMock()

    dept = _make_dept(dept_id=4, tenant_id=21)
    tenant = _make_tenant(tenant_id=21, code='keji')

    with patch.object(svc_mod.DepartmentDao, 'aget_by_id', new=AsyncMock(return_value=dept)), \
         patch.object(svc_mod.TenantDao, 'aget_by_id', new=AsyncMock(return_value=tenant)), \
         patch.object(svc_mod.TenantMountService, '_migrate_child_resources_to_root', new=AsyncMock(return_value={})), \
         patch.object(svc_mod, 'get_async_db_session', return_value=_yield_session(session)), \
         patch.object(svc_mod.TenantMountService, '_on_child_unmounted', new=AsyncMock()), \
         patch.object(svc_mod, '_safe_audit', new=AsyncMock()):

        with pytest.raises(RuntimeError, match='dept unset boom'):
            await svc_mod.TenantMountService.unmount_child(
                dept_id=4,
                operator=_make_operator(),
            )

    # ★ commit MUST NOT fire — SQLAlchemy then closes the session at with-exit
    # and rolls the archive UPDATE back, so the row stays in the active state
    # and the operator's retry sees a coherent world.
    session.commit.assert_not_awaited()
