from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.core.openfga.exceptions import FGAWriteError
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.permission_service import PermissionService


def _op(action: str, obj: str) -> TupleOperation:
    return TupleOperation(
        action=action,
        user='user:400',
        relation='owner',
        object=obj,
    )


@pytest.mark.asyncio
async def test_batch_write_tuples_ignores_duplicate_write_errors():
    async def side_effect(*, writes=None, deletes=None):
        if writes and len(writes) == 2:
            raise FGAWriteError('cannot write a tuple which already exists')
        if writes == [{
            'user': 'user:400',
            'relation': 'owner',
            'object': 'tool:2202',
        }]:
            raise FGAWriteError('cannot write a tuple which already exists')

    fake_fga = SimpleNamespace(write_tuples=AsyncMock(side_effect=side_effect))
    ops = [_op('write', 'tool:2202'), _op('write', 'tool:2203')]

    with patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_save_failed_tuples', AsyncMock()) as save_failed:
        await PermissionService.batch_write_tuples(ops)

    save_failed.assert_not_awaited()
    assert fake_fga.write_tuples.await_count == 3


@pytest.mark.asyncio
async def test_batch_write_tuples_ignores_missing_delete_errors():
    async def side_effect(*, writes=None, deletes=None):
        if deletes and len(deletes) == 2:
            raise FGAWriteError('tuple to be deleted did not exist')
        if deletes == [{
            'user': 'user:400',
            'relation': 'owner',
            'object': 'tool:2202',
        }]:
            raise FGAWriteError('tuple to be deleted did not exist')

    fake_fga = SimpleNamespace(write_tuples=AsyncMock(side_effect=side_effect))
    ops = [_op('delete', 'tool:2202'), _op('delete', 'tool:2203')]

    with patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_save_failed_tuples', AsyncMock()) as save_failed:
        await PermissionService.batch_write_tuples(ops)

    save_failed.assert_not_awaited()
    assert fake_fga.write_tuples.await_count == 3


@pytest.mark.asyncio
async def test_batch_write_tuples_records_only_unresolved_single_failures():
    async def side_effect(*, writes=None, deletes=None):
        if writes and len(writes) == 2:
            raise FGAWriteError('batch rejected')
        if writes == [{
            'user': 'user:400',
            'relation': 'owner',
            'object': 'tool:2203',
        }]:
            raise FGAWriteError('unexpected validation failure')

    fake_fga = SimpleNamespace(write_tuples=AsyncMock(side_effect=side_effect))
    ops = [_op('write', 'tool:2202'), _op('write', 'tool:2203')]

    with patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_save_failed_tuples', AsyncMock()) as save_failed:
        await PermissionService.batch_write_tuples(ops)

    save_failed.assert_awaited_once()
    failed_ops, error_msg = save_failed.await_args.args
    assert failed_ops == [_op('write', 'tool:2203')]
    assert error_msg == 'OpenFGA single-tuple fallback failed'


@pytest.mark.asyncio
async def test_batch_write_tuples_strict_stops_before_revokes_after_failed_grant():
    async def side_effect(*, writes=None, deletes=None):
        if writes and len(writes) == 2:
            raise FGAWriteError('batch rejected')
        if writes == [{
            'user': 'user:400',
            'relation': 'owner',
            'object': 'tool:2202',
        }]:
            raise FGAWriteError('unexpected validation failure')

    fake_fga = SimpleNamespace(write_tuples=AsyncMock(side_effect=side_effect))
    ops = [_op('write', 'tool:2202'), _op('delete', 'tool:2203')]

    with patch.object(PermissionService, '_get_fga', return_value=fake_fga), \
            patch.object(PermissionService, '_save_failed_tuples', AsyncMock()) as save_failed:
        with pytest.raises(FGAWriteError):
            await PermissionService.batch_write_tuples(
                ops,
                raise_on_failure=True,
                stop_on_failure=True,
            )

    save_failed.assert_awaited_once()
    failed_ops, error_msg = save_failed.await_args.args
    assert failed_ops == ops
    assert error_msg == 'OpenFGA single-tuple fallback failed'
    standalone_delete_calls = [
        call.kwargs for call in fake_fga.write_tuples.await_args_list
        if call.kwargs.get('deletes') and not call.kwargs.get('writes')
    ]
    assert standalone_delete_calls == []


@pytest.mark.asyncio
async def test_batch_write_tuples_uses_async_fga_accessor_first():
    fake_fga = SimpleNamespace(write_tuples=AsyncMock())
    ops = [_op('write', 'assistant:2202')]

    with patch(
        'bisheng.core.openfga.manager.aget_fga_client',
        new_callable=AsyncMock,
        return_value=fake_fga,
    ) as async_get_fga, patch.object(
        PermissionService,
        '_get_fga',
        return_value=None,
    ), patch.object(
        PermissionService,
        '_save_failed_tuples',
        AsyncMock(),
    ) as save_failed:
        await PermissionService.batch_write_tuples(ops)

    async_get_fga.assert_awaited_once()
    fake_fga.write_tuples.assert_awaited_once_with(
        writes=[{
            'user': 'user:400',
            'relation': 'owner',
            'object': 'assistant:2202',
        }],
        deletes=None,
    )
    save_failed.assert_not_awaited()
