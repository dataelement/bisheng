from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_manager_schema import UpdateChannelRequest
from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
)
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.errcode.channel import ChannelPermissionDeniedError
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.common.errcode.permission import PermissionDeniedError, PermissionTupleWriteError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.models.knowledge import (
    AuthTypeEnum,
    Knowledge,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.api.endpoints.resource_permission import get_resource_permissions
from bisheng.permission.domain.channel_permission_template import (
    default_permission_ids_for_relation as channel_permission_ids,
)
from bisheng.permission.domain.channel_permission_template import (
    relation_from_channel_permission_ids,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation as knowledge_space_permission_ids,
)
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRequest,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.services.resource_authorization_service import (
    ResourceAuthorizationService,
)


class _LoginUser:
    user_id = 7
    user_name = "operator"
    tenant_id = 1

    def is_admin(self) -> bool:
        return False


class _AdminUser(_LoginUser):
    user_id = 1

    def is_admin(self) -> bool:
        return True


def _knowledge_space(auth_type: AuthTypeEnum) -> Knowledge:
    return Knowledge(
        id=1,
        user_id=1,
        tenant_id=1,
        name="Knowledge Space",
        type=KnowledgeTypeEnum.SPACE.value,
        auth_type=auth_type,
    )


def _channel(visibility: ChannelVisibilityEnum) -> Channel:
    return Channel(
        id="channel-1",
        user_id=1,
        tenant_id=1,
        name="Channel",
        source_list=[],
        visibility=visibility,
    )


def _channel_service(channel, member_repository=None) -> ChannelService:
    return ChannelService(
        channel_repository=SimpleNamespace(
            find_by_id=AsyncMock(return_value=channel),
            update=AsyncMock(side_effect=lambda value: value),
        ),
        space_channel_member_repository=member_repository or SimpleNamespace(),
        channel_info_source_repository=SimpleNamespace(find_by_ids=AsyncMock(return_value=[])),
    )


@pytest.mark.asyncio
async def test_knowledge_space_submit_rechecks_permission_before_mutation():
    space = _knowledge_space(AuthTypeEnum.PUBLIC)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=_LoginUser())

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(return_value=space),
        ),
        patch.object(
            service,
            "_require_permission_id",
            new=AsyncMock(side_effect=SpacePermissionDeniedError()),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new_callable=AsyncMock,
        ) as update_space,
    ):
        with pytest.raises(SpacePermissionDeniedError):
            await service.update_knowledge_space(1, name="Forbidden rename")

    assert space.name == "Knowledge Space"
    update_space.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_submit_rechecks_permission_before_mutation():
    channel = _channel(ChannelVisibilityEnum.PUBLIC)
    service = _channel_service(channel)
    service._user_can_edit_channel = AsyncMock(return_value=False)

    with patch(
        "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
        new_callable=AsyncMock,
    ) as get_information_client:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.update_channel(
                channel.id,
                UpdateChannelRequest(name="Forbidden rename"),
                _LoginUser(),
            )

    assert channel.name == "Channel"
    service.channel_repository.update.assert_not_awaited()
    get_information_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_space_non_manager_cannot_read_permissions():
    with (
        patch(
            "bisheng.permission.api.endpoints.resource_permission._has_resource_permission_management_access",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.get_resource_permissions",
            new_callable=AsyncMock,
        ) as list_permissions,
    ):
        response = await get_resource_permissions("knowledge_space", "1", _LoginUser())

    assert response.status_code == PermissionDeniedError.Code
    assert response.data is None
    list_permissions.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_non_manager_cannot_read_permissions():
    service = ChannelAuthorizationService(
        channel_repository=SimpleNamespace(),
        space_channel_member_repository=SimpleNamespace(),
        membership_sync_service=SimpleNamespace(),
    )
    service._require_manage_access = AsyncMock(side_effect=ChannelPermissionDeniedError())

    with patch(
        "bisheng.channel.domain.services.channel_authorization_service.PermissionService.get_resource_permissions",
        new_callable=AsyncMock,
    ) as list_permissions:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.list_permissions("channel-1", _LoginUser())

    list_permissions.assert_not_awaited()


