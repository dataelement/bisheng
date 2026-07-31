"""F048 folder/file business lifecycle authorization contracts."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.knowledge.domain.services import knowledge_permission_service as permission_module
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeFilePermissionAdapter,
    KnowledgeFileDaoPermissionLoader,
    KnowledgeFilePermissionRecord,
)
from bisheng.permission.domain.services.permission_action_service import (
    PermissionActor,
)


class _Loader:
    def __init__(self, records: tuple[KnowledgeFilePermissionRecord, ...]):
        self.records = {(record.resource_type, record.resource_id): record for record in records}

    async def load_permission_record(self, resource_type, resource_id):
        return self.records.get((resource_type, resource_id))


class _Permission:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def check_action(self, actor, target, action):
        self.calls.append(("check", {"actor": actor, "target": target, "action": action}))
        return True

    async def authorize_created(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"status": "FINALIZED"}

    async def project_parent_change(self, **kwargs):
        self.calls.append(("move", kwargs))
        return {"status": "FINALIZED"}

    async def project_copy(self, **kwargs):
        self.calls.append(("copy", kwargs))
        return {"status": "FINALIZED"}

    async def project_delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return {"status": "FINALIZED"}


class _VersionPort:
    def __init__(self) -> None:
        self.version_calls: list[dict] = []
        self.mode_targets: list[object] = []

    async def get_permission_version(self, **kwargs):
        self.version_calls.append(kwargs)
        return 4, "permission-context-v4"

    async def mode_for_target(self, target):
        self.mode_targets.append(target)
        return SimpleNamespace(mode="INHERIT")


def _actor(tenant_id: int = 5) -> PermissionActor:
    return PermissionActor(user_id=7, current_tenant_id=tenant_id)


def _record(
    *,
    resource_type: str = "knowledge_file",
    resource_id: str = "10",
    tenant_id: int = 5,
    status: str = "SUCCESS",
    parent_type: str = "folder",
    parent_id: str = "2",
    mode: str = "INHERIT",
    ancestor_ids: tuple[str, ...] = ("1", "2"),
) -> KnowledgeFilePermissionRecord:
    return KnowledgeFilePermissionRecord(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        owner_user_id=7,
        permission_version=4,
        context_version=f"file-{resource_id}-v4",
        parent_type=parent_type,
        parent_id=parent_id,
        mode=mode,
        ancestor_ids=ancestor_ids,
    )


@pytest.mark.asyncio
async def test_file_loader_reads_version_and_mode_through_facade(
    monkeypatch,
) -> None:
    file_row = SimpleNamespace(
        id=10,
        file_type=1,
        knowledge_id=11,
        file_level_path="",
        tenant_id=5,
        status=2,
        update_time=None,
        user_id=7,
    )
    knowledge_row = SimpleNamespace(id=11, type=0)
    monkeypatch.setattr(
        permission_module.KnowledgeFileDao,
        "query_by_id",
        AsyncMock(return_value=file_row),
    )
    monkeypatch.setattr(
        permission_module.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=knowledge_row),
    )
    version_port = _VersionPort()

    record = await KnowledgeFileDaoPermissionLoader(version_port).load_permission_record(
        "knowledge_file",
        "10",
    )

    assert record is not None
    assert record.mode == "INHERIT"
    assert version_port.version_calls == [
        {
            "tenant_id": 5,
            "resource_type": "knowledge_file",
            "resource_id": "10",
        }
    ]
    assert len(version_port.mode_targets) == 1
    target = version_port.mode_targets[0]
    assert target.resource_version == 4
    assert (target.parent_type, target.parent_id) == (
        "knowledge_library",
        "11",
    )


@pytest.mark.asyncio
async def test_file_target_is_verified_with_canonical_parent_and_action() -> None:
    record = _record()
    permission = _Permission()
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=_Loader((record,)),
        permission=permission,
    )

    allowed = await adapter.check_action(
        resource_type="knowledge_file",
        resource_id="10",
        actor=_actor(),
        action="download",
    )

    assert allowed is True
    target = permission.calls[0][1]["target"]
    assert (target.parent_type, target.parent_id) == ("folder", "2")
    assert permission.calls[0][1]["action"] == "download"


@pytest.mark.asyncio
async def test_create_defaults_to_inherit_and_protects_creator() -> None:
    record = _record(resource_id="11")
    permission = _Permission()
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=_Loader((record,)),
        permission=permission,
    )

    await adapter.authorize_created(record=record, actor=_actor())

    create = permission.calls[0][1]
    assert create["mode"] == "INHERIT"
    assert create["owner_user_id"] == 7
    assert create["protected"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("INHERIT", "CUSTOM"))
async def test_move_copy_and_delete_delegate_one_atomic_lifecycle_call(
    mode,
) -> None:
    source = _record(mode=mode)
    moved = replace(
        source,
        parent_id="3",
        ancestor_ids=("1", "3"),
        context_version="moved-v5",
    )
    copied = replace(
        moved,
        resource_id="12",
        owner_user_id=9,
        context_version="copy-v1",
    )
    permission = _Permission()
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=_Loader((source, moved, copied)),
        permission=permission,
    )

    await adapter.project_move(
        source=source,
        target=moved,
        actor=_actor(),
    )
    await adapter.project_copy(
        source=source,
        target=copied,
        actor=_actor(),
    )
    await adapter.project_delete(record=moved, actor=_actor())

    assert [call[0] for call in permission.calls] == [
        "move",
        "copy",
        "delete",
    ]
    assert permission.calls[0][1]["mode"] == mode
    assert permission.calls[1][1]["mode"] == mode
    assert permission.calls[1][1]["owner_user_id"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record",
    (
        None,
        _record(tenant_id=6),
        _record(status="FAILED"),
        _record(parent_id="10"),
        _record(ancestor_ids=("1", "10")),
    ),
)
async def test_missing_cross_tenant_invalid_status_and_cycles_fail_closed(
    record,
) -> None:
    permission = _Permission()
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=_Loader(tuple(row for row in (record,) if row is not None)),
        permission=permission,
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.resolve_permission_target(
            resource_type="knowledge_file",
            resource_id="10",
            actor=_actor(),
            action="visible",
        )
    assert permission.calls == []
