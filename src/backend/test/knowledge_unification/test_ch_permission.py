"""T155: channels retain their business bounds when use becomes visibility."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.channel.domain.services.f048_channel_permission import (
    READ_ONLY_CHANNEL_ACTIONS,
    ChannelPermissionRecord,
    F048ChannelPermissionAdapter,
)
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionFGAUnavailableError,
    PermissionInvalidResourceError,
)
from bisheng.permission.application.identity import PermissionActor
from bisheng.permission.domain.services.grant_source_service import GrantSourceService


@pytest.fixture
def channel_permission():
    record = ChannelPermissionRecord(
        tenant_id=101,
        resource_id="channel-a",
        status="ACTIVE",
        creator_user_id=7,
        permission_version=3,
        context_version="channel-v3",
        shared_read_only=True,
    )
    loader = SimpleNamespace(load_permission_record=AsyncMock(return_value=record))
    permission = SimpleNamespace(check_action=AsyncMock(return_value=True))
    adapter = F048ChannelPermissionAdapter(loader=loader, source_service=GrantSourceService(), permission=permission)
    actor = PermissionActor(subject_type="user", subject_id=15, tenant_id=202)
    return SimpleNamespace(record=record, loader=loader, permission=permission, adapter=adapter, actor=actor)


def test_channel_readonly_action_set_contains_only_canonical_visibility():
    assert READ_ONLY_CHANNEL_ACTIONS == frozenset({"visible"})


@pytest.mark.parametrize("marker", ["shared_read_only", "system_read_only"])
async def test_shared_or_system_channel_visibility_uses_exact_business_target(channel_permission, marker):
    case = channel_permission
    case.loader.load_permission_record.return_value = replace(
        case.record, shared_read_only=marker == "shared_read_only", system_read_only=marker == "system_read_only"
    )
    assert await case.adapter.check_action(resource_id="channel-a", actor=case.actor, action="visible")
    actor, target, action = case.permission.check_action.await_args.args
    assert actor is case.actor and action == "visible"
    assert (target.tenant_id, target.resource_type, target.resource_id) == (101, "channel", "channel-a")


@pytest.mark.parametrize("action", ["use", "edit", "delete", "manage_permission"])
async def test_cross_tenant_readonly_adapter_has_no_independent_use_or_management_action(channel_permission, action):
    case = channel_permission
    with pytest.raises(InvalidCatalogActionError):
        await case.adapter.check_action(resource_id="channel-a", actor=case.actor, action=action)
    case.permission.check_action.assert_not_awaited()


@pytest.mark.parametrize("legacy_action", ["use", "use_kb"])
async def test_legacy_action_is_normalized_before_the_channel_adapter(channel_permission, monkeypatch, legacy_action):
    from bisheng.permission.application import business_authorization as module

    case = channel_permission
    identity = object()

    async def resolve(*, resource_type, resource_id, actor, action):
        assert resource_type == "channel" and actor is case.actor and action == "visible"
        return await case.adapter.resolve_permission_target(resource_id=resource_id, actor=actor, action=action)

    monkeypatch.setattr(module, "get_f048_resource_registry", AsyncMock(return_value=SimpleNamespace(resolve=resolve)))
    monkeypatch.setattr(module, "get_f048_runtime", AsyncMock(return_value=case.permission))
    assert await module.check_business_action(
        identity, resource_type="channel", resource_id="channel-a", action=legacy_action, actor=case.actor
    )
    assert case.permission.check_action.await_args.args[0] is case.actor
    assert case.permission.check_action.await_args.args[2] == "visible"


@pytest.mark.parametrize("action", ["edit", "delete", "manage_permission"])
async def test_readonly_marker_does_not_remove_original_owner_tenant_management(channel_permission, action):
    case = channel_permission
    actor = PermissionActor(subject_type="user", subject_id=15, tenant_id=101)
    assert await case.adapter.check_action(resource_id="channel-a", actor=actor, action=action)
    assert case.permission.check_action.await_args.args[0] is actor
    assert case.permission.check_action.await_args.args[2] == action


@pytest.mark.parametrize("change", ["missing", "inactive", "owner", "id", "unshared"])
async def test_visibility_does_not_bypass_channel_lifecycle_or_tenant(channel_permission, change):
    case = channel_permission
    changes = {
        "inactive": {"status": "INACTIVE"},
        "owner": {"creator_user_id": 0},
        "id": {"resource_id": "other"},
        "unshared": {"shared_read_only": False},
    }
    case.loader.load_permission_record.return_value = (
        None if change == "missing" else replace(case.record, **changes[change])
    )
    with pytest.raises(PermissionInvalidResourceError):
        await case.adapter.check_action(resource_id="channel-a", actor=case.actor, action="visible")
    case.permission.check_action.assert_not_awaited()


async def test_permission_outage_never_grants_readonly_access(channel_permission):
    case = channel_permission
    case.permission.check_action.side_effect = PermissionFGAUnavailableError()
    with pytest.raises(PermissionFGAUnavailableError):
        await case.adapter.check_action(resource_id="channel-a", actor=case.actor, action="visible")
