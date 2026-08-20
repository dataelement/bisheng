from contextlib import asynccontextmanager
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


class _BindingTransaction:
    def __init__(self, events):
        self.events = events
        self.bindings = []
        self.snapshot = []

    async def commit(self, bindings):
        self.events.append("binding_commit")
        self.bindings = bindings

    async def restore(self):
        self.events.append("binding_restore")


class _BindingMutationService:
    def __init__(self, events):
        self.transaction_value = _BindingTransaction(events)

    @asynccontextmanager
    async def transaction(self):
        yield self.transaction_value


def _user(user_id: int = 1, admin: bool = True):
    return SimpleNamespace(user_id=user_id, user_name="operator", tenant_id=1, is_admin=lambda: admin)


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
    service = ResourceAuthorizationService(
        grant_subject_query_service=grant_subject_query_service,
        invite_service=SimpleNamespace(ensure_scenario_available=AsyncMock()),
    )
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
        result = await service.authorize("knowledge_space", "11", request, _user())

    grant_subject_query_service.validate_resource_grants.assert_awaited_once_with(
        resource_type="knowledge_space",
        resource_id="11",
        grants=[request.grants[0]],
    )
    authorize.assert_not_awaited()
    assert result.failed_count == 1
    assert result.results[0].subject_id == 999


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


async def test_new_knowledge_space_user_becomes_invite():
    invite_service = SimpleNamespace(
        ensure_scenario_available=AsyncMock(),
        request_invite=AsyncMock(
            return_value={
                "outcome": "invite_created",
                "subject_id": 42,
                "relation": "viewer",
                "model_id": "viewer",
                "approval_instance_id": 88,
            }
        ),
    )
    service = ResourceAuthorizationService(
        invite_service=invite_service,
        grant_subject_query_service=SimpleNamespace(validate_resource_grants=AsyncMock()),
        get_relation_models=AsyncMock(
            return_value=[{"id": "viewer", "name": "Viewer", "relation": "viewer", "is_system": True}]
        ),
    )
    service._resolve_invite_context = AsyncMock(return_value=("Space", "Target", None))
    request = AuthorizeRequest(
        grants=[AuthorizeGrantItem(subject_type="user", subject_id=42, relation="viewer", model_id="viewer")]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=3),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=AsyncMock(),
        ) as direct_authorize,
    ):
        result = await service.authorize("knowledge_space", "11", request, _user())

    invite_service.ensure_scenario_available.assert_awaited_once_with(tenant_id=3)
    invite_service.request_invite.assert_awaited_once()
    assert invite_service.request_invite.await_args.kwargs["tenant_id"] == 3
    direct_authorize.assert_not_awaited()
    assert result.invite_created_count == 1
    assert result.results[0].approval_instance_id == 88


async def test_disabled_scenario_degrades_to_direct_authorization():
    """审批场景关闭时，新增个人用户授权降级为直接授权，不报错、不创建本人确认审批。"""
    from bisheng.common.errcode.approval import ApprovalScenarioDisabledError

    invite_service = SimpleNamespace(
        ensure_scenario_available=AsyncMock(side_effect=ApprovalScenarioDisabledError()),
        request_invite=AsyncMock(),
    )
    service = ResourceAuthorizationService(invite_service=invite_service)
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
            AuthorizeGrantItem(subject_type="user", subject_id=42, relation="viewer"),
        ]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=1),
        ),
        patch.object(service, "_authorize_direct", new=AsyncMock()) as direct_authorize,
    ):
        result = await service.authorize("knowledge_space", "11", request, _user())

    direct_authorize.assert_awaited_once()
    direct_request = direct_authorize.await_args.args[2]
    assert direct_request.grants == request.grants
    invite_service.request_invite.assert_not_awaited()
    assert result.direct_applied_count == 2
    assert result.invite_created_count == 0


