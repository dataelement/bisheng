"""Workflow and assistant F048 business authorization adapters."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.api.services.assistant import AssistantResourceAuthorizationPort
from bisheng.api.services.f048_application_permission import (
    ApplicationPermissionRecord,
    F048ApplicationPermissionAdapter,
)
from bisheng.api.services.workflow import WorkflowResourceAuthorizationPort
from bisheng.common.errcode.permission import (
    InvalidCatalogActionError,
    PermissionInvalidResourceError,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class _Loader:
    def __init__(self, records: tuple[ApplicationPermissionRecord, ...]):
        self.records = {(record.resource_type, record.resource_id): record for record in records}

    async def load_permission_record(self, resource_type, resource_id):
        return self.records.get((resource_type, resource_id))


class _Permission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def check_action(self, actor, target, action):
        self.calls.append(("check", (actor, target, action)))
        return True

    async def batch_check_actions(self, actor, targets, action):
        self.calls.append(("batch", (actor, targets, action)))
        return tuple(True for _ in targets)

    async def authorize_created(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"status": "FINALIZED"}

    async def project_delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"status": "FINALIZED"}


def _record(
    *,
    resource_type: str = "workflow",
    resource_id: str = "wf-1",
    tenant_id: int = 5,
    status: str = "OFFLINE",
    system_owned: bool = False,
    system_allowlisted: bool = False,
) -> ApplicationPermissionRecord:
    return ApplicationPermissionRecord(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        owner_user_id=7,
        permission_version=2,
        context_version=f"{resource_type}-{resource_id}-v2",
        system_owned=system_owned,
        system_allowlisted=system_allowlisted,
    )


def _actor(tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=tenant_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_type,action",
    (
        ("workflow", "visible"),
        ("workflow", "edit"),
        ("workflow", "delete"),
        ("workflow", "share"),
        ("workflow", "publish"),
        ("assistant", "use"),
        ("assistant", "edit"),
    ),
)
async def test_application_actions_use_exact_verified_targets(
    resource_type,
    action,
) -> None:
    record = _record(
        resource_type=resource_type,
        resource_id=f"{resource_type}-1",
    )
    permission = _Permission()
    adapter = F048ApplicationPermissionAdapter(
        loader=_Loader((record,)),
        permission=permission,
    )

    assert await adapter.check_action(
        resource_type=resource_type,
        resource_id=record.resource_id,
        actor=_actor(),
        action=action,
    )
    _, (_, target, exact_action) = permission.calls[0]
    assert target.resource_type == resource_type
    assert exact_action == action


@pytest.mark.asyncio
async def test_business_ports_fix_their_resource_type() -> None:
    workflow = _record()
    assistant = _record(
        resource_type="assistant",
        resource_id="assistant-1",
    )
    adapter = F048ApplicationPermissionAdapter(
        loader=_Loader((workflow, assistant)),
        permission=_Permission(),
    )

    workflow_port = WorkflowResourceAuthorizationPort(adapter)
    assistant_port = AssistantResourceAuthorizationPort(adapter)
    workflow_target = await workflow_port.resolve_permission_target(
        resource_id="wf-1",
        actor=_actor(),
        action="visible",
    )
    assistant_target = await assistant_port.resolve_permission_target(
        resource_id="assistant-1",
        actor=_actor(),
        action="visible",
    )

    assert workflow_target.resource_type == "workflow"
    assert assistant_target.resource_type == "assistant"


@pytest.mark.asyncio
async def test_create_list_and_delete_use_durable_permission_facade() -> None:
    first = _record()
    second = replace(
        first,
        resource_id="wf-2",
        context_version="workflow-wf-2-v1",
    )
    permission = _Permission()
    adapter = F048ApplicationPermissionAdapter(
        loader=_Loader((first, second)),
        permission=permission,
    )

    await adapter.authorize_created(record=first, actor=_actor())
    decisions = await adapter.batch_check_loaded(
        records=(first, second),
        actor=_actor(),
        action="visible",
    )
    await adapter.project_delete(record=second, actor=_actor())

    assert decisions == (True, True)
    assert [call[0] for call in permission.calls] == [
        "create",
        "batch",
        "delete",
    ]
    assert permission.calls[0][1]["protected"] is True


@pytest.mark.asyncio
async def test_builtin_requires_business_predicate_and_action_allowlist() -> None:
    builtin = _record(
        system_owned=True,
        system_allowlisted=True,
    )
    not_allowlisted = replace(builtin, system_allowlisted=False)
    permission = _Permission()
    adapter = F048ApplicationPermissionAdapter(
        loader=_Loader((builtin,)),
        permission=permission,
    )

    assert await adapter.check_action(
        resource_type="workflow",
        resource_id="wf-1",
        actor=_actor(),
        action="use",
    )
    with pytest.raises(InvalidCatalogActionError):
        await adapter.check_action(
            resource_type="workflow",
            resource_id="wf-1",
            actor=_actor(),
            action="edit",
        )

    blocked = F048ApplicationPermissionAdapter(
        loader=_Loader((not_allowlisted,)),
        permission=permission,
    )
    with pytest.raises(PermissionInvalidResourceError):
        await blocked.resolve_permission_target(
            resource_type="workflow",
            resource_id="wf-1",
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record",
    (
        None,
        _record(tenant_id=6),
        _record(status="DELETED"),
        _record(resource_type="tool"),
    ),
)
async def test_invalid_business_application_facts_fail_closed(record) -> None:
    adapter = F048ApplicationPermissionAdapter(
        loader=_Loader(tuple(row for row in (record,) if row is not None)),
        permission=_Permission(),
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_type="workflow",
            resource_id="wf-1",
            actor=_actor(),
            action="visible",
        )
