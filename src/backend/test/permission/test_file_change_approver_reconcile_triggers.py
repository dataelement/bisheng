from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from bisheng.common.errcode.permission import PermissionTupleWriteError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem, AuthorizeRequest


def _user(*, user_id: int = 1, tenant_id: int = 7):
    return SimpleNamespace(
        user_id=user_id,
        user_name="operator",
        tenant_id=tenant_id,
        is_admin=lambda: True,
    )


async def test_dispatcher_deduplicates_spaces_and_carries_explicit_tenant_header():
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        dispatch_file_change_approver_reconcile_for_spaces,
    )

    dispatch = Mock()
    await dispatch_file_change_approver_reconcile_for_spaces(
        space_ids=[12, 11, 12],
        tenant_id=7,
        dispatch=dispatch,
    )

    assert dispatch.call_count == 2
    assert dispatch.call_args_list[0].args == (11,)
    assert dispatch.call_args_list[0].kwargs == {"tenant_id": 7}
    assert dispatch.call_args_list[1].args == (12,)
    assert dispatch.call_args_list[1].kwargs == {"tenant_id": 7}


async def test_dispatcher_ignores_unrelated_resource_or_relation():
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        dispatch_file_change_approver_reconcile_for_permission_change,
    )

    dispatch = Mock()
    viewer = AuthorizeGrantItem(subject_type="user", subject_id=2, relation="viewer")
    manager = AuthorizeGrantItem(subject_type="user", subject_id=2, relation="manager")

    await dispatch_file_change_approver_reconcile_for_permission_change(
        resource_type="knowledge_space",
        resource_id="11",
        grants=[viewer],
        tenant_id=7,
        dispatch=dispatch,
    )
    await dispatch_file_change_approver_reconcile_for_permission_change(
        resource_type="workflow",
        resource_id="11",
        grants=[manager],
        tenant_id=7,
        dispatch=dispatch,
    )

    dispatch.assert_not_called()


async def test_dispatcher_missing_tenant_fails_closed_without_root_fallback():
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        dispatch_file_change_approver_reconcile_for_spaces,
    )

    dispatch = Mock()
    await dispatch_file_change_approver_reconcile_for_spaces(
        space_ids=[11],
        tenant_id=None,
        dispatch=dispatch,
    )

    dispatch.assert_not_called()


async def test_dispatcher_broker_failure_is_best_effort():
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        dispatch_file_change_approver_reconcile_for_spaces,
    )

    dispatch = Mock(side_effect=RuntimeError("broker unavailable"))
    await dispatch_file_change_approver_reconcile_for_spaces(
        space_ids=[11],
        tenant_id=7,
        dispatch=dispatch,
    )

    dispatch.assert_called_once_with(11, tenant_id=7)


async def test_default_dispatcher_uses_celery_header_not_task_kwargs():
    from bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher import (
        dispatch_file_change_approver_reconcile_for_spaces,
    )
    from bisheng.worker.approval.file_change_tasks import reconcile_space_file_change_approvers

    with patch.object(reconcile_space_file_change_approvers, "apply_async") as apply_async:
        await dispatch_file_change_approver_reconcile_for_spaces(
            space_ids=[11],
            tenant_id=7,
        )

    apply_async.assert_called_once_with(
        args=[11],
        headers={"tenant_id": 7},
    )


