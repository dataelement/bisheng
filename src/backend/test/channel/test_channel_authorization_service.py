from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizeRequest,
    ChannelAuthorizeResponse,
    ChannelGrantItem,
    ChannelRevokeItem,
)
from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
    ChannelAuthorizationSyncError,
    _canonical_role_snapshot,
)
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import ChannelRelationEnum
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.core.openfga.exceptions import FGAWriteError


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(1)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


class _User:
    user_id = 7
    tenant_id = 1

    def is_admin(self):
        return False


class _ChannelRepo:
    async def find_by_id(self, channel_id: str):
        return type("Channel", (), {"id": channel_id, "tenant_id": 1})()


class _MemberRepo:
    def __init__(self, relation: ChannelRelationEnum):
        self.relation = relation
        self.deleted_binding_keys = []

    async def get_effective_channel_relation(self, channel_id: str, user_id: int):
        return self.relation

    async def delete_channel_membership_source(self, channel_id: str, grant_binding_key: str):
        self.deleted_binding_keys.append((channel_id, grant_binding_key))
        return 1


class _SyncService:
    def __init__(self):
        self.grants = []
        self.revokes = []

    async def sync_grant(self, **kwargs):
        self.grants.append(kwargs)
        return [kwargs["grant"].subject_id]

    async def sync_revoke(self, **kwargs):
        self.revokes.append(kwargs)
        return 0


class _InviteService:
    def __init__(self):
        self.ensure_scenario_available = AsyncMock()
        self.request_invite = AsyncMock(
            return_value={
                "operation": "grant",
                "subject_type": "user",
                "subject_id": 11,
                "relation": "viewer",
                "model_id": "viewer",
                "outcome": "invite_created",
                "approval_instance_id": 1201,
                "error_code": None,
                "error_message": None,
            }
        )
        self.list_pending_invites = AsyncMock(return_value=[])


class _BindingMutationService:
    def __init__(self, bindings=None):
        self.bindings = list(bindings or [])

    async def mutate(self, mutator):
        result = mutator(self.bindings)
        if hasattr(result, "__await__"):
            result = await result
        self.bindings = result
        return result

    @asynccontextmanager
    async def transaction(self):
        service = self

        class _Transaction:
            snapshot = list(service.bindings)
            bindings = list(service.bindings)

            def ensure_owned(self):
                return None

            async def commit(self, bindings):
                self.bindings = list(bindings)
                service.bindings = list(bindings)

            async def restore(self):
                self.bindings = list(self.snapshot)
                service.bindings = list(self.snapshot)

        yield _Transaction()


def _service(actor_relation: ChannelRelationEnum, sync_service=None) -> ChannelAuthorizationService:
    invite_service = _InviteService()
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepo(),
        space_channel_member_repository=_MemberRepo(actor_relation),
        membership_sync_service=sync_service or _SyncService(),
        invite_application_service=invite_service,
        relation_binding_mutation_service=_BindingMutationService(),
    )
    service._validate_subjects_belong_to_channel_tenant = AsyncMock(return_value=None)
    service._get_bindings = AsyncMock(return_value=[])
    service._save_bindings = AsyncMock()
    service._active_explicit_user_ids = AsyncMock(return_value={11, 12, 13, 14, 99})
    service._target_user_name = AsyncMock(return_value="Alice")
    service._get_relation_models = AsyncMock(return_value=ChannelAuthorizationService._default_relation_models())
    return service


@pytest.mark.asyncio
async def test_channel_new_user_becomes_invite():
    service = _service(ChannelRelationEnum.OWNER)
    service._active_explicit_user_ids.return_value = set()
    service._users_belong_to_tenant = AsyncMock(return_value=True)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(
                subject_type="user",
                subject_id=11,
                relation=ChannelRelationEnum.VIEWER,
                model_id="viewer",
            )
        ]
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.dispatch_after_authorize",
            new=AsyncMock(),
        ),
    ):
        result = await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_not_awaited()
    service._invite_application_service.ensure_scenario_available.assert_awaited_once_with(tenant_id=1)
    invite_kwargs = service._invite_application_service.request_invite.await_args.kwargs
    assert invite_kwargs["resource_type"] == "channel"
    assert invite_kwargs["resource_id"] == "channel-1"
    assert invite_kwargs["target_user_id"] == 11
    assert result.invite_created_count == 1
    assert result.direct_applied_count == 0
    assert result.results[0].outcome == "invite_created"


