from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.channel.domain.models.channel import ChannelVisibilityEnum
from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizationItemResult,
    ChannelAuthorizeResponse,
)
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
)
from bisheng.channel.domain.services.channel_creation_application_service import (
    ChannelCreationApplicationService,
)
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.common.errcode.channel import (
    ChannelAuthorizationSyncError,
    ChannelPermissionDeniedError,
)
from bisheng.core.openfga.exceptions import FGAConnectionError, FGAWriteError

CHANNEL_ID = "channel-created-once"


class _BindingMutationService:
    @asynccontextmanager
    async def transaction(self):
        class _Transaction:
            snapshot = []
            bindings = []

            def ensure_owned(self):
                return None

            async def commit(self, bindings):
                self.bindings = list(bindings)

            async def restore(self):
                self.bindings = list(self.snapshot)

        yield _Transaction()


class _LoginUser:
    user_id = 7
    user_name = "operator"
    tenant_id = 1

    def is_admin(self) -> bool:
        return False


def _create_request(
    *,
    grants: list[dict] | None = None,
    visibility: ChannelVisibilityEnum = ChannelVisibilityEnum.PUBLIC,
) -> CreateChannelRequest:
    payload = {
        "name": "资讯频道",
        "source_list": ["source-1"],
        "visibility": visibility,
        "is_released": True,
    }
    if grants is not None:
        payload["initial_permissions"] = {"grants": grants}
    return CreateChannelRequest.model_validate(payload)


def _grant(
    *,
    subject_type: str = "user",
    subject_id: int = 11,
    relation: str = "editor",
) -> dict:
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "relation": relation,
        "include_children": False,
        "model_id": relation,
    }


def _services(*, channel=None):
    created_channel = channel or SimpleNamespace(id=CHANNEL_ID, name="资讯频道")
    channel_service = SimpleNamespace(create_channel=AsyncMock(return_value=created_channel))
    query_service = SimpleNamespace(
        validate_creation_grants=AsyncMock(),
        validate_creation_grant_request=AsyncMock(return_value=1),
        validate_creation_grant_subjects=AsyncMock(),
    )

    @asynccontextmanager
    async def scenario_guard(grants, **kwargs):
        await authorization_service.ensure_invite_scenario_available_for_grants(
            grants,
            **kwargs,
        )
        yield

    authorization_service = SimpleNamespace(
        authorize_channel=AsyncMock(return_value=ChannelAuthorizeResponse()),
        ensure_invite_scenario_available_for_grants=AsyncMock(),
        invite_scenario_guard_for_grants=MagicMock(side_effect=scenario_guard),
    )
    application_service = ChannelCreationApplicationService(
        channel_service=channel_service,
        grant_subject_query_service=query_service,
        channel_authorization_service=authorization_service,
    )
    return application_service, channel_service, query_service, authorization_service


def _field(value, name: str):
    if isinstance(value, dict):
        return value[name]
    return getattr(value, name)


async def test_create_channel_without_grants_compatible():
    created_channel = SimpleNamespace(id=CHANNEL_ID, name="资讯频道")
    application_service, channel_service, query_service, authorization_service = _services(channel=created_channel)
    channel_data = _create_request()
    login_user = _LoginUser()
    http_request = object()

    result = await application_service.create(channel_data, login_user, http_request)

    assert result is created_channel
    channel_service.create_channel.assert_awaited_once_with(channel_data, login_user, http_request)
    query_service.validate_creation_grants.assert_not_awaited()
    authorization_service.authorize_channel.assert_not_awaited()