async def test_permission_service_dispatches_after_authoritative_fga_write():
    from bisheng.permission.domain.services.permission_service import PermissionService

    events: list[str] = []
    grant = AuthorizeGrantItem(subject_type="user", subject_id=2, relation="manager")
    batch_write = AsyncMock(side_effect=lambda *_args, **_kwargs: events.append("fga"))
    reconcile = AsyncMock(side_effect=lambda **_kwargs: events.append("dispatch"))
    with (
        patch.object(PermissionService, "_legacy_alias_object_types", new=AsyncMock(return_value=[])),
        patch.object(PermissionService, "_expand_subject", new=AsyncMock(return_value=["user:2"])),
        patch.object(PermissionService, "_affected_user_ids_for_subject", new=AsyncMock(return_value=set())),
        patch.object(PermissionService, "batch_write_tuples", new=batch_write),
        patch.object(PermissionService, "resolve_resource_tenant_id", new=AsyncMock(return_value=7)),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_permission_change",
            new=reconcile,
        ),
    ):
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id="11",
            grants=[grant],
            enforce_fga_success=True,
        )

    assert events == ["fga", "dispatch"]
    reconcile.assert_awaited_once_with(
        resource_type="knowledge_space",
        resource_id="11",
        grants=[grant],
        revokes=(),
        tenant_id=7,
    )


async def test_permission_service_fga_failure_does_not_dispatch():
    from bisheng.permission.domain.services.permission_service import PermissionService

    grant = AuthorizeGrantItem(subject_type="user", subject_id=2, relation="manager")
    reconcile = AsyncMock()
    with (
        patch.object(PermissionService, "_legacy_alias_object_types", new=AsyncMock(return_value=[])),
        patch.object(PermissionService, "_expand_subject", new=AsyncMock(return_value=["user:2"])),
        patch.object(PermissionService, "_affected_user_ids_for_subject", new=AsyncMock(return_value=set())),
        patch.object(
            PermissionService,
            "batch_write_tuples",
            new=AsyncMock(side_effect=RuntimeError("FGA write failed")),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_permission_change",
            new=reconcile,
        ),
        pytest.raises(RuntimeError, match="FGA write failed"),
    ):
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id="11",
            grants=[grant],
            enforce_fga_success=True,
        )

    reconcile.assert_not_awaited()


async def test_generic_resource_authorize_uses_common_fga_success_boundary():
    from bisheng.permission.domain.services.resource_authorization_service import ResourceAuthorizationService

    events: list[str] = []
    authorize = AsyncMock(side_effect=lambda **_kwargs: events.append("fga"))
    mutation = AsyncMock(side_effect=lambda _mutator: events.append("bindings"))
    service = ResourceAuthorizationService(
        binding_mutation_service=SimpleNamespace(mutate=mutation),
    )
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type="department",
                subject_id=3,
                relation="manager",
                model_id="manager",
            )
        ]
    )
    with (
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.grant_subject_query_service."
            "GrantSubjectQueryService.validate_resource_grants",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=authorize,
        ),
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
    ):
        await service.authorize("knowledge_space", "11", request, _user())

    assert events == ["fga", "bindings"]
    assert authorize.await_args.kwargs["enforce_fga_success"] is True


async def test_generic_binding_failure_still_dispatches_committed_fga_change():
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.permission.domain.services.resource_authorization_service import ResourceAuthorizationService

    reconcile = AsyncMock()
    service = ResourceAuthorizationService(
        binding_mutation_service=SimpleNamespace(
            mutate=AsyncMock(side_effect=RuntimeError("binding write failed")),
        ),
    )
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type="department",
                subject_id=3,
                relation="manager",
                model_id="manager",
            )
        ]
    )
    with (
        patch.object(PermissionService, "get_resource_permissions", new=AsyncMock(return_value=[])),
        patch.object(PermissionService, "_legacy_alias_object_types", new=AsyncMock(return_value=[])),
        patch.object(PermissionService, "_expand_subject", new=AsyncMock(return_value=["department:3#member"])),
        patch.object(PermissionService, "_affected_user_ids_for_subject", new=AsyncMock(return_value=set())),
        patch.object(PermissionService, "batch_write_tuples", new=AsyncMock()),
        patch.object(PermissionService, "resolve_resource_tenant_id", new=AsyncMock(return_value=7)),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.grant_subject_query_service."
            "GrantSubjectQueryService.validate_resource_grants",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_permission_change",
            new=reconcile,
        ),
        pytest.raises(PermissionTupleWriteError),
    ):
        await service.authorize("knowledge_space", "11", request, _user())

    reconcile.assert_awaited_once()


