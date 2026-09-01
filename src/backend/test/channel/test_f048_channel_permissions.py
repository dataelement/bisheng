"""F048 channel action and Grant-source contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.channel.domain.services.channel_service import (
    ChannelResourceAuthorizationPort,
)
from bisheng.channel.domain.services.f048_channel_permission import (
    ChannelPermissionRecord,
    ChannelSubjectRecord,
    F048ChannelPermissionAdapter,
)
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionInvalidResourceError,
)
from bisheng.permission.domain.services.grant_source_service import (
    GrantSourceService,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class _Loader:
    def __init__(
        self,
        channel: ChannelPermissionRecord | None,
        subjects: tuple[ChannelSubjectRecord, ...] = (),
    ) -> None:
        self.channel = channel
        self.subjects = {(subject.subject_type, subject.subject_id): subject for subject in subjects}

    async def load_permission_record(self, resource_id):
        if self.channel and self.channel.resource_id == resource_id:
            return self.channel
        return None

    async def load_subject(self, subject_type, subject_id):
        return self.subjects.get((subject_type, subject_id))


class _VersionedLoader(_Loader):
    def __init__(
        self,
        channel: ChannelPermissionRecord,
        versions: tuple[int, ...],
    ) -> None:
        super().__init__(channel)
        self.versions = iter(versions)

    async def load_permission_record(self, resource_id):
        record = await super().load_permission_record(resource_id)
        if record is None:
            return None
        version = next(self.versions)
        return replace(
            record,
            permission_version=version,
            context_version=f"channel-v{version}",
        )


class _Permission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None
        self.clear_outcomes = [
            {"status": "FINALIZED"},
            None,
        ]

    async def check_action(self, actor, target, action):
        self.calls.append(("check", (actor, target, action)))
        if self.error:
            raise self.error
        return True

    async def authorize_created(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"status": "FINALIZED"}

    async def project_delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"status": "FINALIZED"}

    async def sync_business_source_model(self, **kwargs):
        self.calls.append(("membership", kwargs))
        return {"status": "FINALIZED"}

    async def remove_ordinary_sources(self, **kwargs):
        self.calls.append(("clear", kwargs))
        return self.clear_outcomes.pop(0)


def _actor(tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=tenant_id)


def _channel(
    *,
    tenant_id: int = 5,
    shared_read_only: bool = False,
    system_read_only: bool = False,
) -> ChannelPermissionRecord:
    return ChannelPermissionRecord(
        tenant_id=tenant_id,
        resource_id="channel-1",
        status="ACTIVE",
        creator_user_id=7,
        permission_version=3,
        context_version="channel-v3",
        shared_read_only=shared_read_only,
        system_read_only=system_read_only,
    )


def _subjects() -> tuple[ChannelSubjectRecord, ...]:
    return (
        ChannelSubjectRecord(
            tenant_id=5,
            subject_type="user",
            subject_id="8",
            status="ACTIVE",
        ),
        ChannelSubjectRecord(
            tenant_id=5,
            subject_type="department",
            subject_id="17",
            status="ACTIVE",
        ),
        ChannelSubjectRecord(
            tenant_id=5,
            subject_type="user_group",
            subject_id="23",
            status="ACTIVE",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    ("visible", "edit", "delete", "manage_permission"),
)
async def test_channel_uses_exact_action_after_business_validation(action) -> None:
    permission = _Permission()
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel()),
        source_service=GrantSourceService(),
        permission=permission,
    )

    assert await adapter.check_action(
        resource_id="channel-1",
        actor=_actor(),
        action=action,
    )
    assert permission.calls[0][1][2] == action


@pytest.mark.asyncio
async def test_channel_business_port_builds_verified_target() -> None:
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel()),
        source_service=GrantSourceService(),
        permission=_Permission(),
    )
    target = await ChannelResourceAuthorizationPort(adapter).resolve_permission_target(
        resource_id="channel-1",
        actor=_actor(),
        action="visible",
    )
    assert target.resource_type == "channel"


@pytest.mark.asyncio
async def test_direct_department_and_group_sources_are_server_canonical() -> None:
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel(), _subjects()),
        source_service=GrantSourceService(),
        permission=_Permission(),
    )
    direct = await adapter.canonical_source(
        source_id=1,
        actor=_actor(),
        subject_type="user",
        subject_id="8",
        include_children=False,
    )
    department = await adapter.canonical_source(
        source_id=2,
        actor=_actor(),
        subject_type="department",
        subject_id="17",
        include_children=True,
    )
    group = await adapter.canonical_source(
        source_id=3,
        actor=_actor(),
        subject_type="user_group",
        subject_id="23",
        include_children=False,
    )

    assert direct.projected_subject == "user:8"
    assert department.projected_subject == "department:17#subtree_member"
    assert group.projected_subject == "user_group:23#member"
    assert {direct.source_type, department.source_type, group.source_type} == {
        "DIRECT",
        "DEPARTMENT",
        "USER_GROUP",
    }


@pytest.mark.asyncio
async def test_creator_is_projected_as_protected_source() -> None:
    permission = _Permission()
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel()),
        source_service=GrantSourceService(),
        permission=permission,
    )

    await adapter.authorize_created(record=_channel(), actor=_actor())

    create = permission.calls[0][1]
    assert create["owner_user_id"] == 7
    assert create["source_type"] == "CREATOR"
    assert create["protected"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel",
    (
        _channel(tenant_id=1, shared_read_only=True),
        _channel(tenant_id=1, system_read_only=True),
    ),
)
async def test_shared_and_system_channels_are_read_only(channel) -> None:
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(channel),
        source_service=GrantSourceService(),
        permission=_Permission(),
    )

    assert await adapter.check_action(
        resource_id="channel-1",
        actor=_actor(),
        action="visible",
    )
    with pytest.raises(InvalidCatalogActionError):
        await adapter.check_action(
            resource_id="channel-1",
            actor=_actor(),
            action="edit",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel",
    (
        _channel(shared_read_only=True),
        _channel(system_read_only=True),
    ),
)
async def test_read_only_marker_does_not_lock_owner_tenant(channel) -> None:
    permission = _Permission()
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(channel),
        source_service=GrantSourceService(),
        permission=permission,
    )

    assert await adapter.check_action(
        resource_id="channel-1",
        actor=_actor(),
        action="manage_permission",
    )
    assert permission.calls[0][1][2] == "manage_permission"


@pytest.mark.asyncio
async def test_wrong_tenant_and_fga_failure_fail_closed() -> None:
    permission = _Permission()
    unshared = F048ChannelPermissionAdapter(
        loader=_Loader(_channel(tenant_id=6)),
        source_service=GrantSourceService(),
        permission=permission,
    )
    with pytest.raises(PermissionInvalidResourceError):
        await unshared.resolve_permission_target(
            resource_id="channel-1",
            actor=_actor(),
            action="visible",
        )

    permission.error = PermissionFGAUnavailableError()
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel()),
        source_service=GrantSourceService(),
        permission=permission,
    )
    with pytest.raises(PermissionFGAUnavailableError):
        await adapter.check_action(
            resource_id="channel-1",
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
async def test_channel_membership_is_canonical_business_source() -> None:
    permission = _Permission()
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel(), _subjects()),
        source_service=GrantSourceService(),
        permission=permission,
    )

    await adapter.sync_membership(
        resource_id="channel-1",
        operator_user_id=7,
        subject_user_id=8,
        model_key="manager",
    )

    payload = permission.calls[0][1]
    assert payload["model_key"] == "manager"
    assert payload["source"].source_type == "CHANNEL_MEMBERSHIP"
    assert payload["source"].source_ref == "channel-1:user:8"
    assert payload["source"].projected_subject == "user:8"
    assert payload["actor"].current_tenant_id == 5


@pytest.mark.asyncio
async def test_channel_delete_and_private_switch_use_durable_runtime() -> None:
    permission = _Permission()
    adapter = F048ChannelPermissionAdapter(
        loader=_Loader(_channel()),
        source_service=GrantSourceService(),
        permission=permission,
    )

    await adapter.project_delete(record=_channel(), actor=_actor())
    await adapter.remove_ordinary_sources(
        record=_channel(),
        actor=_actor(),
    )

    assert [name for name, _ in permission.calls] == [
        "delete",
        "clear",
        "clear",
    ]


@pytest.mark.asyncio
async def test_private_switch_drains_every_bounded_grant_batch() -> None:
    permission = _Permission()
    permission.clear_outcomes = [
        {"resource_version": 4},
        {"resource_version": 5},
        None,
    ]
    adapter = F048ChannelPermissionAdapter(
        loader=_VersionedLoader(_channel(), (3, 4, 5)),
        source_service=GrantSourceService(),
        permission=permission,
    )

    await adapter.remove_ordinary_sources(
        record=_channel(),
        actor=_actor(),
    )

    clear_calls = [payload for name, payload in permission.calls if name == "clear"]
    assert len(clear_calls) == 3
    assert [call["idempotency_key"] for call in clear_calls] == [
        "channel-private:channel-1:3",
        "channel-private:channel-1:4",
        "channel-private:channel-1:5",
    ]
