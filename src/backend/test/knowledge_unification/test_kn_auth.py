"""Business lifecycle is separate from F048 actions and processing conflicts.

Container and file adapters are real; the permission transport is local. The
use-case conflict/retrieval gates remain the responsibility of T098/T102.
"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.knowledge.domain.models.knowledge import KnowledgeState
from bisheng.knowledge.domain.services.knowledge_permission_service import (
    F048KnowledgeContainerPermissionAdapter,
    F048KnowledgeFilePermissionAdapter,
    KnowledgeContainerPermissionRecord,
    KnowledgeFilePermissionRecord,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@pytest.fixture
def actor():
    return PermissionActor(user_id=7, current_tenant_id=5)


def container(resource_type="knowledge_space", kind="SPACE", status="PUBLISHED"):
    return KnowledgeContainerPermissionRecord(5, resource_type, "11", status, kind, 7, 3, "ctx3")


@pytest.mark.parametrize("state", list(KnowledgeState))
@pytest.mark.parametrize(
    "resource_type,kind", [("knowledge_space", "SPACE"), ("knowledge_library", "NORMAL"), ("knowledge_library", "QA")]
)
async def test_known_container_lifecycle_preserves_exact_f048_decisions(actor, state, resource_type, kind):
    record = container(resource_type, kind, state.name)
    permission = SimpleNamespace(
        check_action=AsyncMock(side_effect=lambda _actor, _target, action: action == "visible")
    )
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)), permission=permission
    )
    assert await adapter.check_action(resource_type=resource_type, resource_id="11", actor=actor, action="visible")
    assert not await adapter.check_action(resource_type=resource_type, resource_id="11", actor=actor, action="edit")
    assert [call.args[2] for call in permission.check_action.await_args_list] == ["visible", "edit"]
    assert permission.check_action.await_args.args[1].resource_type == resource_type


@pytest.mark.parametrize(
    "override", [{"tenant_id": 6}, {"kind": "PRIVATE"}, {"status": "DELETED"}, {"resource_id": "12"}]
)
async def test_lifecycle_access_does_not_loosen_business_identity(actor, override):
    permission = SimpleNamespace(check_action=AsyncMock(return_value=True))
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=replace(container(), **override))),
        permission=permission,
    )
    with pytest.raises(PermissionInvalidResourceError):
        await adapter.check_action(resource_type="knowledge_space", resource_id="11", actor=actor, action="visible")
    permission.check_action.assert_not_awaited()


async def test_loaded_container_batch_keeps_rebuilding_and_unpublished(actor):
    records = tuple(
        replace(container(status=state.name), resource_id=str(index)) for index, state in enumerate(KnowledgeState, 1)
    )
    adapter = F048KnowledgeContainerPermissionAdapter(
        loader=SimpleNamespace(load_permission_records_from_rows=AsyncMock(return_value=records)),
        permission=SimpleNamespace(),
    )
    targets = await adapter.resolve_permission_targets_from_rows(rows=[], resource_type="knowledge_space", actor=actor)
    assert [target.resource_id for target in targets] == [str(index) for index in range(1, 6)]


@pytest.mark.parametrize("mode", ["INHERIT", "CUSTOM"])
async def test_file_rename_stays_independent_of_container_edit_and_download(actor, mode):
    record = KnowledgeFilePermissionRecord(
        5, "knowledge_file", "21", "PROCESSING", 7, 3, "ctx3", "knowledge_space", "11", mode
    )
    permission = SimpleNamespace(check_action=AsyncMock(side_effect=lambda _actor, _target, action: action == "rename"))
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)), permission=permission
    )
    for action, allowed in [("rename", True), ("edit", False), ("download", False)]:
        assert (
            await adapter.check_action(resource_type="knowledge_file", resource_id="21", actor=actor, action=action)
            is allowed
        )
    assert [call.args[2] for call in permission.check_action.await_args_list] == ["rename", "edit", "download"]
    assert all(call.args[1].parent_id == "11" for call in permission.check_action.await_args_list)


@pytest.mark.parametrize("mode", ["INHERIT", "CUSTOM"])
async def test_processing_file_visibility_and_download_remain_distinct(actor, mode):
    record = KnowledgeFilePermissionRecord(
        5, "knowledge_file", "21", "PROCESSING", 7, 3, "ctx3", "knowledge_space", "11", mode
    )
    permission = SimpleNamespace(
        check_action=AsyncMock(side_effect=lambda _actor, _target, action: action == "visible")
    )
    adapter = F048KnowledgeFilePermissionAdapter(
        loader=SimpleNamespace(load_permission_record=AsyncMock(return_value=record)), permission=permission
    )
    assert await adapter.check_action(resource_type="knowledge_file", resource_id="21", actor=actor, action="visible")
    assert not await adapter.check_action(
        resource_type="knowledge_file", resource_id="21", actor=actor, action="download"
    )
