from __future__ import annotations

import hashlib
import inspect
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizeRequest,
    ChannelGrantItem,
    ChannelRevokeItem,
)
from bisheng.channel.domain.services import channel_authorization_service as channel_module
from bisheng.channel.domain.services.channel_authorization_service import (
    ChannelAuthorizationService,
)
from bisheng.common.errcode.channel import ChannelAuthorizationSyncError, ChannelPermissionDeniedError
from bisheng.common.models.space_channel_member import ChannelRelationEnum
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.permission.domain.ports.resource_grant_executor import ResourceGrantCommand
from bisheng.permission.domain.services.permission_service import PermissionService

TENANT_ID = 7


@pytest.fixture(autouse=True)
def tenant_context():
    token = set_current_tenant_id(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


class _User:
    user_id = 101
    user_name = "inviter-a"
    tenant_id = TENANT_ID
    user_role: list[int] = []

    def is_admin(self) -> bool:
        return False


class _ChannelRepository:
    def __init__(self) -> None:
        self.channel = SimpleNamespace(
            id="channel-88",
            tenant_id=TENANT_ID,
            name="News",
            visibility="public",
            user_id=901,
        )

    async def find_by_id(self, channel_id: str):
        if str(channel_id) == str(self.channel.id):
            return self.channel
        return None


class _MemberRepository:
    async def get_effective_channel_relation(self, channel_id: str, user_id: int):
        return ChannelRelationEnum.OWNER


class _InviteApplicationService:
    def __init__(self) -> None:
        self.request_invite = AsyncMock(
            return_value={
                "outcome": "invite_created",
                "request_id": 301,
                "approval_instance_id": 501,
                "target_user_id": 201,
                "relation": "viewer",
                "model_id": "viewer",
                "include_children": False,
                "role_snapshot": {},
                "execution_state": "awaiting_approval",
            }
        )

    @asynccontextmanager
    async def scenario_guard(self, *, tenant_id: int):
        assert tenant_id == TENANT_ID
        yield


class _BindingMutationService:
    def __init__(self) -> None:
        self.bindings: list[dict] = []

    @asynccontextmanager
    async def transaction(self):
        service = self

        class _Transaction:
            snapshot = list(service.bindings)
            bindings = list(service.bindings)

            def ensure_owned(self) -> None:
                return None

            async def commit(self, bindings: list[dict]) -> None:
                self.bindings = list(bindings)
                service.bindings = list(bindings)

            async def restore(self) -> None:
                self.bindings = list(self.snapshot)
                service.bindings = list(self.snapshot)

        yield _Transaction()


def _service(
    *,
    invite_application_service: _InviteApplicationService | None = None,
) -> tuple[ChannelAuthorizationService, _InviteApplicationService, _BindingMutationService]:
    invite_service = invite_application_service or _InviteApplicationService()
    binding_service = _BindingMutationService()
    service = ChannelAuthorizationService(
        channel_repository=_ChannelRepository(),
        space_channel_member_repository=_MemberRepository(),
        invite_application_service=invite_service,
        relation_binding_mutation_service=binding_service,
    )
    service._actor_grant_permissions = AsyncMock(
        return_value={"manage_channel_owner", "manage_channel_manager", "manage_channel_user"}
    )
    service._validate_subjects_belong_to_channel_tenant = AsyncMock(return_value=None)
    service._users_belong_to_tenant = AsyncMock(return_value=True)
    service._active_explicit_user_ids = AsyncMock(return_value=set())
    service._target_user_name = AsyncMock(return_value="target-a")
    service._get_relation_models = AsyncMock(return_value=ChannelAuthorizationService._default_relation_models())
    service._get_bindings = AsyncMock(side_effect=lambda: list(binding_service.bindings))
    return service, invite_service, binding_service


def _grant(
    *,
    subject_type: str = "user",
    subject_id: int = 201,
    relation: ChannelRelationEnum = ChannelRelationEnum.VIEWER,
) -> ChannelGrantItem:
    return ChannelGrantItem(
        subject_type=subject_type,
        subject_id=subject_id,
        relation=relation,
        include_children=subject_type != "user",
        model_id=relation.value,
    )


def _role_snapshot() -> dict:
    model = next(item for item in ChannelAuthorizationService._default_relation_models() if item["id"] == "viewer")
    return {
        "name": model["name"],
        "relation": "viewer",
        "grant_tier": "usage",
        "permissions": sorted(set(model["permissions"])),
        "permissions_explicit": False,
    }


def _fingerprint(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _command(*, role_snapshot: dict | None = None, role_fingerprint: str | None = None) -> ResourceGrantCommand:
    snapshot = role_snapshot or _role_snapshot()
    return ResourceGrantCommand(
        tenant_id=TENANT_ID,
        request_id=301,
        request_fingerprint="request-fingerprint",
        resource_type="channel",
        resource_id="channel-88",
        inviter_user_id=101,
        target_user_id=201,
        relation="viewer",
        model_id="viewer",
        include_children=False,
        role_snapshot=snapshot,
        role_fingerprint=role_fingerprint or _fingerprint(snapshot),
    )


def _executor(service: ChannelAuthorizationService):
    executor_type = channel_module.ChannelResourceGrantExecutor
    return executor_type(authorization_service=service)


async def test_new_personal_user_only_creates_permission_owned_invite() -> None:
    service, invite_service, _ = _service()
    direct = AsyncMock()
    service._apply_direct_authorization = direct

    result = await service.authorize_channel(
        "channel-88",
        ChannelAuthorizeRequest(grants=[_grant()]),
        _User(),
    )

    direct.assert_not_awaited()
    invite_service.request_invite.assert_awaited_once()
    kwargs = invite_service.request_invite.await_args.kwargs
    assert kwargs["tenant_id"] == TENANT_ID
    assert kwargs["resource_type"] == "channel"
    assert kwargs["resource_id"] == "channel-88"
    assert kwargs["inviter_user_id"] == 101
    assert kwargs["target_user_id"] == 201
    assert kwargs["role_snapshot"] == _role_snapshot()
    assert result.invite_created_count == 1
    assert result.direct_applied_count == 0


async def test_department_group_existing_user_updates_and_remove_stay_direct() -> None:
    service, invite_service, _ = _service()
    service._active_explicit_user_ids.return_value = {201}
    direct = AsyncMock()
    service._apply_direct_authorization = direct
    request = ChannelAuthorizeRequest(
        grants=[
            _grant(subject_type="user", subject_id=201, relation=ChannelRelationEnum.MANAGER),
            _grant(subject_type="department", subject_id=301),
            _grant(subject_type="user_group", subject_id=401),
        ],
        revokes=[
            ChannelRevokeItem(
                subject_type="user",
                subject_id=202,
                relation=ChannelRelationEnum.VIEWER,
                include_children=False,
                model_id="viewer",
            )
        ],
    )

    result = await service.authorize_channel("channel-88", request, _User())

    direct.assert_awaited_once()
    direct_request = direct.await_args.args[1]
    assert {(item.subject_type, item.subject_id) for item in direct_request.grants} == {
        ("user", 201),
        ("department", 301),
        ("user_group", 401),
    }
    assert [(item.subject_type, item.subject_id) for item in direct_request.revokes] == [("user", 202)]
    invite_service.request_invite.assert_not_awaited()
    assert result.direct_applied_count == 4


async def test_channel_executor_revalidates_and_uses_the_only_permission_write_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _ = _service()
    permissions: list[SimpleNamespace] = []

    async def authorize(**kwargs) -> None:
        assert kwargs["object_type"] == "channel"
        assert kwargs["object_id"] == "channel-88"
        assert kwargs["revokes"] == []
        assert kwargs["enforce_fga_success"] is True
        assert kwargs["recovery_owner"] == "caller"
        grant = kwargs["grants"][0]
        permissions.append(
            SimpleNamespace(
                subject_type=grant.subject_type,
                subject_id=grant.subject_id,
                relation=grant.relation,
                model_id=grant.model_id,
                include_children=grant.include_children,
            )
        )

    authorize_mock = AsyncMock(side_effect=authorize)
    monkeypatch.setattr(PermissionService, "authorize", authorize_mock)
    monkeypatch.setattr(
        PermissionService,
        "get_resource_permissions",
        AsyncMock(side_effect=lambda *_args: list(permissions)),
    )
    executor = _executor(service)
    command = _command()

    await executor.execute(command)
    verification = await executor.verify(command)

    assert executor.resource_type == "channel"
    assert verification.applied is True
    assert verification.result_snapshot["request_id"] == 301
    authorize_mock.assert_awaited_once()
    assert service._users_belong_to_tenant.await_args.args == ({101, 201}, TENANT_ID)
    service._actor_grant_permissions.assert_awaited()


async def test_channel_executor_rejects_mismatched_tenant_context() -> None:
    service, _, _ = _service()
    token = set_current_tenant_id(TENANT_ID + 1)
    try:
        with pytest.raises(ValueError, match="tenant"):
            await _executor(service).execute(_command())
    finally:
        current_tenant_id.reset(token)


async def test_channel_executor_rejects_a_different_resource_type() -> None:
    service, _, _ = _service()

    with pytest.raises(ValueError, match="resource_type"):
        await _executor(service).execute(replace(_command(), resource_type="knowledge_space"))


@pytest.mark.parametrize(
    "invalid",
    [
        "channel_tenant",
        "private_channel",
        "creator_target",
        "user_tenant",
        "inviter_permission",
        "role_fingerprint",
    ],
)
async def test_channel_executor_f026_and_snapshot_boundaries_fail_closed(
    invalid: str,
) -> None:
    service, _, _ = _service()
    repository = service.channel_repository
    command = _command()
    if invalid == "channel_tenant":
        repository.channel.tenant_id = TENANT_ID + 1
    elif invalid == "private_channel":
        repository.channel.visibility = "private"
    elif invalid == "creator_target":
        repository.channel.user_id = command.target_user_id
    elif invalid == "user_tenant":
        service._users_belong_to_tenant.return_value = False
    elif invalid == "inviter_permission":
        service._actor_grant_permissions.return_value = set()
    else:
        command = _command(role_fingerprint="tampered")

    with pytest.raises(ChannelPermissionDeniedError):
        await _executor(service).execute(command)


async def test_authoritative_verify_and_redelivery_do_not_repeat_an_uncertain_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _ = _service()
    permissions: list[SimpleNamespace] = []

    async def authorize(**kwargs) -> None:
        grant = kwargs["grants"][0]
        permissions.append(
            SimpleNamespace(
                subject_type="user",
                subject_id=grant.subject_id,
                relation=grant.relation,
                model_id=grant.model_id,
                include_children=grant.include_children,
            )
        )
        raise RuntimeError("openfga response lost")

    authorize_mock = AsyncMock(side_effect=authorize)
    monkeypatch.setattr(PermissionService, "authorize", authorize_mock)
    monkeypatch.setattr(
        PermissionService,
        "get_resource_permissions",
        AsyncMock(side_effect=lambda *_args: list(permissions)),
    )
    executor = _executor(service)
    command = _command()

    with pytest.raises(RuntimeError, match="response lost"):
        await executor.execute(command)
    assert (await executor.verify(command)).applied is True

    await executor.execute(command)

    authorize_mock.assert_awaited_once()
    assert (await executor.verify(command)).applied is True


async def test_response_loss_binding_commit_failure_compensates_the_authoritative_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, binding_service = _service()
    permissions: list[SimpleNamespace] = []
    restored = False

    @asynccontextmanager
    async def failing_transaction():
        class _Transaction:
            bindings: list[dict] = []

            def ensure_owned(self) -> None:
                return None

            async def commit(self, _bindings: list[dict]) -> None:
                raise RuntimeError("binding commit failed")

            async def restore(self) -> None:
                nonlocal restored
                restored = True

        yield _Transaction()

    async def authorize(**kwargs) -> None:
        if kwargs["grants"]:
            grant = kwargs["grants"][0]
            permissions.append(
                SimpleNamespace(
                    subject_type="user",
                    subject_id=grant.subject_id,
                    relation=grant.relation,
                )
            )
            raise RuntimeError("openfga response lost")
        permissions.clear()

    binding_service.transaction = failing_transaction
    monkeypatch.setattr(PermissionService, "authorize", AsyncMock(side_effect=authorize))
    monkeypatch.setattr(
        PermissionService,
        "get_resource_permissions",
        AsyncMock(side_effect=lambda *_args: list(permissions)),
    )
    executor = _executor(service)
    command = _command()

    with pytest.raises(ChannelAuthorizationSyncError):
        await executor.execute(command)

    assert restored is True
    assert permissions == []
    assert (await executor.verify(command)).applied is False


async def test_grant_failure_remains_a_business_failure_without_approval_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _ = _service()
    monkeypatch.setattr(
        PermissionService,
        "authorize",
        AsyncMock(side_effect=RuntimeError("openfga unavailable")),
    )
    monkeypatch.setattr(
        PermissionService,
        "get_resource_permissions",
        AsyncMock(return_value=[]),
    )
    executor = _executor(service)

    with pytest.raises(RuntimeError, match="openfga unavailable"):
        await executor.execute(_command())

    assert (await executor.verify(_command())).applied is False


def test_channel_authorization_has_no_approval_invite_or_payload_persistence_dependency() -> None:
    source = inspect.getsource(channel_module)
    forbidden = (
        "bisheng.approval.domain.services.resource_user_invite",
        "bisheng.approval.domain.repositories",
        "ApprovalInstanceRepository",
        "ApprovalOutbox",
        "payload_snapshot",
    )
    assert not any(value in source for value in forbidden)