async def test_direct_space_manager_sync_dispatches_before_binding_save():
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    events: list[str] = []
    bindings = [
        {
            "resource_type": "knowledge_space",
            "resource_id": "11",
            "subject_type": "user",
            "subject_id": 2,
            "relation": "viewer",
        }
    ]
    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=AsyncMock(side_effect=lambda **_kwargs: events.append("fga")),
        ) as authorize,
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.resolve_resource_tenant_id",
            new=AsyncMock(return_value=7),
        ),
        patch(
            "bisheng.permission.domain.services.relation_model_store.get_bindings",
            new=AsyncMock(return_value=bindings),
        ),
        patch(
            "bisheng.permission.domain.services.relation_model_store.save_bindings",
            new=AsyncMock(side_effect=lambda _bindings: events.append("bindings")),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_permission_change",
            new=AsyncMock(side_effect=lambda **_kwargs: events.append("dispatch")),
        ) as reconcile,
    ):
        await KnowledgeSpaceService.sync_direct_space_user_permissions(
            11,
            2,
            UserRoleEnum.ADMIN,
            is_active=True,
        )

    assert events == ["fga", "dispatch", "bindings"]
    assert authorize.await_args.kwargs["dispatch_file_change_approver_reconcile"] is False
    assert reconcile.await_args.kwargs["tenant_id"] == 7


async def test_direct_space_viewer_sync_does_not_dispatch():
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.permission.domain.services.relation_model_store.get_bindings",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.relation_model_store.save_bindings",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_permission_change",
            new=AsyncMock(),
        ) as reconcile,
    ):
        await KnowledgeSpaceService.sync_direct_space_user_permissions(
            11,
            2,
            UserRoleEnum.MEMBER,
            is_active=True,
        )

    reconcile.assert_not_awaited()


async def test_department_admin_sync_dispatches_affected_space_once():
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_space_id_by_department_id",
            new=AsyncMock(return_value=11),
        ),
        patch.object(DepartmentKnowledgeSpaceService, "_sync_added_admin", new=AsyncMock()),
        patch.object(DepartmentKnowledgeSpaceService, "_sync_removed_admin", new=AsyncMock()),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_spaces",
            new=AsyncMock(),
        ) as reconcile,
    ):
        await DepartmentKnowledgeSpaceService.sync_department_admin_memberships(
            request=None,
            login_user=_user(),
            department_id=5,
            added_user_ids=[2, 3, 2],
            removed_user_ids=[4, 4],
        )

    reconcile.assert_awaited_once_with(space_ids=[11], tenant_id=7)


async def test_department_admin_sync_does_not_dispatch_when_no_fga_write_succeeds():
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_space_id_by_department_id",
            new=AsyncMock(return_value=11),
        ),
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_added_admin",
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_removed_admin",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_spaces",
            new=AsyncMock(),
        ) as reconcile,
    ):
        await DepartmentKnowledgeSpaceService.sync_department_admin_memberships(
            request=None,
            login_user=_user(),
            department_id=5,
            added_user_ids=[2],
            removed_user_ids=[3],
        )

    reconcile.assert_not_awaited()


async def test_sso_department_admin_cleanup_dispatches_affected_space_once():
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_space_id_by_department_id",
            new=AsyncMock(return_value=11),
        ),
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_removed_admin",
            new=AsyncMock(),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.resolve_resource_tenant_id",
            new=AsyncMock(return_value=7),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_spaces",
            new=AsyncMock(),
        ) as reconcile,
    ):
        await DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=5,
            user_ids=[2, 3, 2],
        )

    reconcile.assert_awaited_once_with(space_ids=[11], tenant_id=7)


