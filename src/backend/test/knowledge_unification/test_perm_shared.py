"""F118 system/shared visibility boundaries. AC-78, AC-79, AC-80, AC-81, AC-83."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.services.f048_application_permission import (
    ApplicationPermissionRecord,
    F048ApplicationPermissionAdapter,
)
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.tenant.domain.repositories.resource_share_repository import (
    SharedResourceRecord,
    SharedResourceRepository,
)
from bisheng.tenant.domain.services.resource_share_service import ResourceShareService


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("This permission contract test must not open a network connection")

    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setattr("socket.socket.connect_ex", reject)
    monkeypatch.setattr("socket.create_connection", reject)


def actor():
    return PermissionActor(user_id=7, current_tenant_id=5)


def application(resource_type="workflow"):
    return ApplicationPermissionRecord(
        tenant_id=5,
        resource_type=resource_type,
        resource_id=f"{resource_type}-1",
        status="OFFLINE",
        owner_user_id=0,
        permission_version=0,
        context_version="application-v0",
        system_owned=True,
        system_allowlisted=True,
    )


def application_adapter(record):
    permission = SimpleNamespace(
        check_action=AsyncMock(return_value=True),
        authorize_system_owned=AsyncMock(return_value="created"),
    )
    return (
        F048ApplicationPermissionAdapter(
            loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)),
            permission=permission,
        ),
        permission,
    )


@pytest.mark.parametrize("resource_type", ("workflow", "assistant"))
async def test_system_application_creation_and_use_emit_only_visibility(resource_type):
    record = application(resource_type)
    adapter, permission = application_adapter(record)
    principal = actor()

    assert await adapter.authorize_created(record=record, actor=principal) == "created"
    created = permission.authorize_system_owned.call_args.kwargs
    assert created["actor"] is principal
    assert created["action_codes"] == ("visible",)
    assert created["target"].tenant_id == record.tenant_id
    assert created["target"].resource_type == resource_type
    assert created["target"].resource_id == record.resource_id
    assert await adapter.check_action(
        resource_type=resource_type, resource_id=record.resource_id, actor=principal, action="visible"
    )
    assert permission.check_action.call_args.args[0] is principal
    assert permission.check_action.call_args.args[2] == "visible"


@pytest.mark.parametrize("resource_type", ("workflow", "assistant"))
@pytest.mark.parametrize("action", ("use", "edit", "delete", "publish", "share", "manage_permission", "download"))
async def test_system_application_rejects_other_actions_before_permission_io(resource_type, action):
    record = application(resource_type)
    adapter, permission = application_adapter(record)
    with pytest.raises(InvalidCatalogActionError):
        await adapter.check_action(
            resource_type=resource_type, resource_id=record.resource_id, actor=actor(), action=action
        )
    permission.check_action.assert_not_awaited()


@pytest.mark.parametrize("change", ({"system_allowlisted": False}, {"tenant_id": 6}, {"status": "DELETED"}))
async def test_system_application_retains_business_predicates(change):
    record = replace(application(), **change)
    adapter, permission = application_adapter(record)
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.check_action(
            resource_type="workflow", resource_id=record.resource_id, actor=actor(), action="visible"
        )
    permission.check_action.assert_not_awaited()


@pytest.mark.parametrize("action", ("publish", "share", "manage_permission", "edit", "delete"))
async def test_ordinary_application_keeps_each_management_action(action):
    record = replace(application(), owner_user_id=7, system_owned=False, system_allowlisted=False)
    adapter, permission = application_adapter(record)
    assert await adapter.check_action(
        resource_type="workflow", resource_id=record.resource_id, actor=actor(), action=action
    )
    assert permission.check_action.call_args.args[2] == action


def shared_service(resource_type="knowledge_library", *, allowed=True, record_changes=None, topology_valid=True):
    record = SharedResourceRecord(1, resource_type, "resource-1", "ACTIVE", True, 3, "resource-v3")
    if record_changes:
        record = replace(record, **record_changes)
    loader = SimpleNamespace(load_by_ids=AsyncMock(return_value=(record,)))
    permission = SimpleNamespace(check_system_action=AsyncMock(return_value=allowed))
    topology = SimpleNamespace(is_root_to_child=AsyncMock(return_value=topology_valid))
    return (
        ResourceShareService(
            repository=SharedResourceRepository(loader), system_permission=permission, topology=topology
        ),
        loader,
        permission,
        topology,
    )


@pytest.mark.parametrize(
    "resource_type",
    ("knowledge_library", "knowledge_space", "folder", "knowledge_file", "workflow", "assistant", "tool", "channel"),
)
async def test_shared_visibility_preserves_actor_exact_target_and_root_topology(resource_type):
    service, loader, permission, topology = shared_service(resource_type)
    principal = actor()
    target = await service.resolve_shared_target(
        actor=principal, resource_type=resource_type, resource_id="resource-1", action="visible"
    )
    permission.check_system_action.assert_awaited_once_with(principal, resource_type, "resource-1", "visible")
    loader.load_by_ids.assert_awaited_once_with(resource_type, ("resource-1",))
    topology.is_root_to_child.assert_awaited_once_with(1, 5)
    assert (target.tenant_id, target.resource_type, target.resource_id) == (1, resource_type, "resource-1")


@pytest.mark.parametrize("resource_type", ("knowledge_library", "workflow", "assistant", "tool"))
@pytest.mark.parametrize("action", ("use", "download", "edit", "delete", "share", "publish", "manage_permission"))
async def test_shared_read_only_resources_reject_retired_and_management_actions(resource_type, action):
    service, loader, permission, topology = shared_service(resource_type)
    with pytest.raises(InvalidCatalogActionError):
        await service.resolve_shared_target(
            actor=actor(), resource_type=resource_type, resource_id="resource-1", action=action
        )
    permission.check_system_action.assert_not_awaited()
    loader.load_by_ids.assert_not_awaited()
    topology.is_root_to_child.assert_not_awaited()


@pytest.mark.parametrize("resource_type", ("knowledge_space", "folder", "knowledge_file"))
async def test_document_shared_download_remains_a_separate_action(resource_type):
    service, _, permission, _ = shared_service(resource_type)
    principal = actor()
    await service.resolve_shared_target(
        actor=principal, resource_type=resource_type, resource_id="resource-1", action="download"
    )
    permission.check_system_action.assert_awaited_once_with(principal, resource_type, "resource-1", "download")


@pytest.mark.parametrize(
    "record_changes,topology_valid",
    (({"status": "INACTIVE"}, True), ({"shareable": False}, True), ({"owner_tenant_id": 5}, True), ({}, False)),
)
async def test_shared_visibility_retains_resource_and_topology_restrictions(record_changes, topology_valid):
    service, _, _, _ = shared_service(record_changes=record_changes, topology_valid=topology_valid)
    with pytest.raises(PermissionInvalidResourceError):
        await service.resolve_shared_target(
            actor=actor(), resource_type="knowledge_library", resource_id="resource-1", action="visible"
        )


async def test_shared_denial_does_not_load_cross_tenant_business_data():
    service, loader, _, topology = shared_service(allowed=False)
    with pytest.raises(PermissionInvalidResourceError):
        await service.resolve_shared_target(
            actor=actor(), resource_type="knowledge_library", resource_id="resource-1", action="visible"
        )
    loader.load_by_ids.assert_not_awaited()
    topology.is_root_to_child.assert_not_awaited()


@pytest.mark.parametrize("resource_type", ("knowledge_space", "workflow", "assistant", "tool", "channel"))
def test_business_resource_root_to_child_write_path_stays_disabled(resource_type):
    with pytest.raises(ValueError, match="Unsupported resource type"):
        ResourceShareService._validate_type(resource_type)
    ResourceShareService._validate_type(resource_type, legacy=True)
