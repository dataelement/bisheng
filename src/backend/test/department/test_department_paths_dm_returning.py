"""Regression: department path-rewrite DAO methods must disable ORM session
synchronization so no RETURNING clause is injected.

Background: DM (达梦) inherits Oracle's ``RETURNING ... INTO``, which is
single-row only. An ORM UPDATE whose WHERE uses ``LIKE`` (not Python-evaluatable)
falls back to the "fetch" synchronize_session strategy, which injects
``RETURNING <pk>`` on RETURNING-capable dialects. On a multi-row subtree rewrite
DM then raises ``[CODE:-5016] Invalid return into multi rows``.

These DAO methods therefore run with ``synchronize_session=False`` (plain UPDATE,
no RETURNING, rowcount preserved). DM is not exercised in CI, so these tests
guard against the flag being removed by a future "cleanup".
"""

from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from bisheng.database.models.department import DepartmentDao


def _make_sync_factory():
    captured: list = []
    session = MagicMock()
    session.execute.side_effect = lambda stmt, *a, **k: captured.append(stmt) or MagicMock()

    @contextmanager
    def factory():
        yield session

    return factory, captured


def _make_async_factory():
    captured: list = []
    session = MagicMock()

    async def _execute(stmt, *a, **k):
        captured.append(stmt)
        return MagicMock(rowcount=0)

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    return factory, captured


def _sync_disabled(stmt) -> bool:
    return stmt.get_execution_options().get("synchronize_session") is False


def test_update_paths_batch_disables_session_sync():
    factory, captured = _make_sync_factory()
    with patch("bisheng.database.models.department.get_sync_db_session", factory):
        DepartmentDao.update_paths_batch("/3/", "/1/3/")

    assert captured, "update_paths_batch should emit an UPDATE"
    assert all(_sync_disabled(s) for s in captured)


async def test_aupdate_paths_batch_disables_session_sync():
    factory, captured = _make_async_factory()
    with patch("bisheng.database.models.department.get_async_db_session", factory):
        await DepartmentDao.aupdate_paths_batch("/3/", "/1/3/")

    assert captured, "aupdate_paths_batch should emit an UPDATE"
    assert all(_sync_disabled(s) for s in captured)


async def test_areparent_root_under_disables_sync_on_subtree_rewrite():
    factory, captured = _make_async_factory()
    with patch("bisheng.database.models.department.get_async_db_session", factory):
        await DepartmentDao.areparent_root_under(dept_id=3, old_path="/3/", new_path="/1/3/", new_parent_id=1)

    # First statement is the multi-row LIKE-prefix subtree rewrite — the one that
    # would trip DM's -5016. It must run with synchronize_session=False.
    assert captured, "areparent_root_under should emit the subtree UPDATE"
    assert _sync_disabled(captured[0])