@pytest.mark.asyncio
async def test_channel_direct_operations_unchanged():
    service = _service(ChannelRelationEnum.OWNER)
    service._active_explicit_user_ids.return_value = {11}
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(
                subject_type="user",
                subject_id=11,
                relation=ChannelRelationEnum.MANAGER,
            ),
            ChannelGrantItem(
                subject_type="department",
                subject_id=21,
                relation=ChannelRelationEnum.VIEWER,
            ),
        ],
        revokes=[
            ChannelRevokeItem(
                subject_type="user_group",
                subject_id=31,
                relation=ChannelRelationEnum.VIEWER,
            )
        ],
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.dispatch_after_authorize",
            new=AsyncMock(),
        ),
    ):
        result = await service.authorize_channel("channel-1", request, _User())

    service._invite_application_service.ensure_scenario_available.assert_not_awaited()
    service._invite_application_service.request_invite.assert_not_awaited()
    assert len(mock_authorize.await_args.kwargs["grants"]) == 2
    assert len(mock_authorize.await_args.kwargs["revokes"]) == 1
    assert result.direct_applied_count == 3
    assert {item.outcome for item in result.results} == {"applied"}


@pytest.mark.asyncio
async def test_channel_disabled_scenario_zero_side_effect():
    service = _service(ChannelRelationEnum.OWNER)
    service._active_explicit_user_ids.return_value = set()
    service._invite_application_service.ensure_scenario_available.side_effect = ApprovalScenarioDisabledError(
        msg="个人用户邀请确认场景未启用，无法新增个人用户权限"  # noqa: RUF001
    )
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(
                subject_type="department",
                subject_id=21,
                relation=ChannelRelationEnum.VIEWER,
            ),
            ChannelGrantItem(
                subject_type="user",
                subject_id=11,
                relation=ChannelRelationEnum.VIEWER,
            ),
        ]
    )

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
        new_callable=AsyncMock,
    ) as mock_authorize:
        with pytest.raises(ApprovalScenarioDisabledError):
            await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_not_awaited()
    service._invite_application_service.request_invite.assert_not_awaited()
    service._save_bindings.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_pending_projection():
    service = _service(ChannelRelationEnum.OWNER)
    service._require_manage_access = AsyncMock(return_value=ChannelRelationEnum.OWNER)
    service._get_relation_models = AsyncMock(
        return_value=[
            {
                "id": "viewer",
                "name": "可查看",
                "relation": "viewer",
                "grant_tier": "usage",
                "permissions": [],
            }
        ]
    )
    service._invite_application_service.list_pending_invites.return_value = [
        SimpleNamespace(
            id=1201,
            approval_instance_id=1201,
            target_user_id=11,
            target_user_name="Alice",
            relation="viewer",
            model_id="viewer",
            include_children=False,
        )
    ]

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.get_resource_permissions",
        new=AsyncMock(return_value=[]),
    ):
        entries = await service.list_permissions("channel-1", _User())

    assert len(entries) == 1
    assert entries[0].subject_id == 11
    assert entries[0].authorization_status == "pending"
    assert entries[0].approval_instance_id == 1201


def test_channel_counts_compatible():
    response = ChannelAuthorizeResponse()

    assert response.synced_user_count == 0
    assert response.affected_member_count == 0
    assert response.direct_applied_count == 0
    assert response.results == []


