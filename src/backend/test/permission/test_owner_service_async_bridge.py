import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.permission.domain.services import owner_service as owner_mod
from bisheng.permission.domain.services.owner_service import OwnerService


async def _sample():
    return 'ok'


_PERM_SVC = 'bisheng.permission.domain.services.permission_service.PermissionService'


@pytest.mark.asyncio
async def test_delete_non_owner_resource_tuples_deletes_only_non_owner():
    fga = MagicMock()
    fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:1', 'relation': 'owner', 'object': 'channel:c1'},
        {'user': 'user:2', 'relation': 'viewer', 'object': 'channel:c1'},
        {'user': 'department:3#member', 'relation': 'manager', 'object': 'channel:c1'},
    ])
    with patch(f'{_PERM_SVC}._get_fga', return_value=fga), patch(
        f'{_PERM_SVC}.batch_write_tuples', new_callable=AsyncMock,
    ) as mock_batch:
        deleted = await OwnerService.delete_non_owner_resource_tuples('channel', 'c1')

    assert deleted == 2
    mock_batch.assert_awaited_once()
    ops = mock_batch.await_args.args[0]
    assert {op.user for op in ops} == {'user:2', 'department:3#member'}
    assert all(op.action == 'delete' and op.relation != 'owner' for op in ops)


@pytest.mark.asyncio
async def test_delete_non_owner_resource_tuples_noop_when_only_owner():
    fga = MagicMock()
    fga.read_tuples = AsyncMock(return_value=[
        {'user': 'user:1', 'relation': 'owner', 'object': 'channel:c1'},
    ])
    with patch(f'{_PERM_SVC}._get_fga', return_value=fga), patch(
        f'{_PERM_SVC}.batch_write_tuples', new_callable=AsyncMock,
    ) as mock_batch:
        deleted = await OwnerService.delete_non_owner_resource_tuples('channel', 'c1')

    assert deleted == 0
    mock_batch.assert_not_awaited()


def test_run_async_safe_uses_anyio_bridge_when_available(monkeypatch):
    monkeypatch.setattr(asyncio, 'get_running_loop', lambda: (_ for _ in ()).throw(RuntimeError()))

    class _FromThread:
        @staticmethod
        def run(fn, awaitable):
            awaitable.close()
            return 'bridged'

    monkeypatch.setitem(sys.modules, 'anyio', type('AnyIO', (), {'from_thread': _FromThread})())

    assert owner_mod._run_async_safe(_sample()) == 'bridged'


def test_run_async_safe_falls_back_only_without_worker_bridge(monkeypatch):
    monkeypatch.setattr(asyncio, 'get_running_loop', lambda: (_ for _ in ()).throw(RuntimeError()))

    class _FromThread:
        @staticmethod
        def run(fn, awaitable):
            raise RuntimeError('This function can only be run from an AnyIO worker thread')

    monkeypatch.setitem(sys.modules, 'anyio', type('AnyIO', (), {'from_thread': _FromThread})())
    monkeypatch.setattr(asyncio, 'run', lambda coro: (coro.close(), 'standalone')[1])

    assert owner_mod._run_async_safe(_sample()) == 'standalone'


def test_run_async_safe_does_not_mask_bridge_errors_with_new_loop(monkeypatch):
    monkeypatch.setattr(asyncio, 'get_running_loop', lambda: (_ for _ in ()).throw(RuntimeError()))

    class _FromThread:
        @staticmethod
        def run(fn, awaitable):
            raise ValueError('bridge failed')

    monkeypatch.setitem(sys.modules, 'anyio', type('AnyIO', (), {'from_thread': _FromThread})())

    called = False

    def _run(_):
        nonlocal called
        called = True
        return 'unexpected'

    monkeypatch.setattr(asyncio, 'run', _run)

    with pytest.raises(ValueError, match='bridge failed'):
        owner_mod._run_async_safe(_sample())

    assert called is False
