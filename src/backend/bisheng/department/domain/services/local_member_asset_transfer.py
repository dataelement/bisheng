"""Transfer F018 assets and delete Linsight rows during local member delete."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.department.domain.services.local_member_asset_inventory import (
    LocalMemberAssetInventory,
)
from bisheng.department.domain.services.local_member_transfer_receiver import ResolvedTransferReceiver
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.models.linsight_sop import LinsightSOP, LinsightSOPRecord
from bisheng.tenant.domain.services.resource_ownership_service import ResourceOwnershipService
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao


async def _resolve_transfer_operator(operator: object) -> object:
    is_global_super = getattr(operator, "is_global_super", None)
    if callable(is_global_super) and is_global_super():
        return operator
    is_admin = getattr(operator, "is_admin", None)
    if callable(is_admin) and is_admin():
        return operator

    rows = await UserRoleDao.aget_roles_user([AdminRole])
    for row in sorted(rows, key=lambda item: int(item.user_id)):
        user = await UserDao.aget_user(int(row.user_id))
        if user is None or int(getattr(user, "delete", 0) or 0) != 0:
            continue
        return user
    return operator


async def transfer_local_member_assets(
    *,
    from_user_id: int,
    inventory: LocalMemberAssetInventory,
    receiver: ResolvedTransferReceiver,
    operator: object,
    reason: str,
) -> tuple[int, dict[str, int], list[str | None]]:
    if not inventory.transfer_batches:
        return 0, {}, []

    transfer_operator = await _resolve_transfer_operator(operator)
    transferred_count = 0
    counts_by_type: dict[str, int] = defaultdict(int)
    transfer_log_ids: list[str | None] = []

    for batch in inventory.transfer_batches:
        result = await ResourceOwnershipService.transfer_owner(
            tenant_id=batch.tenant_id,
            from_user_id=from_user_id,
            to_user_id=receiver.user_id,
            resource_types=[batch.resource_type],
            resource_ids=batch.resource_ids,
            reason=reason,
            operator=transfer_operator,
        )
        batch_count = int(result.get("transferred_count", 0))
        transferred_count += batch_count
        counts_by_type[batch.resource_type] += batch_count
        transfer_log_ids.append(result.get("transfer_log_id"))

    return transferred_count, dict(counts_by_type), transfer_log_ids


async def delete_local_member_linsight_assets(
    *,
    user_id: int,
    expected_counts: dict[str, int] | None = None,
) -> dict[str, int]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            await session.exec(delete(LinsightSessionVersion).where(LinsightSessionVersion.user_id == user_id))
            await session.exec(delete(LinsightSOP).where(LinsightSOP.user_id == user_id))
            await session.exec(delete(LinsightSOPRecord).where(LinsightSOPRecord.user_id == user_id))
            await session.commit()
    if expected_counts is not None:
        return dict(expected_counts)
    return {
        "linsight_session_version": 0,
        "linsight_sop": 0,
        "linsight_sop_record": 0,
    }
