from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupItemStatus,
)
from bisheng.permission.domain.services.department_transfer_permission_snapshot_service import (
    DepartmentTransferPermissionSnapshotService,
)


@pytest.mark.asyncio
async def test_snapshot_unions_sources_and_hard_excludes_protected_identities():
    event = type("Event", (), {"id": 51, "tenant_id": 1, "user_id": 7})()
    bindings = [
        {
            "key": "binding-space",
            "resource_type": "knowledge_space",
            "resource_id": "100",
            "subject_type": "user",
            "subject_id": 7,
            "relation": "viewer",
            "model_id": "custom-view",
        },
        {
            "key": "binding-personal",
            "resource_type": "knowledge_space",
            "resource_id": "200",
            "subject_type": "user",
            "subject_id": 7,
            "relation": "manager",
            "model_id": "manager",
        },
    ]
    fga = type(
        "FGA",
        (),
        {
            "read_tuples": AsyncMock(
                return_value=[
                    {"user": "user:7", "relation": "viewer", "object": "knowledge_space:100"},
                    {"user": "user:7", "relation": "owner", "object": "knowledge_space:100"},
                    {"user": "user:7", "relation": "editor", "object": "knowledge_file:301"},
                    {"user": "user:7", "relation": "viewer", "object": "folder:999"},
                    {"user": "department:8#member", "relation": "viewer", "object": "folder:302"},
                ]
            )
        },
    )()
    source_repository = type(
        "Sources",
        (),
        {
            "resolve_resource_contexts": AsyncMock(
                return_value={
                    ("knowledge_space", "100"): {
                        "root_space_id": 100,
                        "scope_level": "department",
                        "creator_user_id": 8,
                        "uploader_user_id": None,
                    },
                    ("knowledge_space", "200"): {
                        "root_space_id": 200,
                        "scope_level": "personal",
                        "creator_user_id": 7,
                        "uploader_user_id": None,
                    },
                    ("knowledge_file", "301"): {
                        "root_space_id": 100,
                        "scope_level": "department",
                        "creator_user_id": 8,
                        "uploader_user_id": 7,
                    },
                }
            ),
            "list_active_memberships": AsyncMock(
                return_value=[
                    type(
                        "Member",
                        (),
                        {
                            "id": 81,
                            "business_id": "100",
                            "user_role": "member",
                            "membership_source": "manual",
                            "relation": "viewer",
                        },
                    )(),
                    type(
                        "Member",
                        (),
                        {
                            "id": 82,
                            "business_id": "100",
                            "user_role": "creator",
                            "membership_source": "manual",
                            "relation": "owner",
                        },
                    )(),
                ]
            ),
            "list_active_department_file_grants": AsyncMock(
                return_value=[
                    type(
                        "Grant",
                        (),
                        {
                            "id": 91,
                            "space_id": 100,
                            "file_id": 301,
                            "approval_instance_id": 5001,
                            "granted_at": None,
                        },
                    )()
                ]
            ),
        },
    )()
    captured: dict[str, dict] = {}

    async def upsert_item(**kwargs):
        captured[kwargs["item_key"]] = kwargs
        return type("Item", (), kwargs)()

    repository = type(
        "Repository",
        (),
        {
            "upsert_item": AsyncMock(side_effect=upsert_item),
            "set_snapshot_complete": AsyncMock(),
        },
    )()
    binding_service = type("Bindings", (), {"get_bindings": AsyncMock(return_value=bindings)})()
    service = DepartmentTransferPermissionSnapshotService(
        session=None,
        repository=repository,
        source_repository=source_repository,
        binding_service=binding_service,
        fga_client=fga,
    )

    await service.capture(event)

    tuple_item = captured["rebac_tuple:knowledge_space:100:viewer"]
    assert tuple_item["status"] == DepartmentTransferCleanupItemStatus.PENDING
    assert tuple_item["snapshot"]["model_id"] == "custom-view"
    assert set(tuple_item["snapshot"]["sources"]) == {"binding", "openfga"}
    assert "rebac_tuple:knowledge_space:100:owner" not in captured

    assert captured["rebac_tuple:knowledge_space:200:manager"]["status"] == (
        DepartmentTransferCleanupItemStatus.SKIPPED
    )
    assert captured["rebac_tuple:knowledge_file:301:editor"]["status"] == (
        DepartmentTransferCleanupItemStatus.SKIPPED
    )
    assert captured["rebac_tuple:folder:999:viewer"]["status"] == (
        DepartmentTransferCleanupItemStatus.SKIPPED
    )
    assert "space_membership:100" in captured
    assert "department_file_grant:100:301" in captured
    repository.set_snapshot_complete.assert_awaited_once_with(51, complete=True, error=None)