async def test_create_then_authorize_channel():
    events: list[str] = []

    async def validate(**kwargs):
        events.append("validate")
        return 1

    async def create(*args):
        events.append("create")
        return SimpleNamespace(id=CHANNEL_ID, name="资讯频道")

    async def authorize(*args, **kwargs):
        events.append("authorize")

    application_service, channel_service, query_service, authorization_service = _services()
    query_service.validate_creation_grant_request.side_effect = validate
    channel_service.create_channel.side_effect = create
    authorization_service.authorize_channel.side_effect = authorize
    channel_data = _create_request(grants=[_grant()])
    login_user = _LoginUser()
    http_request = object()

    result = await application_service.create(channel_data, login_user, http_request)

    assert events == ["validate", "create", "authorize"]
    assert channel_service.create_channel.await_count == 1
    query_service.validate_creation_grant_request.assert_awaited_once()
    query_service.validate_creation_grant_subjects.assert_awaited_once()
    authorize_args = authorization_service.authorize_channel.await_args.args
    assert authorize_args[0] == CHANNEL_ID
    assert authorize_args[2] is login_user
    assert len(authorize_args[1].grants) == 1
    assert authorize_args[1].grants[0].subject_id == 11
    assert authorize_args[1].revokes == []
    permission_result = _field(result, "initial_permission_result")
    assert _field(permission_result, "status") == "success"
    assert _field(permission_result, "error_code") is None


async def test_channel_create_disabled_scene_before_side_effect():
    application_service, channel_service, query_service, authorization_service = _services()
    authorization_service.ensure_invite_scenario_available_for_grants.side_effect = ApprovalScenarioDisabledError(
        msg="个人用户邀请确认场景未启用，无法新增个人用户权限"  # noqa: RUF001
    )

    grants = [_grant()]
    with (
        patch("bisheng.core.context.tenant.get_current_tenant_id", return_value=5),
        pytest.raises(ApprovalScenarioDisabledError),
    ):
        await application_service.create(
            _create_request(grants=grants),
            _LoginUser(),
            object(),
        )

    assert authorization_service.ensure_invite_scenario_available_for_grants.await_args.kwargs["tenant_id"] == 5
    channel_service.create_channel.assert_not_awaited()
    query_service.validate_creation_grant_request.assert_not_awaited()
    authorization_service.authorize_channel.assert_not_awaited()


async def test_channel_create_mixed_invites():
    application_service, channel_service, _, authorization_service = _services()
    authorization_service.authorize_channel.return_value = ChannelAuthorizeResponse(
        direct_applied_count=1,
        invite_created_count=1,
        results=[
            ChannelAuthorizationItemResult(
                operation="grant",
                subject_type="department",
                subject_id=21,
                relation="viewer",
                model_id="viewer",
                outcome="applied",
            ),
            ChannelAuthorizationItemResult(
                operation="grant",
                subject_type="user",
                subject_id=11,
                relation="viewer",
                model_id="viewer",
                outcome="invite_created",
                approval_instance_id=1201,
            ),
        ],
    )

    result = await application_service.create(
        _create_request(
            grants=[
                _grant(subject_type="department", subject_id=21, relation="viewer"),
                _grant(subject_type="user", subject_id=11, relation="viewer"),
            ]
        ),
        _LoginUser(),
        object(),
    )

    permission_result = _field(result, "initial_permission_result")
    assert _field(permission_result, "status") == "success"
    assert _field(permission_result, "direct_applied_count") == 1
    assert _field(permission_result, "invite_created_count") == 1
    assert len(_field(permission_result, "results")) == 2
    assert channel_service.create_channel.await_count == 1


async def test_channel_create_partial_failure_keeps_channel():
    application_service, channel_service, _, authorization_service = _services()
    authorization_service.authorize_channel.return_value = ChannelAuthorizeResponse(
        failed_count=1,
        results=[
            ChannelAuthorizationItemResult(
                operation="grant",
                subject_type="user",
                subject_id=11,
                relation="viewer",
                model_id="viewer",
                outcome="failed",
                error_code=ChannelPermissionDeniedError.Code,
                error_message="target invalid",
            )
        ],
    )

    result = await application_service.create(
        _create_request(grants=[_grant()]),
        _LoginUser(),
        object(),
    )

    assert _field(result, "id") == CHANNEL_ID
    permission_result = _field(result, "initial_permission_result")
    assert _field(permission_result, "status") == "failed"
    assert _field(permission_result, "error_code") == ChannelPermissionDeniedError.Code
    assert _field(permission_result, "failed_count") == 1
    assert channel_service.create_channel.await_count == 1


