from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionTupleWriteError,
)
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRequest,
)
from bisheng.permission.domain.services.resource_authorization_service import (
    ResourceAuthorizationService,
)


def _user(user_id: int = 1, admin: bool = True):
    return SimpleNamespace(user_id=user_id, user_name="operator", is_admin=lambda: admin)


async def test_authorize_success_returns_none_and_persists_binding():
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=2,
                relation="viewer",
                model_id="custom_viewer",
            )
        ]
    )
    service = ResourceAuthorizationService()

    with (
        patch.object(service, "get_bindings", AsyncMock(return_value=[])),
        patch.object(service, "save_bindings", AsyncMock()) as save_bindings,
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await service.authorize("workflow", "1", request, _user())

    assert result is None
    authorize.assert_awaited_once()
    save_bindings.assert_awaited_once()
    assert save_bindings.await_args.args[0][0]["model_id"] == "custom_viewer"


async def test_authorize_rejects_non_user_owner():
    service = ResourceAuthorizationService()
    request = AuthorizeRequest(grants=[AuthorizeGrantItem(subject_type="department", subject_id=3, relation="owner")])

    with pytest.raises(PermissionDeniedError):
        await service.authorize("knowledge_space", "1", request, _user())


async def test_authorize_rejects_channel():
    service = ResourceAuthorizationService()

    with pytest.raises(PermissionDeniedError):
        await service.authorize("channel", "channel-1", AuthorizeRequest(), _user())


async def test_tuple_write_failure_is_normalized():
    service = ResourceAuthorizationService()
    request = AuthorizeRequest(grants=[AuthorizeGrantItem(subject_type="user", subject_id=2, relation="viewer")])

    with (
        patch.object(service, "get_bindings", AsyncMock(return_value=[])),
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fga unavailable"),
        ),
    ):
        with pytest.raises(PermissionTupleWriteError) as exc_info:
            await service.authorize("workflow", "1", request, _user())

    assert "fga unavailable" in str(exc_info.value)


async def test_tuple_write_business_error_is_preserved():
    service = ResourceAuthorizationService()
    request = AuthorizeRequest(grants=[AuthorizeGrantItem(subject_type="user", subject_id=2, relation="viewer")])
    business_error = PermissionDeniedError(msg="grant denied")

    with (
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
            side_effect=business_error,
        ),
    ):
        with pytest.raises(PermissionDeniedError) as exc_info:
            await service.authorize("workflow", "1", request, _user())

    assert exc_info.value is business_error


@pytest.mark.parametrize("failure_stage", ["read", "write"])
async def test_relation_model_binding_failure_is_normalized(failure_stage: str):
    service = ResourceAuthorizationService()
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=2,
                relation="viewer",
                model_id="viewer",
            )
        ]
    )
    get_bindings = AsyncMock(
        side_effect=RuntimeError("binding read failed") if failure_stage == "read" else None,
        return_value=[],
    )
    save_bindings = AsyncMock(
        side_effect=RuntimeError("binding write failed") if failure_stage == "write" else None,
    )

    with (
        patch.object(service, "get_bindings", get_bindings),
        patch.object(service, "save_bindings", save_bindings),
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ),
    ):
        with pytest.raises(PermissionTupleWriteError) as exc_info:
            await service.authorize("workflow", "1", request, _user())

    assert "binding" in str(exc_info.value)


async def test_non_admin_requires_management_permission():
    service = ResourceAuthorizationService()
    request = AuthorizeRequest(grants=[AuthorizeGrantItem(subject_type="user", subject_id=2, relation="viewer")])

    with patch(
        "bisheng.permission.domain.services.fine_grained_permission_service."
        "FineGrainedPermissionService.get_effective_permission_ids_async",
        new_callable=AsyncMock,
        return_value=set(),
    ):
        with pytest.raises(PermissionDeniedError):
            await service.authorize("workflow", "1", request, _user(admin=False))


async def test_knowledge_authorize_revalidates_subject_tenant_before_tuple_write():
    grant_subject_query_service = SimpleNamespace(
        validate_resource_grants=AsyncMock(side_effect=PermissionDeniedError())
    )
    service = ResourceAuthorizationService(grant_subject_query_service=grant_subject_query_service)
    request = AuthorizeRequest(grants=[AuthorizeGrantItem(subject_type="user", subject_id=999, relation="viewer")])

    with (
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
    ):
        with pytest.raises(PermissionDeniedError):
            await service.authorize("knowledge_space", "11", request, _user())

    grant_subject_query_service.validate_resource_grants.assert_awaited_once_with(
        resource_type="knowledge_space",
        resource_id="11",
        grants=request.grants,
    )
    authorize.assert_not_awaited()


async def test_default_service_reads_relation_models_and_bindings_from_domain_store():
    service = ResourceAuthorizationService()
    models = [{"id": "viewer", "name": "Viewer", "relation": "viewer", "is_system": True}]
    bindings = [{"key": "workflow:1:user:2:viewer:-"}]

    with (
        patch(
            "bisheng.permission.domain.services.resource_authorization_service.get_relation_models",
            new=AsyncMock(return_value=models),
        ) as read_models,
        patch(
            "bisheng.permission.domain.services.resource_authorization_service.get_bindings",
            new=AsyncMock(return_value=bindings),
        ) as read_bindings,
    ):
        assert await service.get_relation_models() == models
        assert await service.get_bindings() == bindings

    read_models.assert_awaited_once()
    read_bindings.assert_awaited_once()
