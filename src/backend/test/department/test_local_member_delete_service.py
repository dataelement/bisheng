from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.department import DepartmentMemberDeleteTransferReceiverNotFoundError
from bisheng.department.domain.services.local_member_asset_inventory import LocalMemberAssetInventory
from bisheng.department.domain.services.local_member_delete_service import LocalMemberDeleteService
from bisheng.department.domain.services.local_member_transfer_receiver import (
    ResolvedTransferReceiver,
    resolve_local_member_transfer_receiver,
)


@pytest.mark.asyncio
async def test_resolve_receiver_picks_first_active_department_admin(monkeypatch):
    dept = SimpleNamespace(id=20, path="/1/20/", name="信息部")
    admin_a = SimpleNamespace(user_id=100, user_name="AdminA", delete=0)
    admin_b = SimpleNamespace(user_id=101, user_name="AdminB", delete=0)

    monkeypatch.setattr(
        "bisheng.department.domain.services.local_member_transfer_receiver.DepartmentDao.aget_by_id",
        AsyncMock(return_value=dept),
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.local_member_transfer_receiver.DepartmentAdminGrantDao.aget_user_ids_by_department",
        AsyncMock(return_value=[101, 100]),
    )

    async def _aget_user(user_id: int):
        return admin_a if user_id == 100 else admin_b

    monkeypatch.setattr(
        "bisheng.department.domain.services.local_member_transfer_receiver.UserDao.aget_user",
        _aget_user,
    )
    monkeypatch.setattr(
        "bisheng.department.domain.services.local_member_transfer_receiver.ResourceOwnershipService._check_receiver_visible",
        AsyncMock(return_value=None),
    )

    receiver = await resolve_local_member_transfer_receiver(
        user_id=42,
        start_department_id=20,
        tenant_ids=[1],
    )

    assert receiver is not None
    assert receiver.user_id == 100
    assert receiver.source == "department_admin"
    assert receiver.department_id == 20


@pytest.mark.asyncio
async def test_execute_transfers_assets_deletes_linsight_and_soft_deletes_user():
    inventory = LocalMemberAssetInventory(
        tenant_ids=[1],
        counts={"workflow": 1},
        transfer_batches=[
            SimpleNamespace(tenant_id=1, resource_type="workflow", resource_ids=["flow-1"]),
        ],
        linsight_counts={"linsight_sop": 2},
    )
    receiver = ResolvedTransferReceiver(user_id=100, user_name="admin", source="platform_admin")
    validate_member = AsyncMock()
    soft_delete = AsyncMock()

    with (
        patch.object(
            LocalMemberDeleteService,
            "_resolve_start_department_id",
            AsyncMock(return_value=20),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.build_local_member_asset_inventory",
            AsyncMock(return_value=inventory),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.resolve_local_member_transfer_receiver",
            AsyncMock(return_value=receiver),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.transfer_local_member_assets",
            AsyncMock(return_value=(1, {"workflow": 1}, ["log-1"])),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.delete_local_member_linsight_assets",
            AsyncMock(return_value={"linsight_sop": 2}),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.recycle_local_member_personal_knowledge_spaces",
            AsyncMock(return_value=SimpleNamespace(performed=False, recycled_count=0, folder_name="", recycle_batch_id=None)),
        ),
        patch.object(
            LocalMemberDeleteService,
            "soft_delete_local_member_user",
            soft_delete,
        ),
    ):
        result = await LocalMemberDeleteService.execute(
            dept_id="BS@test",
            user_id=42,
            login_user=SimpleNamespace(user_id=7, tenant_id=1),
            validate_member=validate_member,
        )

    validate_member.assert_awaited_once()
    soft_delete.assert_awaited_once_with(42)
    assert result.deleted_user_id == 42
    assert result.transfer.performed is True
    assert result.transfer.transferred_count == 1
    assert result.transfer.receiver.user_id == 100
    assert result.linsight_deleted.performed is True
    assert result.linsight_deleted.deleted_count == 2


@pytest.mark.asyncio
async def test_execute_raises_when_transfer_assets_exist_but_receiver_missing():
    inventory = LocalMemberAssetInventory(
        tenant_ids=[1],
        counts={"assistant": 1},
        transfer_batches=[
            SimpleNamespace(tenant_id=1, resource_type="assistant", resource_ids=["a-1"]),
        ],
    )

    with (
        patch.object(
            LocalMemberDeleteService,
            "_resolve_start_department_id",
            AsyncMock(return_value=20),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.build_local_member_asset_inventory",
            AsyncMock(return_value=inventory),
        ),
        patch(
            "bisheng.department.domain.services.local_member_delete_service.resolve_local_member_transfer_receiver",
            AsyncMock(return_value=None),
        ),
        patch.object(
            LocalMemberDeleteService,
            "soft_delete_local_member_user",
            AsyncMock(),
        ),
    ):
        with pytest.raises(DepartmentMemberDeleteTransferReceiverNotFoundError):
            await LocalMemberDeleteService.execute(
                dept_id="BS@test",
                user_id=42,
                login_user=SimpleNamespace(user_id=7, tenant_id=1),
                validate_member=AsyncMock(),
            )