@pytest.mark.asyncio
async def test_channel_confirmed_invisible_write_failure_restores_binding_without_revoke():
    service = _service(None)
    service._users_belong_to_tenant = AsyncMock(return_value=True)
    service._actor_grant_permissions = AsyncMock(return_value={"manage_channel_user"})
    role_snapshot = await service._role_snapshot(
        ChannelGrantItem(
            subject_type="user",
            subject_id=11,
            relation=ChannelRelationEnum.VIEWER,
            model_id="viewer",
        )
    )
    _, role_fingerprint = _canonical_role_snapshot(role_snapshot)

    class _Transaction:
        snapshot = []
        bindings = []

        def __init__(self):
            self.restored = False

        async def commit(self, bindings):
            self.bindings = bindings

        async def restore(self):
            self.restored = True

        def ensure_owned(self):
            return None

    transaction = _Transaction()

    @asynccontextmanager
    async def _transaction():
        yield transaction

    service.relation_binding_mutation_service.transaction = _transaction

    with (
        patch(
            "bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles",
            new=AsyncMock(return_value=[SimpleNamespace(role_id=1)]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new=AsyncMock(side_effect=[FGAWriteError("write failed"), None]),
        ) as mock_authorize,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(FGAWriteError):
            await service.apply_confirmed_personal_user_grant(
                tenant_id=1,
                resource_id="channel-1",
                inviter_user_id=7,
                target_user_id=11,
                relation="viewer",
                model_id="viewer",
                role_snapshot=role_snapshot,
                role_fingerprint=role_fingerprint,
                include_children=False,
                approval_instance_id=1201,
            )

    assert mock_authorize.await_count == 1
    assert mock_authorize.await_args_list[0].kwargs["recovery_owner"] == "caller"
    assert transaction.restored is True


@pytest.mark.asyncio
async def test_channel_confirmed_binding_restore_failure_is_retryable():
    service = _service(ChannelRelationEnum.OWNER)
    service._users_belong_to_tenant = AsyncMock(return_value=True)
    role_snapshot = await service._role_snapshot(
        ChannelGrantItem(
            subject_type="user",
            subject_id=11,
            relation=ChannelRelationEnum.VIEWER,
            model_id="viewer",
        )
    )
    _, role_fingerprint = _canonical_role_snapshot(role_snapshot)

    class _Transaction:
        bindings = []

        def ensure_owned(self):
            return None

        async def commit(self, bindings):
            self.bindings = bindings

        async def restore(self):
            raise RuntimeError("binding restore failed")

    @asynccontextmanager
    async def _transaction():
        yield _Transaction()

    service.relation_binding_mutation_service.transaction = _transaction

    with (
        patch(
            "bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new=AsyncMock(side_effect=[FGAWriteError("write failed"), None]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(ChannelAuthorizationSyncError):
            await service.apply_confirmed_personal_user_grant(
                tenant_id=1,
                resource_id="channel-1",
                inviter_user_id=7,
                target_user_id=11,
                relation="viewer",
                model_id="viewer",
                role_snapshot=role_snapshot,
                role_fingerprint=role_fingerprint,
                include_children=False,
                approval_instance_id=1201,
            )


@pytest.mark.asyncio
async def test_channel_confirmed_notification_failure_is_best_effort():
    service = _service(ChannelRelationEnum.OWNER)
    service._users_belong_to_tenant = AsyncMock(return_value=True)
    role_snapshot = await service._role_snapshot(
        ChannelGrantItem(
            subject_type="user",
            subject_id=11,
            relation=ChannelRelationEnum.VIEWER,
            model_id="viewer",
        )
    )
    _, role_fingerprint = _canonical_role_snapshot(role_snapshot)

    class _Transaction:
        bindings = []

        def ensure_owned(self):
            return None

        async def commit(self, bindings):
            self.bindings = bindings

    @asynccontextmanager
    async def _transaction():
        yield _Transaction()

    service.relation_binding_mutation_service.transaction = _transaction

    with (
        patch(
            "bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new=AsyncMock(),
        ) as mock_authorize,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.dispatch_after_authorize",
            new=AsyncMock(side_effect=RuntimeError("message unavailable")),
        ),
    ):
        await service.apply_confirmed_personal_user_grant(
            tenant_id=1,
            resource_id="channel-1",
            inviter_user_id=7,
            target_user_id=11,
            relation="viewer",
            model_id="viewer",
            role_snapshot=role_snapshot,
            role_fingerprint=role_fingerprint,
            include_children=False,
            approval_instance_id=1201,
        )

    mock_authorize.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_confirmed_exact_effect_is_idempotent():
    service = _service(ChannelRelationEnum.OWNER)
    service._users_belong_to_tenant = AsyncMock(return_value=True)
    grant = ChannelGrantItem(
        subject_type="user",
        subject_id=11,
        relation=ChannelRelationEnum.VIEWER,
        model_id="viewer",
    )
    role_snapshot = await service._role_snapshot(grant)
    _, role_fingerprint = _canonical_role_snapshot(role_snapshot)

    class _Transaction:
        bindings = [
            {
                "key": "channel:channel-1:user:11:viewer:-",
                "resource_type": "channel",
                "resource_id": "channel-1",
                "subject_type": "user",
                "subject_id": 11,
                "relation": "viewer",
                "include_children": None,
                "model_id": "viewer",
            }
        ]

        def ensure_owned(self):
            return None

    @asynccontextmanager
    async def _transaction():
        yield _Transaction()

    service.relation_binding_mutation_service.transaction = _transaction
    existing = SimpleNamespace(subject_type="user", subject_id=11, relation="viewer")

    with (
        patch(
            "bisheng.user.domain.models.user_role.UserRoleDao.aget_user_roles",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.get_resource_permissions",
            new=AsyncMock(return_value=[existing]),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new=AsyncMock(),
        ) as mock_authorize,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
    ):
        await service.apply_confirmed_personal_user_grant(
            tenant_id=1,
            resource_id="channel-1",
            inviter_user_id=7,
            target_user_id=11,
            relation="viewer",
            model_id="viewer",
            role_snapshot=role_snapshot,
            role_fingerprint=role_fingerprint,
            include_children=False,
            approval_instance_id=1201,
        )

    mock_authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_grant_writes_permission_tuple_without_membership_sync():
    sync_service = _SyncService()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.OWNER),
            ChannelGrantItem(subject_type="user", subject_id=12, relation=ChannelRelationEnum.MANAGER),
            ChannelGrantItem(subject_type="user", subject_id=13, relation=ChannelRelationEnum.EDITOR),
            ChannelGrantItem(subject_type="user", subject_id=14, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch.object(
            service,
            "_save_binding_changes",
            new_callable=AsyncMock,
        ),
    ):
        result = await service.authorize_channel("channel-1", request, _User())

    assert mock_authorize.await_count == 1
    assert len(mock_authorize.await_args.kwargs["grants"]) == 4
    assert result.synced_user_count == 0
    assert result.affected_member_count == 0
    assert sync_service.grants == []


@pytest.mark.asyncio
async def test_authorize_channel_dispatches_permission_notifications_after_sync():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.MANAGER),
        ]
    )
    notify_context = object()

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new_callable=AsyncMock,
            return_value=notify_context,
        ) as mock_build_context,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.dispatch_after_authorize",
            new_callable=AsyncMock,
        ) as mock_dispatch,
    ):
        await service.authorize_channel("channel-1", request, _User())

    assert mock_build_context.await_args.kwargs["resource_type"] == "channel"
    assert mock_build_context.await_args.kwargs["resource_id"] == "channel-1"
    assert mock_build_context.await_args.kwargs["grants"][0].relation == "manager"
    assert mock_dispatch.await_args.kwargs == {
        "context": notify_context,
        "operator_user_id": _User.user_id,
        "operator_user_name": getattr(_User, "user_name", None),
    }


