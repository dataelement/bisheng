from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.models.department_transfer_permission_cleanup import (
    DepartmentTransferCleanupEventStatus,
    DepartmentTransferCleanupItemStatus,
    DepartmentTransferCleanupItemType,
)
from bisheng.permission.domain.services.department_transfer_grant_guard import (
    DepartmentTransferGrantGuard,
    KnowledgeGrantSignature,
)
from bisheng.permission.domain.services.department_transfer_permission_cleanup_service import (
    DepartmentTransferPermissionCleanupService,
)


class _RaceRepository:
    def __init__(self):
        self.event = SimpleNamespace(
            id=81,
            tenant_id=1,
            user_id=7,
            old_department_id=10,
            new_department_id=20,
            trigger_source="local",
            status=DepartmentTransferCleanupEventStatus.PENDING,
            snapshot_complete=True,
            retry_count=0,
        )
        self.item = SimpleNamespace(
            id=1,
            event_id=81,
            item_key="rebac_tuple:knowledge_space:100:viewer",
            item_type=DepartmentTransferCleanupItemType.REBAC_TUPLE,
            user_id=7,
            resource_type="knowledge_space",
            resource_id="100",
            root_space_id=100,
            relation="viewer",
            source_ref=None,
            snapshot={},
            status=DepartmentTransferCleanupItemStatus.PENDING,
        )

    async def find_by_id(self, _event_id):
        return self.event

    async def claim_event(self, _event_id, *, now):
        return self.event.status not in DepartmentTransferCleanupEventStatus.TERMINAL

    async def list_processable_items(self, *, event_id, limit):
        if self.item.status in DepartmentTransferCleanupItemStatus.PROCESSABLE:
            return [self.item]
        return []

    async def list_active_events_for_user(self, *, user_id):
        if self.event.status in DepartmentTransferCleanupEventStatus.TERMINAL:
            return []
        return [self.event]

    async def protect_item(self, *, item_key, **_kwargs):
        if item_key == self.item.item_key and self.item.status in DepartmentTransferCleanupItemStatus.PROCESSABLE:
            self.item.status = DepartmentTransferCleanupItemStatus.PROTECTED
        return self.item

    async def transition_item(self, _item_id, *, to_status, **_kwargs):
        if self.item.status not in DepartmentTransferCleanupItemStatus.PROCESSABLE:
            return False
        self.item.status = to_status
        return True

    async def refresh_event_counts(self, _event_id):
        return None

    async def mark_event_succeeded(self, _event_id, *, completed_at):
        self.event.status = DepartmentTransferCleanupEventStatus.SUCCEEDED
        return self.event

    async def mark_event_failed(self, *_args, **_kwargs):
        self.event.status = DepartmentTransferCleanupEventStatus.FAILED
        return self.event


def _build_services():
    repository = _RaceRepository()
    user_lock = asyncio.Lock()
    permission_state = {"present": True}

    async def _authorize(**_kwargs):
        permission_state["present"] = False

    guard = DepartmentTransferGrantGuard(
        repository=repository,
        current_department_loader=AsyncMock(return_value=20),
        lock_factory=lambda _user_id: user_lock,
    )
    cleanup = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        repository=repository,
        permission_service=SimpleNamespace(authorize=_authorize),
        binding_service=SimpleNamespace(remove_binding_if_matches=AsyncMock()),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: user_lock,
    )

    async def grant():
        await guard.protect_knowledge_grants(
            user_id=7,
            grants=[
                KnowledgeGrantSignature(
                    resource_type="knowledge_space",
                    resource_id="100",
                    relation="viewer",
                )
            ],
            source="admin_grant",
            operation_id="race-operation",
        )
        permission_state["present"] = True

    return cleanup, grant, permission_state


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["grant_then_cleanup", "cleanup_then_grant"])
async def test_same_signature_regrant_survives_both_cleanup_orderings(order):
    cleanup, grant, permission_state = _build_services()

    if order == "grant_then_cleanup":
        await grant()
        await cleanup.process_event(81)
    else:
        await cleanup.process_event(81)
        await grant()

    assert permission_state["present"] is True


@pytest.mark.asyncio
async def test_a_to_b_to_a_does_not_restore_revoked_permission():
    cleanup, _grant, permission_state = _build_services()

    first = await cleanup.process_event(81)
    assert first.succeeded is True
    assert permission_state["present"] is False

    second_repository = _RaceRepository()
    second_repository.event.id = 82
    second_repository.event.old_department_id = 20
    second_repository.event.new_department_id = 10
    second_repository.item.status = DepartmentTransferCleanupItemStatus.SKIPPED
    second_cleanup = DepartmentTransferPermissionCleanupService(
        session=SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()),
        repository=second_repository,
        permission_service=SimpleNamespace(authorize=AsyncMock()),
        binding_service=SimpleNamespace(),
        file_grant_repository=SimpleNamespace(),
        cache_invalidator=AsyncMock(),
        projection_refresher=AsyncMock(),
        audit_writer=SimpleNamespace(),
        lock_factory=lambda _user_id: asyncio.Lock(),
    )

    reverse = await second_cleanup.process_event(82)

    assert reverse.succeeded is True
    assert permission_state["present"] is False