async def test_sso_department_admin_cleanup_does_not_dispatch_when_fga_write_fails():
    from bisheng.knowledge.domain.services.department_knowledge_space_service import (
        DepartmentKnowledgeSpaceService,
    )

    with (
        patch(
            "bisheng.knowledge.domain.services.department_knowledge_space_service."
            "DepartmentKnowledgeSpaceDao.aget_space_id_by_department_id",
            new=AsyncMock(return_value=11),
        ),
        patch.object(
            DepartmentKnowledgeSpaceService,
            "_sync_removed_admin",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_spaces",
            new=AsyncMock(),
        ) as reconcile,
    ):
        await DepartmentKnowledgeSpaceService.cleanup_removed_department_admins(
            department_id=5,
            user_ids=[2],
        )

    reconcile.assert_not_awaited()


async def test_bulk_owner_transfer_dispatches_each_affected_space_once():
    from bisheng.tenant.domain.services.resource_ownership_service import (
        ResourceOwnershipService,
        ResourceRow,
    )

    resources = [
        ResourceRow("knowledge_space", 11, 1, 7),
        ResourceRow("knowledge_space", 12, 1, 7),
        ResourceRow("workflow", "flow-1", 1, 7),
    ]
    with (
        patch.object(ResourceOwnershipService, "_check_receiver_visible", new=AsyncMock()),
        patch.object(ResourceOwnershipService, "_resolve_resources", new=AsyncMock(return_value=resources)),
        patch.object(ResourceOwnershipService, "_bulk_update_user_ids", new=AsyncMock()),
        patch.object(ResourceOwnershipService, "_flip_fga_owner_tuples", new=AsyncMock()),
        patch.object(ResourceOwnershipService, "_safe_audit", new=AsyncMock()),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_spaces",
            new=AsyncMock(),
        ) as reconcile,
    ):
        result = await ResourceOwnershipService.transfer_owner(
            tenant_id=7,
            from_user_id=1,
            to_user_id=2,
            resource_types=["knowledge_space", "workflow"],
            operator=_user(user_id=1),
        )

    assert result["transferred_count"] == 3
    reconcile.assert_awaited_once_with(space_ids=[11, 12], tenant_id=7)


async def test_bulk_owner_transfer_fga_failure_does_not_dispatch():
    from bisheng.common.errcode.resource_owner_transfer import ResourceTransferTxFailedError
    from bisheng.tenant.domain.services.resource_ownership_service import (
        ResourceOwnershipService,
        ResourceRow,
    )

    resources = [ResourceRow("knowledge_space", 11, 1, 7)]
    with (
        patch.object(ResourceOwnershipService, "_check_receiver_visible", new=AsyncMock()),
        patch.object(ResourceOwnershipService, "_resolve_resources", new=AsyncMock(return_value=resources)),
        patch.object(ResourceOwnershipService, "_bulk_update_user_ids", new=AsyncMock()),
        patch.object(
            ResourceOwnershipService,
            "_flip_fga_owner_tuples",
            new=AsyncMock(side_effect=RuntimeError("FGA write failed")),
        ),
        patch(
            "bisheng.permission.domain.services.file_change_approver_reconcile_dispatcher."
            "dispatch_file_change_approver_reconcile_for_spaces",
            new=AsyncMock(),
        ) as reconcile,
        pytest.raises(ResourceTransferTxFailedError),
    ):
        await ResourceOwnershipService.transfer_owner(
            tenant_id=7,
            from_user_id=1,
            to_user_id=2,
            resource_types=["knowledge_space"],
            operator=_user(user_id=1),
        )

    reconcile.assert_not_awaited()


async def test_bulk_owner_fga_write_requires_authoritative_success():
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.tenant.domain.services.resource_ownership_service import (
        ResourceOwnershipService,
        ResourceRow,
    )

    batch_write = AsyncMock()
    with patch.object(PermissionService, "batch_write_tuples", new=batch_write):
        await ResourceOwnershipService._flip_fga_owner_tuples(
            [ResourceRow("knowledge_space", 11, 1, 7)],
            from_user_id=1,
            to_user_id=2,
        )

    assert batch_write.await_args.kwargs == {
        "crash_safe": True,
        "raise_on_failure": True,
        "stop_on_failure": True,
    }
