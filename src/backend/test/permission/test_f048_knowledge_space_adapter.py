"""F048 authorization boundary for knowledge spaces and libraries."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import (
    InvalidPermissionModeError,
    PermissionInvalidResourceError,
)
from bisheng.knowledge.domain.services import knowledge_permission_service as permission_module
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    KnowledgeContainerDaoPermissionLoader,
    KnowledgeContainerPermissionRecord,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class _Loader:
    def __init__(self, record: KnowledgeContainerPermissionRecord | None):
        self.record = record
        self.calls: list[tuple[str, str]] = []

    async def load_permission_record(self, resource_type, resource_id):
        self.calls.append((resource_type, resource_id))
        return self.record


class _Permission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def check_action(self, actor, target, action):
        self.calls.append(("check", (actor, target, action)))
        return True

    async def batch_check_actions(self, actor, targets, action):
        self.calls.append(("batch", (actor, targets, action)))
        return tuple(True for _ in targets)

    async def authorize_created(
        self,
        *,
        actor,
        target,
        owner_user_id,
        mode,
        protected,
    ):
        self.calls.append(
            (
                "create",
                (actor, target, owner_user_id, mode, protected),
            )
        )
        return {"status": "FINALIZED"}

    async def project_copy(
        self,
        *,
        actor,
        source,
        target,
        owner_user_id,
        mode,
    ):
        self.calls.append(("copy", (actor, source, target, owner_user_id, mode)))
        return {"status": "FINALIZED"}

    async def project_delete(self, *, actor, target):
        self.calls.append(("delete", (actor, target)))
        return {"status": "FINALIZED"}


class _VersionPort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def get_permission_version(self, **kwargs):
        self.calls.append(kwargs)
        return 3, "permission-context-v3"


def _record(
    *,
    resource_type: str = "knowledge_library",
    tenant_id: int = 5,
    status: str = "PUBLISHED",
    kind: str = "NORMAL",
    resource_id: str = "11",
    owner_user_id: int = 7,
) -> KnowledgeContainerPermissionRecord:
    return KnowledgeContainerPermissionRecord(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        kind=kind,
        owner_user_id=owner_user_id,
        permission_version=3,
        context_version="knowledge-v3",
    )


def _actor(tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_container_loader_reads_permission_version_through_facade(
    monkeypatch,
) -> None:
    knowledge_row = SimpleNamespace(
        id=2,
        tenant_id=5,
        type=0,
        state=1,
        update_time=None,
        user_id=7,
    )
    monkeypatch.setattr(
        permission_module.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=knowledge_row),
    )
    version_port = _VersionPort()

    record = await KnowledgeContainerDaoPermissionLoader(version_port).load_permission_record(
        "knowledge_library",
        "2",
    )

    assert record is not None
    assert record.resource_id == "2"
    assert record.permission_version == 3
    assert version_port.calls == [
        {
            "tenant_id": 5,
            "resource_type": "knowledge_library",
            "resource_id": "2",
        }
    ]


@pytest.mark.asyncio
async def test_container_service_verifies_business_facts_before_action() -> None:
    loader = _Loader(_record())
    permission = _Permission()
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=loader,
        permission=permission,
    )

    target = await adapter.resolve_permission_target(
        resource_id="11",
        resource_type="knowledge_library",
        actor=_actor(),
        action="edit",
    )
    allowed = await adapter.check_action(
        resource_id="11",
        resource_type="knowledge_library",
        actor=_actor(),
        action="edit",
    )

    assert allowed is True
    assert target.tenant_id == 5
    assert target.parent_id is None
    assert target.resource_version == 3
    assert loader.calls == [
        ("knowledge_library", "11"),
        ("knowledge_library", "11"),
    ]
    assert permission.calls[0][0] == "check"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record,requested_type",
    (
        (None, "knowledge_library"),
        (_record(tenant_id=6), "knowledge_library"),
        (_record(status="COPYING"), "knowledge_library"),
        (_record(kind="SPACE"), "knowledge_library"),
        (
            _record(
                resource_type="knowledge_space",
                kind="NORMAL",
            ),
            "knowledge_space",
        ),
    ),
)
async def test_missing_tenant_status_and_kind_are_hidden(
    record,
    requested_type,
) -> None:
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=_Loader(record),
        permission=_Permission(),
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_id="11",
            resource_type=requested_type,
            actor=_actor(),
            action="visible",
        )


@pytest.mark.asyncio
async def test_spaces_and_libraries_are_fixed_custom_with_protected_owner() -> None:
    record = _record(
        resource_type="knowledge_space",
        kind="SPACE",
    )
    permission = _Permission()
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=_Loader(record),
        permission=permission,
    )

    await adapter.authorize_created(record=record, actor=_actor())
    with pytest.raises(InvalidPermissionModeError):
        await adapter.switch_mode(
            record=record,
            actor=_actor(),
            target_mode="INHERIT",
        )

    _, create = permission.calls[0]
    assert create[2:] == (7, "CUSTOM", True)


@pytest.mark.asyncio
async def test_loaded_list_copy_and_delete_use_only_verified_targets() -> None:
    first = _record(resource_id="11")
    second = replace(first, resource_id="12", context_version="knowledge-v4")
    permission = _Permission()
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=_Loader(first),
        permission=permission,
    )

    decisions = await adapter.batch_check_loaded(
        records=(first, second),
        actor=_actor(),
        action="visible",
    )
    await adapter.project_copy(
        source=first,
        target=second,
        actor=_actor(),
        new_owner_user_id=9,
    )
    await adapter.project_delete(record=first, actor=_actor())

    assert decisions == (True, True)
    assert [call[0] for call in permission.calls] == [
        "batch",
        "copy",
        "delete",
    ]