async def test_mixed_authorization_keeps_invalid_invite_failure_per_item():
    events: list[str] = []

    @asynccontextmanager
    async def scenario_guard(*, tenant_id: int):
        assert tenant_id == 3
        events.append("guard_enter")
        yield
        events.append("guard_exit")

    async def validate_resource_grants(*, grants, **_kwargs):
        if int(grants[0].subject_id) == 99:
            raise PermissionDeniedError()

    async def request_invite(**kwargs):
        events.append(f"invite:{kwargs['target_user_id']}")
        return {
            "outcome": "invite_created",
            "subject_id": 42,
            "relation": "viewer",
            "model_id": "viewer",
            "approval_instance_id": 88,
        }

    invite_service = SimpleNamespace(
        scenario_guard=scenario_guard,
        request_invite=AsyncMock(side_effect=request_invite),
    )
    service = ResourceAuthorizationService(
        invite_service=invite_service,
        grant_subject_query_service=SimpleNamespace(
            validate_resource_grants=AsyncMock(side_effect=validate_resource_grants),
        ),
    )
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
            AuthorizeGrantItem(subject_type="user", subject_id=42, relation="viewer"),
            AuthorizeGrantItem(subject_type="user", subject_id=99, relation="viewer"),
        ]
    )

    async def apply_direct(*_args, **_kwargs):
        events.append("direct")

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService._resolve_resource_tenant",
            new=AsyncMock(return_value=3),
        ),
        patch.object(service, "_authorize_direct", side_effect=apply_direct),
        patch.object(
            service,
            "_validate_department_space_grants",
            new=AsyncMock(),
        ),
        patch.object(
            service,
            "_resolve_invite_context",
            new=AsyncMock(return_value=("docs", "target", None)),
        ),
        patch.object(
            service,
            "_resolve_role_snapshot",
            new=AsyncMock(return_value=("viewer", {"id": "viewer"})),
        ),
    ):
        result = await service.authorize("knowledge_space", "11", request, _user())

    assert events == ["guard_enter", "direct", "invite:42", "guard_exit"]
    assert result.direct_applied_count == 1
    assert result.invite_created_count == 1
    assert result.failed_count == 1
    assert result.results[-1].subject_id == 99
    assert result.results[-1].outcome == "failed"


async def test_department_and_existing_explicit_user_stay_direct():
    existing = SimpleNamespace(subject_type="user", subject_id=42, relation="viewer")
    invite_service = SimpleNamespace(ensure_scenario_available=AsyncMock(), request_invite=AsyncMock())
    service = ResourceAuthorizationService(invite_service=invite_service)
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(subject_type="department", subject_id=9, relation="viewer"),
            AuthorizeGrantItem(subject_type="user", subject_id=42, relation="editor"),
        ]
    )

    with (
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[existing]),
        ),
        patch.object(service, "_authorize_direct", AsyncMock()) as direct,
    ):
        result = await service.authorize("knowledge_space", "11", request, _user())

    invite_service.ensure_scenario_available.assert_not_awaited()
    invite_service.request_invite.assert_not_awaited()
    assert len(direct.await_args.args[2].grants) == 2
    assert result.direct_applied_count == 2


async def test_list_merges_pending_instances_and_active_wins():
    invite_service = SimpleNamespace(
        list_pending_invite_items=AsyncMock(
            return_value=[
                SimpleNamespace(
                    business_request_id=5,
                    approval_instance_id=5,
                    subject_type="user",
                    subject_id=42,
                    subject_name="Pending",
                    relation="viewer",
                    model_id="viewer",
                    model_name="Viewer",
                    authorization_status="pending",
                ),
                SimpleNamespace(
                    business_request_id=6,
                    approval_instance_id=6,
                    subject_type="user",
                    subject_id=7,
                    relation="viewer",
                    authorization_status="pending",
                ),
            ]
        )
    )
    service = ResourceAuthorizationService(invite_service=invite_service)
    active = [SimpleNamespace(subject_type="user", subject_id=7, relation="editor", authorization_status="active")]

    result = await service.list_pending_permissions(
        tenant_id=3,
        resource_type="knowledge_space",
        resource_id="11",
        active_permissions=active,
    )

    assert len(result) == 2
    assert result[1].subject_id == 42
    assert result[1].authorization_status == "pending"
    assert result[1].approval_instance_id == 5


