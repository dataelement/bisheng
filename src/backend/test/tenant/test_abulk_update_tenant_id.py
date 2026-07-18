"""Tests for TenantDao.abulk_update_tenant_id atomicity (F011 AC-04a).

Review finding (MEDIUM): the previous implementation wrapped each table
UPDATE in its own try/except and committed once at the end of the loop.
That broke AC-04a "事务保证一致性": a mid-loop failure silently dropped
the failing table's delta while committing rows updated earlier.

This test pins the corrected contract:
  1. Happy path: all tables updated atomically, caller sees per-table rowcount.
  2. Failure path: any exception inside the loop MUST propagate; the session
     MUST NOT commit the partial changes; earlier-table updates are rolled back.
  3. Unknown-table ``OperationalError`` is treated like any other failure
     (no silent swallowing).
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _FakeSession:
    """Minimal async session mock that records execute() + commit/rollback order."""

    def __init__(self, outcomes):
        """outcomes: list of either int rowcount (success) or Exception (failure)."""
        self._outcomes = list(outcomes)
        self.calls: list = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, stmt, params=None):
        self.calls.append(('execute', str(stmt), params))
        next_outcome = self._outcomes.pop(0)
        if isinstance(next_outcome, Exception):
            raise next_outcome
        return _FakeResult(next_outcome)

    async def commit(self):
        self.calls.append(('commit',))
        self.committed = True

    async def rollback(self):
        self.calls.append(('rollback',))
        self.rolled_back = True


def _patch_session_factory(session):
    """Patch ``get_async_db_session`` inside the tenant module to yield ``session``."""

    @asynccontextmanager
    async def _fake_factory():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    return patch(
        'bisheng.database.models.tenant.get_async_db_session',
        _fake_factory,
    )


@pytest.mark.asyncio
class TestAbulkUpdateTenantIdAtomicity:

    async def test_happy_path_commits_and_returns_rowcounts(self):
        from bisheng.database.models.tenant import TenantDao

        session = _FakeSession([3, 2, 0])  # 3 tables, different rowcounts
        with _patch_session_factory(session):
            result = await TenantDao.abulk_update_tenant_id(
                tables=['flow', 'knowledge', 'channel'],
                from_tenant_id=5,
                to_tenant_id=1,
            )

        assert result == {'flow': 3, 'knowledge': 2, 'channel': 0}
        assert session.committed is True
        assert session.rolled_back is False

    async def test_midloop_failure_rolls_back_entire_transaction(self):
        """A mid-loop UPDATE failure MUST abort — no commit, no partial state.

        Atomicity pin: previously per-table ``try/except`` swallowed the
        error and committed the earlier tables. That contradicts AC-04a.
        """
        from bisheng.database.models.tenant import TenantDao

        boom = RuntimeError('simulated DB failure on 2nd table')
        session = _FakeSession([5, boom, 99])  # second table blows up
        with _patch_session_factory(session):
            with pytest.raises(RuntimeError, match='simulated DB failure'):
                await TenantDao.abulk_update_tenant_id(
                    tables=['flow', 'knowledge', 'channel'],
                    from_tenant_id=5,
                    to_tenant_id=1,
                )

        # Must NOT have reached commit.
        assert session.committed is False
        # Rollback must have happened (either by our helper or the DAO itself).
        assert session.rolled_back is True
        # Third table should not have been attempted (loop aborts on raise).
        exec_calls = [c for c in session.calls if c[0] == 'execute']
        assert len(exec_calls) == 2

    async def test_unknown_table_operational_error_propagates(self):
        """OperationalError ("no such table") must propagate just like any other."""
        from sqlalchemy.exc import OperationalError

        from bisheng.database.models.tenant import TenantDao

        err = OperationalError(
            statement='UPDATE ghost_table ...',
            params={},
            orig=Exception('no such table: ghost_table'),
        )
        session = _FakeSession([1, err])
        with _patch_session_factory(session):
            with pytest.raises(OperationalError):
                await TenantDao.abulk_update_tenant_id(
                    tables=['flow', 'ghost_table'],
                    from_tenant_id=5,
                    to_tenant_id=1,
                )

        assert session.committed is False
        assert session.rolled_back is True

    async def test_empty_table_list_is_noop(self):
        """Empty input is a valid, trivially atomic no-op."""
        from bisheng.database.models.tenant import TenantDao

        session = _FakeSession([])
        with _patch_session_factory(session):
            result = await TenantDao.abulk_update_tenant_id(
                tables=[], from_tenant_id=5, to_tenant_id=1,
            )
        assert result == {}
        # Still commits (empty transaction is fine).
        assert session.committed is True
        assert session.rolled_back is False
