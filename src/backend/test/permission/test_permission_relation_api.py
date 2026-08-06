from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.permission.application.relation_api import (
    PermissionObject,
    PermissionRelation,
    PermissionRelationApplication,
    PermissionRelationChange,
    PermissionSubject,
    get_permission_relation_api,
    is_tenant_admin,
)


def _relation(*, subject_id: str = "7") -> PermissionRelation:
    return PermissionRelation(
        subject=PermissionSubject("user", subject_id),
        relation="admin",
        resource=PermissionObject("tenant", "5"),
    )


async def test_check_encodes_semantic_permission_values() -> None:
    client = AsyncMock()
    client.check = AsyncMock(return_value=True)
    permissions = PermissionRelationApplication(client)

    allowed = await permissions.check(
        subject=PermissionSubject("department", "3", relation="member"),
        relation="visible",
        resource=PermissionObject("workflow", "flow-1"),
        consistency="HIGHER_CONSISTENCY",
    )

    assert allowed is True
    client.check.assert_awaited_once_with(
        user="department:3#member",
        relation="visible",
        object="workflow:flow-1",
        consistency="HIGHER_CONSISTENCY",
    )


async def test_batch_check_rejects_incomplete_backend_result() -> None:
    client = AsyncMock()
    client.batch_check = AsyncMock(return_value=[])
    permissions = PermissionRelationApplication(client)

    with pytest.raises(PermissionServiceUnavailableError):
        await permissions.batch_check((_relation(),))


async def test_query_methods_hide_backend_encoding() -> None:
    client = AsyncMock()
    client.list_objects = AsyncMock(return_value=["workflow:a", "workflow:b", "tenant:wrong", "workflow:a"])
    client.read_tuples = AsyncMock(
        return_value=[
            {"user": "user:7", "relation": "admin", "object": "tenant:5"},
            {"user": "department:3#member", "relation": "visible", "object": "workflow:a"},
        ]
    )
    permissions = PermissionRelationApplication(client)

    resource_ids = await permissions.list_resource_ids(
        subject=PermissionSubject("user", "7"),
        relation="visible",
        resource_type="workflow",
    )
    subject_ids = await permissions.list_subject_ids(
        resource=PermissionObject("tenant", "5"),
        relation="admin",
        subject_type="user",
    )
    relations = await permissions.list_relations(subject=PermissionSubject("user", "7"))

    assert resource_ids == ("a", "b")
    assert subject_ids == ("7",)
    assert relations == (
        _relation(),
        PermissionRelation(
            subject=PermissionSubject("department", "3", relation="member"),
            relation="visible",
            resource=PermissionObject("workflow", "a"),
        ),
    )


async def test_grant_and_revoke_encode_only_inside_permission_module() -> None:
    client = AsyncMock()
    client.write_tuples = AsyncMock()
    permissions = PermissionRelationApplication(client)
    relation = _relation()

    await permissions.grant((relation,))
    await permissions.revoke((relation,))

    client.write_tuples.assert_any_await(
        writes=[{"user": "user:7", "relation": "admin", "object": "tenant:5"}],
        deletes=None,
    )
    client.write_tuples.assert_any_await(
        writes=None,
        deletes=[{"user": "user:7", "relation": "admin", "object": "tenant:5"}],
    )


async def test_crash_safe_changes_translate_only_inside_permission_module() -> None:
    client = AsyncMock()
    permissions = PermissionRelationApplication(client)
    changes = (
        PermissionRelationChange(action="grant", relation=_relation(subject_id="7")),
        PermissionRelationChange(action="revoke", relation=_relation(subject_id="9")),
    )

    with patch(
        "bisheng.permission.domain.services.permission_service.PermissionService.batch_write_tuples",
        new=AsyncMock(),
    ) as batch_write:
        await permissions.apply_changes(changes, crash_safe=True)

    batch_write.assert_awaited_once()
    operations = batch_write.await_args.args[0]
    assert [(operation.action, operation.user) for operation in operations] == [
        ("write", "user:7"),
        ("delete", "user:9"),
    ]
    assert batch_write.await_args.kwargs == {"crash_safe": True}
    client.write_tuples.assert_not_awaited()


async def test_client_failures_are_translated_to_permission_error() -> None:
    client = AsyncMock()
    client.check = AsyncMock(side_effect=ConnectionError("backend down"))
    permissions = PermissionRelationApplication(client)

    with pytest.raises(PermissionServiceUnavailableError):
        await permissions.check(
            subject=PermissionSubject("user", "7"),
            relation="admin",
            resource=PermissionObject("tenant", "5"),
        )


async def test_getter_waits_for_process_runtime_and_returns_protocol() -> None:
    relations = AsyncMock()
    runtime = SimpleNamespace(components=SimpleNamespace(relations=relations))

    with patch(
        "bisheng.permission.application.process_runtime.get_f048_process_runtime",
        new=AsyncMock(return_value=runtime),
    ) as get_runtime:
        resolved = await get_permission_relation_api()

    assert resolved is relations
    get_runtime.assert_awaited_once()


async def test_getter_translates_runtime_initialization_failure() -> None:
    with (
        patch(
            "bisheng.permission.application.process_runtime.get_f048_process_runtime",
            new=AsyncMock(side_effect=RuntimeError("not ready")),
        ),
        pytest.raises(PermissionServiceUnavailableError),
    ):
        await get_permission_relation_api()


async def test_tenant_admin_query_uses_permission_application_protocol() -> None:
    permissions = AsyncMock()
    permissions.check = AsyncMock(return_value=True)

    with patch(
        "bisheng.permission.application.relation_api.get_permission_relation_api",
        new=AsyncMock(return_value=permissions),
    ):
        assert await is_tenant_admin(7, 5) is True

    permissions.check.assert_awaited_once_with(
        subject=PermissionSubject("user", "7"),
        relation="admin",
        resource=PermissionObject("tenant", "5"),
    )