@pytest.mark.asyncio
async def test_touched_authorize_preserves_untouched_concurrent_binding():
    concurrent_binding = {
        "key": "knowledge_space:1:user:30:viewer:-",
        "resource_type": "knowledge_space",
        "resource_id": "1",
        "subject_type": "user",
        "subject_id": 30,
        "relation": "viewer",
        "include_children": None,
        "model_id": "viewer",
    }
    touched_binding = {
        "key": "knowledge_space:1:user:20:viewer:-",
        "resource_type": "knowledge_space",
        "resource_id": "1",
        "subject_type": "user",
        "subject_id": 20,
        "relation": "viewer",
        "include_children": None,
        "model_id": "viewer",
    }
    save_bindings = AsyncMock()
    service = ResourceAuthorizationService(
        get_bindings=AsyncMock(return_value=[concurrent_binding, touched_binding]),
        save_bindings=save_bindings,
        grant_subject_query_service=SimpleNamespace(validate_resource_grants=AsyncMock(return_value=None)),
    )
    request = AuthorizeRequest(
        grants=[
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=20,
                relation="editor",
                model_id="editor",
            )
        ],
        revokes=[
            AuthorizeRevokeItem(
                subject_type="user",
                subject_id=20,
                relation="viewer",
                model_id="viewer",
            )
        ],
    )

    with (
        patch(
            "bisheng.knowledge.domain.models.department_knowledge_space.DepartmentKnowledgeSpaceDao.aget_by_space_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "bisheng.permission.domain.services.permission_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
        patch(
            "bisheng.permission.domain.services.resource_permission_notification_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
    ):
        await service.authorize("knowledge_space", "1", request, _AdminUser())

    assert [item.subject_id for item in authorize.await_args.kwargs["grants"]] == [20]
    assert [item.subject_id for item in authorize.await_args.kwargs["revokes"]] == [20]
    saved = save_bindings.await_args.args[0]
    assert concurrent_binding in saved
    assert touched_binding not in saved
    assert any(
        binding["subject_id"] == 20 and binding["relation"] == "editor" and binding["model_id"] == "editor"
        for binding in saved
    )


@pytest.mark.asyncio
async def test_knowledge_space_private_then_share_does_not_restore_permissions():
    public_space = _knowledge_space(AuthTypeEnum.PUBLIC)
    private_space = _knowledge_space(AuthTypeEnum.PRIVATE)
    shared_again = _knowledge_space(AuthTypeEnum.PUBLIC)
    service = KnowledgeSpaceService(request=SimpleNamespace(), login_user=_LoginUser())

    with (
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new=AsyncMock(side_effect=[public_space, private_space]),
        ),
        patch.object(service, "_require_permission_id", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
            new=AsyncMock(side_effect=[private_space, shared_again]),
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_get_members_by_space",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(service, "_authorized_space_user_ids", new=AsyncMock(return_value=set())),
        patch.object(service, "_list_space_child_resources", new=AsyncMock(return_value=[])),
        patch.object(
            KnowledgeSpaceService,
            "clear_space_authorization_for_private",
            new_callable=AsyncMock,
        ) as clear_permissions,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service."
            "SpaceChannelMemberDao.async_delete_non_creator_members",
            new_callable=AsyncMock,
        ) as delete_non_creator_members,
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
    ):
        await service.update_knowledge_space(1, auth_type=AuthTypeEnum.PRIVATE)
        await service.update_knowledge_space(1, auth_type=AuthTypeEnum.PUBLIC)

    clear_permissions.assert_awaited_once()
    delete_non_creator_members.assert_awaited_once_with(1)
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_private_then_share_does_not_restore_permissions():
    channel = _channel(ChannelVisibilityEnum.PUBLIC)
    creator = SimpleNamespace(id=10, user_id=1, user_role=UserRoleEnum.CREATOR, status="active")
    granted_owner = SimpleNamespace(id=11, user_id=2, user_role=UserRoleEnum.CREATOR, status="active")
    member_repository = SimpleNamespace(
        find_all=AsyncMock(return_value=[creator, granted_owner]),
        delete=AsyncMock(return_value=True),
    )
    service = _channel_service(channel, member_repository)
    service._user_can_edit_channel = AsyncMock(return_value=True)

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ChannelAuthorizationService.clear_authorization_for_private",
            new_callable=AsyncMock,
        ) as clear_authorization,
        patch(
            "bisheng.channel.domain.services.channel_service.OwnerService.write_owner_tuple",
            new_callable=AsyncMock,
        ) as write_owner_tuple,
        patch(
            "bisheng.channel.domain.services.channel_service.PermissionService.authorize",
            new_callable=AsyncMock,
        ) as authorize,
    ):
        await service.update_channel(
            channel.id,
            UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
            _LoginUser(),
        )
        await service.update_channel(
            channel.id,
            UpdateChannelRequest(visibility=ChannelVisibilityEnum.PUBLIC),
            _LoginUser(),
        )

    clear_authorization.assert_awaited_once_with(channel.id, channel.user_id)
    write_owner_tuple.assert_awaited_once_with(
        channel.user_id,
        "channel",
        channel.id,
        enforce_fga_success=True,
    )
    member_repository.delete.assert_awaited_once_with(granted_owner.id)
    authorize.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_private_cleanup_preserves_only_actual_creator_authorization():
    bindings = [
        {
            "resource_type": "channel",
            "resource_id": "channel-1",
            "subject_type": "self",
            "subject_id": 1,
            "relation": "owner",
        },
        {
            "resource_type": "channel",
            "resource_id": "channel-1",
            "subject_type": "user",
            "subject_id": 2,
            "relation": "owner",
        },
        {
            "resource_type": "channel",
            "resource_id": "channel-1",
            "subject_type": "department",
            "subject_id": 20,
            "relation": "owner",
        },
        {
            "resource_type": "channel",
            "resource_id": "channel-1",
            "subject_type": "user_group",
            "subject_id": 30,
            "relation": "owner",
        },
        {
            "resource_type": "channel",
            "resource_id": "other-channel",
            "subject_type": "user",
            "subject_id": 2,
            "relation": "viewer",
        },
    ]
    tuples = [
        {"user": "user:1", "relation": "owner", "object": "channel:channel-1"},
        {"user": "user:2", "relation": "owner", "object": "channel:channel-1"},
        {"user": "department:20#member", "relation": "owner", "object": "channel:channel-1"},
        {"user": "user_group:30#member", "relation": "owner", "object": "channel:channel-1"},
        {"user": "user:3", "relation": "viewer", "object": "channel:channel-1"},
    ]
    save_bindings = AsyncMock()
    batch_write = AsyncMock()

    with (
        patch.object(ChannelAuthorizationService, "_get_bindings", new=AsyncMock(return_value=bindings)),
        patch.object(ChannelAuthorizationService, "_save_bindings", new=save_bindings),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService._aget_fga",
            new=AsyncMock(return_value=SimpleNamespace(read_tuples=AsyncMock(return_value=tuples))),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.batch_write_tuples",
            new=batch_write,
        ),
    ):
        await ChannelAuthorizationService.clear_authorization_for_private("channel-1", 1)

    assert save_bindings.await_args.args[0] == [bindings[0], bindings[-1]]
    operations = batch_write.await_args.args[0]
    assert {(item.user, item.relation) for item in operations} == {
        ("user:2", "owner"),
        ("department:20#member", "owner"),
        ("user_group:30#member", "owner"),
        ("user:3", "viewer"),
    }
    assert batch_write.await_args.kwargs == {
        "crash_safe": True,
        "raise_on_failure": True,
        "stop_on_failure": True,
    }


