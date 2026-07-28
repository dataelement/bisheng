from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
)
from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
from bisheng.permission.domain.services.department_transfer_grant_guard import (
    DepartmentTransferGrantGuard,
    DepartmentTransferGrantRetryableError,
    KnowledgeGrantSignature,
)


@pytest.mark.asyncio
async def test_same_signature_grant_protects_every_unfinished_event():
    events = [
        type(
            "Event",
            (),
            {
                "id": 61,
                "tenant_id": 1,
                "user_id": 7,
                "old_department_id": 10,
                "new_department_id": 20,
                "status": DepartmentTransferCleanupEventStatus.PENDING,
                "changed_at": datetime(2026, 7, 24, 12, 0, 0),
            },
        )(),
        type(
            "Event",
            (),
            {
                "id": 62,
                "tenant_id": 1,
                "user_id": 7,
                "old_department_id": 20,
                "new_department_id": 30,
                "status": DepartmentTransferCleanupEventStatus.FAILED,
                "changed_at": datetime(2026, 7, 24, 12, 1, 0),
            },
        )(),
    ]
    repository = type(
        "Repository",
        (),
        {
            "list_active_events_for_user": AsyncMock(return_value=events),
            "protect_item": AsyncMock(),
        },
    )()
    guard = DepartmentTransferGrantGuard(
        repository=repository,
        current_department_loader=AsyncMock(return_value=30),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    await guard.protect_knowledge_grants(
        user_id=7,
        grants=[
            KnowledgeGrantSignature(
                resource_type="knowledge_space",
                resource_id="99",
                relation="viewer",
                model_id="custom-view",
            )
        ],
        source="admin_grant",
        operation_id="op-1",
    )

    tuple_calls = [
        call
        for call in repository.protect_item.await_args_list
        if call.kwargs["item_key"] == "rebac_tuple:knowledge_space:99:viewer"
    ]
    assert len(tuple_calls) == 2
    assert {call.kwargs["event_id"] for call in tuple_calls} == {61, 62}


@pytest.mark.asyncio
async def test_preparing_event_blocks_grant_until_department_state_is_determined():
    event = type(
        "Event",
        (),
        {
            "id": 63,
            "tenant_id": 1,
            "user_id": 7,
            "old_department_id": 10,
            "new_department_id": 20,
            "status": DepartmentTransferCleanupEventStatus.PREPARING,
            "changed_at": None,
        },
    )()
    repository = type(
        "Repository",
        (),
        {
            "list_active_events_for_user": AsyncMock(return_value=[event]),
            "protect_item": AsyncMock(),
            "activate_event": AsyncMock(),
        },
    )()
    guard = DepartmentTransferGrantGuard(
        repository=repository,
        current_department_loader=AsyncMock(return_value=10),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    with pytest.raises(DepartmentTransferGrantRetryableError):
        await guard.protect_department_file_grant(
            user_id=7,
            space_id=100,
            file_id=301,
            approval_instance_id=5001,
        )

    repository.protect_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_permission_service_guards_only_direct_user_knowledge_grants(monkeypatch):
    from bisheng.permission.domain.services import (
        department_transfer_grant_guard as guard_module,
    )
    from bisheng.permission.domain.services.permission_service import PermissionService

    lock_state = {"active": False}
    call_order: list[str] = []

    class _LockProbe:
        async def __aenter__(self):
            lock_state["active"] = True
            call_order.append("lock_enter")

        async def __aexit__(self, *_args):
            call_order.append("lock_exit")
            lock_state["active"] = False

    async def _protect(**_kwargs):
        assert lock_state["active"] is True
        call_order.append("protect")

    async def _write(*_args, **_kwargs):
        assert lock_state["active"] is True
        call_order.append("write")

    protect = AsyncMock(side_effect=_protect)
    monkeypatch.setattr(guard_module, "protect_knowledge_direct_grants", protect)
    monkeypatch.setattr(
        guard_module,
        "_DepartmentTransferUserLock",
        lambda _user_id: _LockProbe(),
    )
    monkeypatch.setattr(
        PermissionService,
        "_legacy_alias_object_types",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        PermissionService,
        "_expand_subject",
        AsyncMock(return_value=["user:7"]),
    )
    monkeypatch.setattr(
        PermissionService,
        "_affected_user_ids_for_subject",
        AsyncMock(return_value=set()),
    )
    monkeypatch.setattr(
        PermissionService,
        "batch_write_tuples",
        AsyncMock(side_effect=_write),
    )

    await PermissionService.authorize(
        object_type="knowledge_space",
        object_id="100",
        grants=[
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=7,
                relation="viewer",
                model_id="custom-viewer",
            ),
            AuthorizeGrantItem(
                subject_type="department",
                subject_id=10,
                relation="viewer",
            ),
            AuthorizeGrantItem(
                subject_type="user",
                subject_id=8,
                relation="owner",
            ),
        ],
        revokes=[],
        enforce_fga_success=True,
    )

    protect.assert_awaited_once()
    assert protect.await_args.kwargs["user_id"] == 7
    signature = protect.await_args.kwargs["grants"][0]
    assert signature.resource_type == "knowledge_space"
    assert signature.resource_id == "100"
    assert signature.relation == "viewer"
    assert signature.model_id == "custom-viewer"
    assert protect.await_args.kwargs["lock_held"] is True
    assert call_order == ["lock_enter", "protect", "write", "lock_exit"]