async def test_authorize_failure_does_not_recreate_channel():
    created_channel = SimpleNamespace(id=CHANNEL_ID, name="资讯频道")
    application_service, channel_service, _, authorization_service = _services(channel=created_channel)
    authorization_error = ChannelPermissionDeniedError()
    authorization_service.authorize_channel.side_effect = authorization_error
    channel_data = _create_request(grants=[_grant()])

    result = await application_service.create(channel_data, _LoginUser(), object())

    assert channel_service.create_channel.await_count == 1
    assert authorization_service.authorize_channel.await_count == 1
    assert _field(result, "id") == CHANNEL_ID
    permission_result = _field(result, "initial_permission_result")
    assert _field(permission_result, "status") == "failed"
    assert _field(permission_result, "error_code") == authorization_error.code


async def test_invalid_subject_rejected_before_create():
    application_service, channel_service, query_service, authorization_service = _services()
    validation_error = ChannelPermissionDeniedError()
    query_service.validate_creation_grant_request.side_effect = validation_error
    channel_data = _create_request(grants=[_grant(subject_type="user_group", subject_id=201, relation="owner")])

    with pytest.raises(ChannelPermissionDeniedError) as exc_info:
        await application_service.create(channel_data, _LoginUser(), object())

    assert exc_info.value is validation_error
    channel_service.create_channel.assert_not_awaited()
    authorization_service.authorize_channel.assert_not_awaited()


async def test_private_channel_rejects_initial_grants_before_validation_or_create():
    application_service, channel_service, query_service, authorization_service = _services()
    channel_data = _create_request(
        visibility=ChannelVisibilityEnum.PRIVATE,
        grants=[_grant()],
    )

    with pytest.raises(ChannelPermissionDeniedError):
        await application_service.create(channel_data, _LoginUser(), object())

    query_service.validate_creation_grant_request.assert_not_awaited()
    channel_service.create_channel.assert_not_awaited()
    authorization_service.authorize_channel.assert_not_awaited()


@pytest.mark.parametrize(
    ("tuple_error", "expected_error_code"),
    [
        (FGAConnectionError("OpenFGA unavailable"), ChannelAuthorizationSyncError.Code),
        (FGAWriteError("tuple write rejected"), ChannelAuthorizationSyncError.Code),
        (ChannelPermissionDeniedError(), ChannelPermissionDeniedError.Code),
    ],
    ids=["fga-connection", "fga-write", "business-error"],
)
async def test_tuple_write_failure_is_structured_without_recreating_channel(
    tuple_error: Exception,
    expected_error_code: int,
):
    created_channel = SimpleNamespace(
        id=CHANNEL_ID,
        name="资讯频道",
        user_id=_LoginUser.user_id,
        tenant_id=_LoginUser.tenant_id,
    )
    channel_service = SimpleNamespace(create_channel=AsyncMock(return_value=created_channel))
    query_service = SimpleNamespace(
        validate_creation_grant_request=AsyncMock(return_value=1),
        validate_creation_grant_subjects=AsyncMock(),
    )
    authorization_service = ChannelAuthorizationService(
        channel_repository=MagicMock(),
        space_channel_member_repository=MagicMock(),
        membership_sync_service=MagicMock(),
        relation_binding_mutation_service=_BindingMutationService(),
    )
    authorization_service._ensure_channel = AsyncMock(return_value=created_channel)
    authorization_service._actor_grant_permissions = AsyncMock(return_value={"manage_channel_user"})
    authorization_service._validate_subjects_belong_to_channel_tenant = AsyncMock()
    authorization_service._active_explicit_user_ids = AsyncMock(return_value=set())
    application_service = ChannelCreationApplicationService(
        channel_service=channel_service,
        grant_subject_query_service=query_service,
        channel_authorization_service=authorization_service,
    )

    with (
        patch(
            "bisheng.channel.domain.services.channel_authorization_service.PermissionService.authorize",
            new=AsyncMock(side_effect=tuple_error),
        ),
        patch(
            "bisheng.channel.domain.services.channel_authorization_service."
            "ResourcePermissionNotificationService.build_context",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await application_service.create(
            _create_request(grants=[_grant(subject_type="department", subject_id=11)]),
            _LoginUser(),
            object(),
        )

    assert channel_service.create_channel.await_count == 1
    permission_result = _field(result, "initial_permission_result")
    assert _field(permission_result, "status") == "failed"
    assert _field(permission_result, "error_code") == expected_error_code