@pytest.mark.asyncio
async def test_channel_private_binding_failure_uses_existing_permission_error():
    creator_tuple = {"user": "user:1", "relation": "owner", "object": "channel:channel-1"}
    with (
        patch.object(
            ChannelAuthorizationService,
            "_get_bindings",
            new=AsyncMock(side_effect=RuntimeError("binding store unavailable")),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService._aget_fga",
            new=AsyncMock(return_value=SimpleNamespace(read_tuples=AsyncMock(return_value=[creator_tuple]))),
        ),
    ):
        with pytest.raises(PermissionTupleWriteError):
            await ChannelAuthorizationService.clear_authorization_for_private("channel-1", 1)


@pytest.mark.asyncio
async def test_channel_private_cleanup_failure_uses_existing_permission_error():
    channel = _channel(ChannelVisibilityEnum.PUBLIC)
    member_repository = SimpleNamespace(
        find_all=AsyncMock(return_value=[]),
        delete=AsyncMock(return_value=True),
    )
    service = _channel_service(channel, member_repository)
    service._user_can_edit_channel = AsyncMock(return_value=True)
    failure = PermissionTupleWriteError(exception=RuntimeError("fga down"))

    with (
        patch(
            "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ChannelAuthorizationService.clear_authorization_for_private",
            new=AsyncMock(side_effect=failure),
        ),
    ):
        with pytest.raises(PermissionTupleWriteError) as exc_info:
            await service.update_channel(
                channel.id,
                UpdateChannelRequest(visibility=ChannelVisibilityEnum.PRIVATE),
                _LoginUser(),
            )

    assert exc_info.value.Code == PermissionTupleWriteError.Code
    member_repository.delete.assert_not_awaited()
    service.channel_repository.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_creator_owner_cannot_update_creator_only_knowledge_sync():
    channel = _channel(ChannelVisibilityEnum.PUBLIC)
    service = _channel_service(channel)
    service._user_can_edit_channel = AsyncMock(return_value=True)
    service._save_knowledge_sync = AsyncMock()

    with patch(
        "bisheng.channel.domain.services.channel_service.get_bisheng_information_client",
        new_callable=AsyncMock,
    ) as get_information_client:
        with pytest.raises(ChannelPermissionDeniedError):
            await service.update_channel(
                channel.id,
                UpdateChannelRequest(
                    knowledge_sync={
                        "main": {"enabled": False, "spaces": []},
                        "subs": [],
                    }
                ),
                _LoginUser(),
            )

    get_information_client.assert_not_awaited()
    service._save_knowledge_sync.assert_not_awaited()
    service.channel_repository.update.assert_not_awaited()


def test_canonical_role_and_permission_id_semantics_are_unchanged():
    assert knowledge_space_permission_ids("viewer") == {
        "view_space",
        "view_folder",
        "download_folder",
        "view_file",
        "download_file",
    }
    assert knowledge_space_permission_ids("editor") == {
        *knowledge_space_permission_ids("viewer"),
        "edit_space",
        "create_folder",
        "rename_folder",
        "move_folder",
        "upload_file",
        "rename_file",
        "move_file",
    }
    assert "manage_space_relation" in knowledge_space_permission_ids("manager")
    assert "delete_space" in knowledge_space_permission_ids("owner")

    expected_channel_permissions = {
        "owner": {
            "view_channel",
            "edit_channel",
            "delete_channel",
            "manage_channel_owner",
            "manage_channel_manager",
            "manage_channel_user",
        },
        "manager": {"view_channel", "edit_channel", "manage_channel_user"},
        "editor": {"view_channel", "edit_channel"},
        "viewer": {"view_channel"},
    }
    for relation, permission_ids in expected_channel_permissions.items():
        assert channel_permission_ids(relation) == permission_ids
        assert relation_from_channel_permission_ids(permission_ids) == relation
