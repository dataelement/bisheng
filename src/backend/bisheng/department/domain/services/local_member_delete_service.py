"""Orchestrate local member delete with asset transfer and Linsight cleanup."""

from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import select

from bisheng.common.errcode.department import DepartmentMemberDeleteTransferReceiverNotFoundError
from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.department import UserDepartment
from bisheng.database.models.user_group import UserGroup
from bisheng.department.domain.schemas.local_member_delete_schema import (
    LocalMemberDeleteExecuteResponse,
    LocalMemberDeleteLinsightSummary,
    LocalMemberDeletePersonalRecycleSummary,
    LocalMemberDeletePreviewResponse,
    LocalMemberDeleteTransferSummary,
)
from bisheng.department.domain.services.department_change_handler import DepartmentChangeHandler
from bisheng.department.domain.services.local_member_asset_inventory import (
    build_local_member_asset_inventory,
)
from bisheng.department.domain.services.local_member_asset_transfer import (
    delete_local_member_linsight_assets,
    transfer_local_member_assets,
)
from bisheng.department.domain.services.local_member_personal_recycle import (
    recycle_local_member_personal_knowledge_spaces,
)
from bisheng.department.domain.services.local_member_transfer_receiver import (
    resolve_local_member_transfer_receiver,
)
from bisheng.tenant.domain.services.resource_ownership_service import MAX_BATCH
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole


class LocalMemberDeleteService:
    TRANSFER_REASON = "local organization member delete auto transfer"

    @classmethod
    async def preview(
        cls,
        *,
        dept_id: str,
        user_id: int,
        login_user,
        validate_member,
    ) -> LocalMemberDeletePreviewResponse:
        await validate_member(dept_id, user_id, login_user)
        start_department_id = await cls._resolve_start_department_id(user_id, dept_id)
        inventory = await build_local_member_asset_inventory(
            user_id=user_id,
            fallback_tenant_id=int(getattr(login_user, "tenant_id", 0) or 0) or None,
            batch_size=MAX_BATCH,
        )
        proposed_receiver = None
        if inventory.has_transferable_assets:
            receiver = await resolve_local_member_transfer_receiver(
                user_id=user_id,
                start_department_id=start_department_id,
                tenant_ids=inventory.tenant_ids,
            )
            proposed_receiver = receiver.to_preview() if receiver is not None else None

        return LocalMemberDeletePreviewResponse(
            has_assets=(
                inventory.transfer_count > 0
                or inventory.linsight_delete_count > 0
                or inventory.personal_knowledge_space_count > 0
            ),
            counts=inventory.counts,
            transfer_count=inventory.transfer_count,
            linsight_delete_count=inventory.linsight_delete_count,
            proposed_receiver=proposed_receiver,
        )

    @classmethod
    async def execute(
        cls,
        *,
        dept_id: str,
        user_id: int,
        login_user,
        validate_member,
    ) -> LocalMemberDeleteExecuteResponse:
        await validate_member(dept_id, user_id, login_user)
        start_department_id = await cls._resolve_start_department_id(user_id, dept_id)
        inventory = await build_local_member_asset_inventory(
            user_id=user_id,
            fallback_tenant_id=int(getattr(login_user, "tenant_id", 0) or 0) or None,
            batch_size=MAX_BATCH,
        )

        transfer_summary = LocalMemberDeleteTransferSummary(performed=False)
        if inventory.has_transferable_assets:
            receiver = await resolve_local_member_transfer_receiver(
                user_id=user_id,
                start_department_id=start_department_id,
                tenant_ids=inventory.tenant_ids,
            )
            if receiver is None:
                raise DepartmentMemberDeleteTransferReceiverNotFoundError()
            transferred_count, counts_by_type, transfer_log_ids = await transfer_local_member_assets(
                from_user_id=user_id,
                inventory=inventory,
                receiver=receiver,
                operator=login_user,
                reason=cls.TRANSFER_REASON,
            )
            transfer_summary = LocalMemberDeleteTransferSummary(
                performed=True,
                receiver=receiver.to_preview(),
                transferred_count=transferred_count,
                counts_by_type=counts_by_type,
                transfer_log_ids=[log_id for log_id in transfer_log_ids if log_id],
            )

        personal_recycle_summary = LocalMemberDeletePersonalRecycleSummary()
        if inventory.personal_knowledge_space_ids:
            from bisheng.user.domain.models.user import UserDao

            deleted_user = await UserDao.aget_user(user_id)
            recycle_result = await recycle_local_member_personal_knowledge_spaces(
                user_id=user_id,
                user_name=str(getattr(deleted_user, "user_name", "") or ""),
                space_ids=inventory.personal_knowledge_space_ids,
                operator=login_user,
            )
            personal_recycle_summary = LocalMemberDeletePersonalRecycleSummary(
                performed=recycle_result.performed,
                recycled_count=recycle_result.recycled_count,
                folder_name=recycle_result.folder_name,
                recycle_batch_id=recycle_result.recycle_batch_id,
            )

        linsight_summary = LocalMemberDeleteLinsightSummary(performed=False)
        if inventory.linsight_delete_count > 0:
            linsight_counts = await delete_local_member_linsight_assets(
                user_id=user_id,
                expected_counts=inventory.linsight_counts,
            )
            linsight_summary = LocalMemberDeleteLinsightSummary(
                performed=True,
                deleted_count=sum(linsight_counts.values()),
                counts=linsight_counts,
            )

        await cls.soft_delete_local_member_user(user_id)

        return LocalMemberDeleteExecuteResponse(
            deleted_user_id=user_id,
            transfer=transfer_summary,
            linsight_deleted=linsight_summary,
            personal_recycled=personal_recycle_summary,
        )

    @classmethod
    async def _resolve_start_department_id(cls, user_id: int, dept_id: str) -> int | None:
        from bisheng.database.models.department import DepartmentDao, UserDepartmentDao

        primary = await UserDepartmentDao.aget_user_primary_department(user_id)
        if primary is not None:
            return int(primary.department_id)
        department = await DepartmentDao.aget_by_dept_id(dept_id)
        return int(department.id) if department is not None and department.id is not None else None

    @classmethod
    async def soft_delete_local_member_user(cls, user_id: int) -> None:
        from bisheng.database.models.department import UserDepartmentDao
        from bisheng.user.domain.services.user import UserService

        uds = await UserDepartmentDao.aget_user_departments(user_id)
        dept_ids = [int(item.department_id) for item in uds]

        async with get_async_db_session() as session:
            await session.exec(delete(UserDepartment).where(UserDepartment.user_id == user_id))
            await session.exec(
                delete(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id != AdminRole,
                ),
            )
            await session.exec(delete(UserGroup).where(UserGroup.user_id == user_id))
            db_user = (await session.exec(select(User).where(User.user_id == user_id))).first()
            if db_user:
                db_user.delete = 1
                session.add(db_user)
            await session.commit()

        if db_user:
            await UserService.ainvalidate_jwt_after_account_disabled(user_id)
            await UserService.on_account_disabled(user_id)

        for department_id in dept_ids:
            ops = DepartmentChangeHandler.on_member_removed(department_id, user_id)
            await DepartmentChangeHandler.execute_async(ops)
