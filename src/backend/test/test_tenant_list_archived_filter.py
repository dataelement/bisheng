"""TenantDao.alist_tenants must hide archived rows from the regular list.

Archived is a terminal state used purely for audit (see
``tenant_mount_service.unmount_child``). Letting archived rows surface in the
default tenant management list confuses operators because:

  * unmount + remount of the same dept produces two rows with identical
    ``tenant_name`` (one archived, one active), and
  * ``display_tenant_code`` strips the ``#archived#<ts>`` suffix on the way
    out, so even ``tenant_code`` looks duplicated.

The fix is a default ``status != 'archived'`` predicate; callers that need
the archived rows (audit views, tests) opt in by passing
``status='archived'`` explicitly.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _session_context(mock_session):
    @asynccontextmanager
    async def _cm():
        yield mock_session

    return _cm


def _make_session(total: int = 0):
    """Async session double whose ``exec`` records every statement and returns
    a deterministic count then an empty row set."""
    captured: list = []

    count_result = MagicMock()
    count_result.one = MagicMock(return_value=total)
    rows_result = MagicMock()
    rows_result.all = MagicMock(return_value=[])

    async def _fake_exec(stmt):
        captured.append(stmt)
        return count_result if len(captured) == 1 else rows_result

    session = MagicMock()
    session.exec = AsyncMock(side_effect=_fake_exec)
    return session, captured


def _compiled_where(stmts) -> str:
    return ' '.join(
        str(s.compile(compile_kwargs={'literal_binds': True})) for s in stmts
    ).lower()


@pytest.mark.asyncio
async def test_alist_tenants_excludes_archived_by_default():
    from bisheng.database.models.tenant import TenantDao

    session, captured = _make_session(total=0)
    with patch(
        'bisheng.database.models.tenant.get_async_db_session',
        _session_context(session),
    ):
        rows, total = await TenantDao.alist_tenants()

    assert rows == []
    assert total == 0
    where_sql = _compiled_where(captured)
    # Either MySQL/SQLite (``!=``) or PostgreSQL (``<>``) renderings are fine.
    assert (
        "status != 'archived'" in where_sql
        or "status <> 'archived'" in where_sql
    ), where_sql


@pytest.mark.asyncio
async def test_alist_tenants_explicit_archived_status_returns_archived_rows():
    """Audit / debug callers can still list archived rows by passing the
    status filter explicitly. The default exclusion must NOT win in that case."""
    from bisheng.database.models.tenant import TenantDao

    session, captured = _make_session(total=0)
    with patch(
        'bisheng.database.models.tenant.get_async_db_session',
        _session_context(session),
    ):
        await TenantDao.alist_tenants(status='archived')

    where_sql = _compiled_where(captured)
    assert "status = 'archived'" in where_sql, where_sql
    # The implicit-exclude branch must not also fire when status is given —
    # otherwise the predicate would be ``= 'archived' AND != 'archived'``
    # which silently returns zero rows.
    assert "!= 'archived'" not in where_sql
    assert "<> 'archived'" not in where_sql


@pytest.mark.asyncio
async def test_alist_tenants_active_status_filter_unchanged():
    """A status='active' filter must keep behaving as a single equality
    predicate — the default-exclude branch should not stack onto it."""
    from bisheng.database.models.tenant import TenantDao

    session, captured = _make_session(total=0)
    with patch(
        'bisheng.database.models.tenant.get_async_db_session',
        _session_context(session),
    ):
        await TenantDao.alist_tenants(status='active')

    where_sql = _compiled_where(captured)
    assert "status = 'active'" in where_sql, where_sql
    assert "!= 'archived'" not in where_sql
    assert "<> 'archived'" not in where_sql