@pytest.mark.asyncio
async def test_owner_cannot_grant_organization_owner():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="department", subject_id=11, relation=ChannelRelationEnum.OWNER),
        ]
    )

    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel("channel-1", request, _User())


@pytest.mark.asyncio
async def test_owner_cannot_grant_user_group_owner():
    service = _service(ChannelRelationEnum.OWNER)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user_group", subject_id=11, relation=ChannelRelationEnum.OWNER),
        ]
    )

    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel("channel-1", request, _User())


@pytest.mark.asyncio
async def test_manager_can_only_grant_usage_relations():
    service = _service(ChannelRelationEnum.MANAGER)
    allowed = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.EDITOR),
            ChannelGrantItem(subject_type="user", subject_id=12, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ),
        patch.object(
            service,
            "_save_binding_changes",
            new_callable=AsyncMock,
        ),
    ):
        await service.authorize_channel("channel-1", allowed, _User())

    denied = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=13, relation=ChannelRelationEnum.MANAGER),
        ]
    )
    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel("channel-1", denied, _User())


@pytest.mark.asyncio
async def test_editor_viewer_cannot_authorize():
    service = _service(ChannelRelationEnum.EDITOR)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with pytest.raises(ChannelPermissionDeniedError):
        await service.authorize_channel("channel-1", request, _User())


@pytest.mark.asyncio
async def test_fga_failure_does_not_sync_membership():
    sync_service = _SyncService()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
        new_callable=AsyncMock,
        side_effect=RuntimeError("fga down"),
    ) as mock_authorize:
        with pytest.raises(RuntimeError, match="fga down"):
            await service.authorize_channel("channel-1", request, _User())

    assert mock_authorize.await_count == 1
    assert sync_service.grants == []


