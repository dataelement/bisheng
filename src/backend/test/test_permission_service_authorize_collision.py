from unittest.mock import AsyncMock, patch

import pytest

from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.services.permission_service import PermissionService


@pytest.mark.asyncio
async def test_authorize_write_wins_over_same_tuple_delete():
    """Switching a subject's relation model without changing the underlying
    relation produces a grant + revoke of the same tuple. The write must win so
    the grant is not silently cancelled by the delete."""
    captured = {}

    async def _capture(operations, **kwargs):
        captured['operations'] = operations

    with patch.object(
        PermissionService, '_legacy_alias_object_types', new=AsyncMock(return_value=[]),
    ), patch.object(
        PermissionService, '_expand_subject', new=AsyncMock(return_value=['user:2']),
    ), patch.object(
        PermissionService, '_affected_user_ids_for_subject', new=AsyncMock(return_value=set()),
    ), patch.object(
        PermissionService, 'batch_write_tuples', new=AsyncMock(side_effect=_capture),
    ):
        await PermissionService.authorize(
            object_type='channel',
            object_id='c1',
            grants=[AuthorizeGrantItem(subject_type='user', subject_id=2, relation='manager')],
            revokes=[AuthorizeRevokeItem(subject_type='user', subject_id=2, relation='manager')],
        )

    ops = captured['operations']
    actions = {(op.action, op.user, op.relation, op.object) for op in ops}
    assert ('write', 'user:2', 'manager', 'channel:c1') in actions
    assert ('delete', 'user:2', 'manager', 'channel:c1') not in actions


@pytest.mark.asyncio
async def test_authorize_keeps_delete_of_a_different_relation():
    """A genuine relation change (revoke old relation, grant new) must keep both
    operations — only same-tuple collisions are collapsed."""
    captured = {}

    async def _capture(operations, **kwargs):
        captured['operations'] = operations

    with patch.object(
        PermissionService, '_legacy_alias_object_types', new=AsyncMock(return_value=[]),
    ), patch.object(
        PermissionService, '_expand_subject', new=AsyncMock(return_value=['user:2']),
    ), patch.object(
        PermissionService, '_affected_user_ids_for_subject', new=AsyncMock(return_value=set()),
    ), patch.object(
        PermissionService, 'batch_write_tuples', new=AsyncMock(side_effect=_capture),
    ):
        await PermissionService.authorize(
            object_type='channel',
            object_id='c1',
            grants=[AuthorizeGrantItem(subject_type='user', subject_id=2, relation='editor')],
            revokes=[AuthorizeRevokeItem(subject_type='user', subject_id=2, relation='viewer')],
        )

    actions = {(op.action, op.user, op.relation, op.object) for op in captured['operations']}
    assert ('write', 'user:2', 'editor', 'channel:c1') in actions
    assert ('delete', 'user:2', 'viewer', 'channel:c1') in actions