async def test_confirmed_grant_precommits_binding_and_uses_caller_recovery():
    role = {
        "id": "viewer",
        "name": "Viewer",
        "relation": "viewer",
        "permissions": [],
        "permissions_explicit": False,
        "is_system": True,
        "grant_tier": "usage",
    }
    events = []
    service = ResourceAuthorizationService(
        get_relation_models=AsyncMock(return_value=[role]),
        grant_subject_query_service=SimpleNamespace(validate_resource_grants=AsyncMock()),
        binding_mutation_service=_BindingMutationService(events),
    )
    normalized_role = role
    fingerprint = service._role_snapshot_fingerprint(normalized_role)
    active_permissions = []

    async def authorize(*args, **kwargs):
        events.append("fga_write")
        assert kwargs["recovery_owner"] == "caller"
        grant = kwargs["grants"][0]
        active_permissions.append(
            SimpleNamespace(
                subject_type=grant.subject_type,
                subject_id=grant.subject_id,
                relation=grant.relation,
            )
        )

    async def resolve_permissions(login_user, *_args, **_kwargs):
        assert login_user.user_role == [1, 9]
        assert login_user.is_admin()
        return {
            "manage_space_relation",
            "view_space",
            "view_folder",
            "view_file",
            "download_folder",
            "download_file",
        }

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=SimpleNamespace(id=11)),
        ),
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.user.domain.models.user.UserDao.aget_user",
            new=AsyncMock(return_value=SimpleNamespace(user_name="Inviter", delete=0)),
        ),
        patch(
            "bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles",
            new=AsyncMock(
                return_value=[SimpleNamespace(role_id=1), SimpleNamespace(role_id=9)],
            ),
        ),
        patch(
            "bisheng.permission.domain.services.fine_grained_permission_service."
            "FineGrainedPermissionService.get_effective_permission_ids_async",
            new=AsyncMock(side_effect=resolve_permissions),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new=AsyncMock(side_effect=lambda *_args, **_kwargs: list(active_permissions)),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new=AsyncMock(side_effect=authorize),
        ),
    ):
        from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

        tenant_token = set_current_tenant_id(1)
        try:
            await service.apply_confirmed_personal_user_grant(
                tenant_id=1,
                resource_id="11",
                inviter_user_id=7,
                target_user_id=42,
                relation="viewer",
                model_id="viewer",
                role_snapshot=normalized_role,
                role_fingerprint=fingerprint,
                include_children=False,
                approval_instance_id=88,
            )
        finally:
            current_tenant_id.reset(tenant_token)

    assert events == ["fga_write", "binding_commit"]


async def test_confirmed_grant_rejects_private_space():
    """Accepting a stale share invite must fail once the space is PRIVATE.

    Regression for the bug where a knowledge space shared to a user, then
    converted to private, could still be joined when the user accepted the
    pending invitation. The accept-side guard reads auth_type and refuses.
    """
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum

    role = {
        "id": "viewer",
        "name": "Viewer",
        "relation": "viewer",
        "permissions": [],
        "permissions_explicit": False,
        "is_system": True,
        "grant_tier": "usage",
    }
    service = ResourceAuthorizationService(get_relation_models=AsyncMock(return_value=[role]))
    fingerprint = service._role_snapshot_fingerprint(role)

    with (
        patch(
            "bisheng.knowledge.domain.models.knowledge.KnowledgeDao.aquery_by_id",
            new=AsyncMock(
                return_value=SimpleNamespace(id=11, tenant_id=1, auth_type=AuthTypeEnum.PRIVATE),
            ),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
    ):
        from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id

        tenant_token = set_current_tenant_id(1)
        try:
            with pytest.raises(PermissionDeniedError):
                await service.apply_confirmed_personal_user_grant(
                    tenant_id=1,
                    resource_id="11",
                    inviter_user_id=7,
                    target_user_id=42,
                    relation="viewer",
                    model_id="viewer",
                    role_snapshot=role,
                    role_fingerprint=fingerprint,
                    include_children=False,
                    approval_instance_id=88,
                )
        finally:
            current_tenant_id.reset(tenant_token)

    authorize.assert_not_awaited()