@pytest.mark.asyncio
async def test_membership_sync_service_is_not_called_for_permission_grants():
    class FailingSync(_SyncService):
        async def sync_grant(self, **kwargs):
            self.grants.append(kwargs)
            raise RuntimeError("sync failed")

    sync_service = FailingSync()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch.object(
            service,
            "_get_bindings",
            new_callable=AsyncMock,
            return_value=[{"key": "existing", "resource_type": "channel"}],
        ),
        patch.object(
            service,
            "_save_bindings",
            new_callable=AsyncMock,
        ),
    ):
        result = await service.authorize_channel("channel-1", request, _User())

    assert mock_authorize.await_count == 1
    assert result.synced_user_count == 0
    assert result.affected_member_count == 0
    assert sync_service.grants == []
    assert service.space_channel_member_repository.deleted_binding_keys == []


@pytest.mark.asyncio
async def test_direct_binding_failure_restores_locked_snapshot_without_clobbering_concurrent_change():
    sync_service = _SyncService()
    service = _service(ChannelRelationEnum.OWNER, sync_service)
    concurrent_binding = {
        "key": "channel:other:user:99:viewer:-",
        "resource_type": "channel",
        "resource_id": "other",
        "subject_type": "user",
        "subject_id": 99,
        "relation": "viewer",
        "model_id": "viewer",
    }

    class _FailingTransaction:
        snapshot = [concurrent_binding]
        bindings = [concurrent_binding]

        def __init__(self):
            self.restored = None

        def ensure_owned(self):
            return None

        async def commit(self, bindings):
            self.bindings = list(bindings)
            raise RuntimeError("binding failed")

        async def restore(self):
            self.bindings = list(self.snapshot)
            self.restored = list(self.bindings)

    transaction = _FailingTransaction()

    @asynccontextmanager
    async def _transaction():
        yield transaction

    service.relation_binding_mutation_service.transaction = _transaction
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
    ):
        with pytest.raises(ChannelAuthorizationSyncError):
            await service.authorize_channel("channel-1", request, _User())

    assert sync_service.grants == []
    assert service.space_channel_member_repository.deleted_binding_keys == []
    assert mock_authorize.await_count == 2
    assert mock_authorize.await_args_list[0].kwargs["recovery_owner"] == "caller"
    assert mock_authorize.await_args_list[1].kwargs["recovery_owner"] == "caller"
    assert mock_authorize.await_args_list[1].kwargs["revokes"][0].subject_id == 11
    assert transaction.restored == [concurrent_binding]


@pytest.mark.asyncio
async def test_direct_duplicate_grant_binding_failure_does_not_revoke_existing_tuple():
    service = _service(ChannelRelationEnum.OWNER)
    existing_binding = {
        "key": "channel:channel-1:user:11:viewer:-",
        "resource_type": "channel",
        "resource_id": "channel-1",
        "subject_type": "user",
        "subject_id": 11,
        "relation": "viewer",
        "include_children": None,
        "model_id": "viewer",
    }

    class _FailingTransaction:
        snapshot = [existing_binding]
        bindings = [existing_binding]
        restored = False

        def ensure_owned(self):
            return None

        async def commit(self, bindings):
            self.bindings = list(bindings)
            raise RuntimeError("binding failed")

        async def restore(self):
            self.bindings = list(self.snapshot)
            self.restored = True

    transaction = _FailingTransaction()

    @asynccontextmanager
    async def _transaction():
        yield transaction

    service.relation_binding_mutation_service.transaction = _transaction
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
        new_callable=AsyncMock,
    ) as mock_authorize:
        with pytest.raises(ChannelAuthorizationSyncError):
            await service.authorize_channel("channel-1", request, _User())

    assert mock_authorize.await_count == 1
    assert transaction.restored is True


_FINE_GRAINED_PERMISSIONS = (
    "bisheng.channel.domain.services.channel_authorization_service"
    ".FineGrainedPermissionService.get_effective_permission_ids_async"
)


@pytest.mark.asyncio
async def test_grantable_models_excludes_owner_without_manage_channel_owner():
    # Role carries delete + manage_manager + manage_user but NOT manage_channel_owner.
    service = _service(ChannelRelationEnum.OWNER)
    service._get_relation_models = AsyncMock(return_value=ChannelAuthorizationService._default_relation_models())
    effective = {
        "view_channel",
        "edit_channel",
        "delete_channel",
        "manage_channel_manager",
        "manage_channel_user",
    }

    with patch(_FINE_GRAINED_PERMISSIONS, new_callable=AsyncMock, return_value=effective):
        models = await service.grantable_relation_models("channel-1", _User())

    relations = {m.relation.value for m in models}
    assert "owner" not in relations
    assert {"manager", "editor", "viewer"} <= relations


@pytest.mark.asyncio
async def test_authorize_denied_owner_grant_without_manage_channel_owner():
    service = _service(ChannelRelationEnum.OWNER)
    effective = {"delete_channel", "manage_channel_manager", "manage_channel_user"}
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.OWNER),
        ]
    )

    with (
        patch(_FINE_GRAINED_PERMISSIONS, new_callable=AsyncMock, return_value=effective),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
    ):
        with pytest.raises(ChannelPermissionDeniedError):
            await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_authorize_allows_manager_grant_with_manage_channel_manager():
    service = _service(ChannelRelationEnum.OWNER)
    effective = {"manage_channel_manager", "manage_channel_user"}
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.MANAGER),
        ]
    )

    with (
        patch(_FINE_GRAINED_PERMISSIONS, new_callable=AsyncMock, return_value=effective),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch.object(
            service,
            "_save_binding_changes_from_snapshot",
            new_callable=AsyncMock,
        ),
    ):
        await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_non_owner_bindings_keeps_owner_and_other_resources():
    bindings = [
        {"key": "k1", "resource_type": "channel", "resource_id": "channel-1", "relation": "owner"},
        {"key": "k2", "resource_type": "channel", "resource_id": "channel-1", "relation": "manager"},
        {"key": "k3", "resource_type": "channel", "resource_id": "channel-1", "relation": "viewer"},
        {"key": "k4", "resource_type": "channel", "resource_id": "channel-2", "relation": "viewer"},
        {"key": "k5", "resource_type": "knowledge_space", "resource_id": "channel-1", "relation": "viewer"},
    ]
    saved: dict = {}

    async def _fake_save(new_bindings):
        saved["value"] = new_bindings

    mutation_service = SimpleNamespace()

    async def _mutate(mutator):
        updated = mutator(bindings)
        if updated != bindings:
            await _fake_save(updated)
        return updated

    mutation_service.mutate = _mutate

    with (
        patch.object(
            ChannelAuthorizationService,
            "_new_binding_mutation_service",
            return_value=mutation_service,
        ),
    ):
        removed = await ChannelAuthorizationService.clear_non_owner_bindings("channel-1")

    assert removed == 2
    remaining_keys = {b["key"] for b in saved["value"]}
    assert remaining_keys == {"k1", "k4", "k5"}


@pytest.mark.asyncio
async def test_clear_non_owner_bindings_noop_when_nothing_to_remove():
    bindings = [
        {"key": "k1", "resource_type": "channel", "resource_id": "channel-1", "relation": "owner"},
    ]
    mutate = AsyncMock(side_effect=lambda mutator: mutator(bindings))
    mutation_service = SimpleNamespace(mutate=mutate)
    with patch.object(
        ChannelAuthorizationService,
        "_new_binding_mutation_service",
        return_value=mutation_service,
    ):
        removed = await ChannelAuthorizationService.clear_non_owner_bindings("channel-1")

    assert removed == 0
    mutate.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_tenant_subject_validation_rejects_before_fga_write():
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepo(),
        space_channel_member_repository=_MemberRepo(ChannelRelationEnum.OWNER),
        membership_sync_service=_SyncService(),
        invite_application_service=_InviteService(),
        relation_binding_mutation_service=_BindingMutationService(),
    )
    service._active_explicit_user_ids = AsyncMock(return_value=set())
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with (
        patch.object(
            service,
            "_users_belong_to_tenant",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
    ):
        result = await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_not_awaited()
    assert result.failed_count == 1
    assert result.results[0].error_code == ChannelPermissionDeniedError.Code


@pytest.mark.asyncio
async def test_cross_tenant_revoke_is_allowed_for_cleanup():
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepo(),
        space_channel_member_repository=_MemberRepo(ChannelRelationEnum.OWNER),
        membership_sync_service=_SyncService(),
        relation_binding_mutation_service=_BindingMutationService(),
    )
    request = ChannelAuthorizeRequest(
        revokes=[
            ChannelRevokeItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.VIEWER),
        ]
    )

    with (
        patch.object(
            service,
            "_users_belong_to_tenant",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_users_belong_to_tenant,
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch.object(
            service,
            "_save_binding_changes_from_snapshot",
            new_callable=AsyncMock,
        ),
        patch.object(
            service,
            "_get_bindings",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch.object(
            service,
            "_save_bindings",
            new_callable=AsyncMock,
        ),
    ):
        await service.authorize_channel("channel-1", request, _User())

    mock_users_belong_to_tenant.assert_not_awaited()
    mock_authorize.assert_awaited_once()


def _service_with_creator(actor_relation: ChannelRelationEnum, creator_id: int) -> ChannelAuthorizationService:
    """Service whose channel reports ``creator_id`` as its DB creator (user_id)."""
    service = _service(actor_relation)
    service.channel_repository = type(
        "Repo",
        (),
        {
            "find_by_id": AsyncMock(
                return_value=type(
                    "Channel",
                    (),
                    {"id": "channel-1", "tenant_id": 1, "user_id": creator_id},
                )(),
            ),
        },
    )()
    return service


@pytest.mark.asyncio
async def test_cannot_downgrade_creator_permission_even_as_owner():
    # Actor is OWNER (holds manage_channel_owner); creator is user 99.
    service = _service_with_creator(ChannelRelationEnum.OWNER, creator_id=99)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=99, relation=ChannelRelationEnum.MANAGER),
        ]
    )

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
        new_callable=AsyncMock,
    ) as mock_authorize:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.authorize_channel("channel-1", request, _User())

    # Rejected before any permission tuple is written.
    mock_authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_cannot_revoke_creator_permission_even_as_owner():
    service = _service_with_creator(ChannelRelationEnum.OWNER, creator_id=99)
    request = ChannelAuthorizeRequest(
        revokes=[
            ChannelRevokeItem(subject_type="user", subject_id=99, relation=ChannelRelationEnum.OWNER),
        ]
    )

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
        new_callable=AsyncMock,
    ) as mock_authorize:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_granting_non_creator_user_is_not_blocked_by_creator_guard():
    # Creator is 99; granting a different user (11) must pass the creator guard.
    service = _service_with_creator(ChannelRelationEnum.OWNER, creator_id=99)
    request = ChannelAuthorizeRequest(
        grants=[
            ChannelGrantItem(subject_type="user", subject_id=11, relation=ChannelRelationEnum.MANAGER),
        ]
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as mock_authorize,
        patch.object(
            service,
            "_save_binding_changes_from_snapshot",
            new_callable=AsyncMock,
        ),
    ):
        await service.authorize_channel("channel-1", request, _User())

    mock_authorize.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_permissions_marks_creator_entry():
    # Channel created by user 99; user 11 is a granted (non-creator) owner.
    service = _service_with_creator(ChannelRelationEnum.OWNER, creator_id=99)
    service._require_manage_access = AsyncMock(return_value=ChannelRelationEnum.OWNER)
    service._get_relation_models = AsyncMock(return_value=[])

    def _perm(subject_id: int, name: str):
        return SimpleNamespace(
            subject_type="user",
            subject_id=subject_id,
            relation="owner",
            subject_name=name,
            subject_group_names=None,
            subject_member_names=None,
            include_children=None,
            model_id="owner",
            model_name=None,
        )

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service."
        "PermissionService.get_resource_permissions_from_bindings",
        new=AsyncMock(return_value=[_perm(99, "creator"), _perm(11, "granted-owner")]),
    ) as list_binding_permissions:
        entries = await service.list_permissions("channel-1", _User())

    by_id = {e.subject_id: e for e in entries}
    assert by_id[99].is_creator is True
    assert by_id[11].is_creator is False
    display_bindings = list_binding_permissions.await_args.args[0]
    assert display_bindings == [
        {
            "subject_type": "user",
            "subject_id": 99,
            "relation": "owner",
            "include_children": None,
            "model_id": "owner",
        }
    ]
